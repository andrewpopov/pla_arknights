"""Observe current expedition water yield; never infer it from warehouse totals."""

from maa_sand_config import WATER_STAGES, CheckpointError
from maa_sand_food import load_food_catalog, observed_energy
from maa_sand_settlement import enlarged_count, quantity

BAG_FOOD_ITEMS = {"Tenderloin": "sandbox_1_venison", "Wing": "sandbox_1_poultry"}


def water_count_roi(hit):
    rect = hit.get("rect", [])
    if (
        hit.get("score", 0) < 0.9
        or len(rect) != 4
        or any(type(v) is not int for v in rect)
    ):
        raise CheckpointError("Bag water icon requires a confident native rectangle")
    x, y, w, h = rect
    if not (340 <= x <= 917 and 230 <= y <= 434 and w == 43 and h == 46):
        raise CheckpointError("Water icon lies outside the reviewed bag item area")
    # The explicit +N label is below/right of this cropped icon. Warehouse row excluded.
    return [x + 27, y + 45, 52, 30]


def read_bag_water(runtime, path):
    hits = runtime.matches(path, ["SandAuto@BagHeader", "SandAuto@BagWater"])
    if hits.get("SandAuto@BagHeader", {}).get("score", 0) < 0.9:
        raise CheckpointError("Current-operation bag is not identified")
    hit = hits.get("SandAuto@BagWater")
    if hit is None:
        return {
            "image": str(path),
            "water": None,
            "inventory_updated": False,
            "status": "water_unknown",
            "reason": "Unmatched bag item is not zero water.",
        }
    roi = water_count_roi(hit)
    reads = runtime.ocr(path, roi)
    count = quantity(reads)
    return {
        "image": str(path),
        "water": count,
        "inventory_updated": False,
        "status": "current_operation_water",
        "evidence": {"icon": hit, "roi": roi, "quantity_reads": reads},
    }


def food_count_roi(hit):
    rect = hit.get("rect", [])
    if (
        hit.get("score", 0) < 0.92
        or len(rect) != 4
        or any(type(v) is not int for v in rect)
    ):
        raise CheckpointError("Bag food icon requires a confident native rectangle")
    x, y, w, h = rect
    if not (340 <= x <= 883 and 230 <= y <= 430 and (w, h) == (42, 42)):
        raise CheckpointError(
            "Food icon lies outside the reviewed operation-bag item area"
        )
    return [x + 25, y + 40, 52, 30]


def read_bag_food(runtime, path, catalog=None):
    """Count only reviewed native item art; unmatched inventory remains unknown."""
    tasks = ["SandAuto@BagHeader", *("SandAuto@Bag" + key for key in BAG_FOOD_ITEMS)]
    hits = runtime.matches(path, tasks)
    if hits.get("SandAuto@BagHeader", {}).get("score", 0) < 0.9:
        raise CheckpointError(
            "Current-operation bag is not identified for food accounting"
        )
    report = {
        "image": str(path),
        "status": "food_unknown",
        "raw_food_counts": {},
        "base_energy_observed": None,
        "evidence": {},
        "inventory_updated": False,
        "raw_inventory_complete": False,
        "conversion_multiplier_applied": False,
    }
    occupied = set()
    for name, item_id in BAG_FOOD_ITEMS.items():
        hit = hits.get("SandAuto@Bag" + name)
        if hit is None:
            continue
        roi = food_count_roi(hit)
        location = tuple(hit["rect"])
        if location in occupied:
            raise CheckpointError("Two food identities matched the same bag item")
        occupied.add(location)
        reads = runtime.ocr(path, roi)
        prepared = None
        try:
            value = quantity(reads)
        except CheckpointError:
            prepared, enlarged_roi = enlarged_count(path, roi)
            reads = runtime.ocr(prepared, enlarged_roi)
            value = quantity(reads)
        report["raw_food_counts"][item_id] = value
        report["evidence"][item_id] = {
            "icon": hit,
            "roi": roi,
            "quantity_reads": reads,
            "prepared_image": str(prepared) if prepared else None,
        }
    if report["raw_food_counts"]:
        report.update(
            status="current_operation_food",
            base_energy_observed=observed_energy(
                report["raw_food_counts"], catalog or load_food_catalog(), multiplier=1
            ),
        )
    return report


def water_goal(observation, pumps):
    if type(pumps) is not int or pumps not in (1, 2):
        raise CheckpointError("Guide water target supports one or two pumps only")
    if (
        observation.get("status") != "current_operation_water"
        or type(observation.get("water")) is not int
        or observation["water"] <= 0
    ):
        raise CheckpointError(
            "Water target requires an observed positive current-operation yield"
        )
    target = pumps * 10
    return {
        "target_water": target,
        "observed_water": observation["water"],
        "ready_to_save": observation["water"] >= target,
        "inventory_updated": False,
        "settlement_required": True,
    }


def hunting_goal(observation, pumps=1, minimum_base_energy=80):
    if (
        type(minimum_base_energy) is not int
        or not 1 <= minimum_base_energy <= 1000
        or type(pumps) is not int
        or pumps != 1
    ):
        raise CheckpointError(
            "Hunting target requires one pump and a bounded positive food target"
        )
    water = water_goal(observation, pumps)
    food = observation.get("food", {})
    if not observation.get("image") or food.get("image") != observation["image"]:
        raise CheckpointError(
            "Food and water must belong to the same operation-bag image"
        )
    counts = food.get("raw_food_counts", {})
    if not isinstance(counts, dict) or any(
        key not in BAG_FOOD_ITEMS.values() or type(value) is not int or value <= 0
        for key, value in counts.items()
    ):
        raise CheckpointError(
            "Hunting bag supports exact positive reviewed food counts only"
        )
    energy = observed_energy(counts, multiplier=1) if counts else None
    if food.get("base_energy_observed") != energy or (
        counts and food.get("status") != "current_operation_food"
    ):
        raise CheckpointError(
            "Food energy must agree with the current exact ingredient counts"
        )
    food_ready = energy is not None and energy >= minimum_base_energy
    return {
        **water,
        "target_base_food_energy": minimum_base_energy,
        "observed_base_food_energy": energy,
        "observed_food_counts": counts,
        "food_ready_to_save": food_ready,
        "ready_to_save": water["ready_to_save"] and food_ready,
    }


class WaterHarvestMonitor:
    """Read the bag between bounded advances; leave accounting to settlement."""

    target_name = "Water"

    def __init__(self, player):
        self.player = player
        self.rt = player.rt
        self.pending = False

    @staticmethod
    def hit(hits, task):
        return hits.get(task, {}).get("score", 0) >= 0.9

    def bag_hits(self, path):
        return self.rt.matches(path, ["SandAuto@BagHeader", "SandAuto@BagButton"])

    def restore_pause(self):
        path, _, states = self.player.frame("water-bag-restore")
        hits = self.bag_hits(path)
        if self.hit(hits, "SandAuto@BagHeader"):
            if not self.hit(hits, "SandAuto@BagButton"):
                raise CheckpointError(
                    "Open bag has no verified toggle; inspection remains pending"
                )
            self.rt.task("SandPilot@ToggleBattleBag")
            path, _, states = self.player.frame("water-bag-closed")
            hits = self.bag_hits(path)
        if self.hit(hits, "SandAuto@BagHeader") or "SandAuto@Battle" not in states:
            raise CheckpointError(
                "Bag did not return to a verified battle; inspection remains pending"
            )
        self.player.pause(True)
        path, _, states = self.player.frame("water-bag-paused")
        if "SandAuto@Paused" not in states or "SandAuto@Battle" not in states:
            raise CheckpointError("Bag inspection did not restore a verified pause")
        self.pending = False
        return path

    def read_observation(self, path):
        return read_bag_water(self.rt, path)

    def goal(self, observation, pumps):
        return water_goal(observation, pumps)

    def check_additional_progress(self, observation, history):
        pass

    def inspect(self):
        if self.pending:
            raise CheckpointError(
                "Previous bag toggle is unresolved; do not toggle again"
            )
        if not self.player.in_battle or getattr(self.player, "raid_mode", False):
            raise CheckpointError(
                "Water inspection requires a gathering battle, not a raid"
            )
        self.player.pause(True)
        path, _, states = self.player.frame("water-bag-before")
        if "SandAuto@Paused" not in states or "SandAuto@Battle" not in states:
            raise CheckpointError("Bag inspection requires a confirmed paused battle")
        hits = self.bag_hits(path)
        if self.hit(hits, "SandAuto@BagHeader") or not self.hit(
            hits, "SandAuto@BagButton"
        ):
            raise CheckpointError(
                "Start bag inspection from the identified closed-bag control"
            )
        before = self.player.remaining(path)
        self.pending = True
        try:
            self.rt.task("SandPilot@ToggleBattleBag")
            path, _, _ = self.player.frame("water-bag-open")
            observation = self.read_observation(path)
        finally:
            restored = self.restore_pause()
        after = self.player.remaining(restored)
        if before != after:
            raise CheckpointError("Harvest clock changed during paused bag inspection")
        observation["remaining"] = after
        self.rt.log(getattr(self, "event_name", "water_haul_observed"), **observation)
        return observation

    def wait(self, pumps=2, *, maximum_game_seconds=180, remaining_floor=25):
        # Validate all policy inputs before the first control call.
        water_goal({"status": "current_operation_water", "water": 1}, pumps)
        if (
            type(maximum_game_seconds) is not int
            or not 1 <= maximum_game_seconds <= 180
            or type(remaining_floor) is not int
            or not 25 <= remaining_floor <= 240
        ):
            raise CheckpointError(
                "Water monitoring needs a bounded game-time budget and reserve"
            )
        start = previous = last_water = None
        history = {}
        for poll in range(61):
            observation = self.inspect()
            remaining = observation["remaining"]
            if remaining < 25:
                raise CheckpointError("Harvest exit reserve already exhausted")
            if start is None:
                start = remaining
            elif remaining >= previous:
                raise CheckpointError(
                    "Harvest clock did not decrease after the bounded advance"
                )
            previous = remaining
            self.check_additional_progress(observation, history)
            count = observation["water"]
            if count is not None:
                if last_water is not None and count < last_water:
                    raise CheckpointError(
                        "Current-operation water decreased; operation continuity is unknown"
                    )
                last_water = count
                goal = self.goal(observation, pumps)
                if goal["ready_to_save"]:
                    return {
                        **goal,
                        "observation": observation,
                        "polls": poll + 1,
                        "paused": True,
                        "elapsed_game_seconds": start - remaining,
                    }
            # Unknown is allowed to remain unknown during bounded harvesting. Never infer zero.
            elapsed = start - remaining
            if remaining <= remaining_floor or elapsed >= maximum_game_seconds:
                raise CheckpointError(
                    self.target_name
                    + " target not observed before the harvesting reserve/budget"
                )
            # advance() uses wall seconds. Preserve the reserve even at observed-game speed2x.
            seconds = min(
                5,
                (remaining - remaining_floor) / 2,
                (maximum_game_seconds - elapsed) / 2,
            )
            if seconds < 0.5:
                raise CheckpointError(
                    "No bounded harvesting interval remains before the reserve"
                )
            self.player.advance(seconds)
        raise CheckpointError(
            self.target_name + " target was not observed within the bounded poll limit"
        )


class HuntingHarvestMonitor(WaterHarvestMonitor):
    """Reuse paused bag inspection and bounded water polling for a joint food target."""

    event_name = "hunting_haul_observed"
    target_name = "Hunting food/water"

    def __init__(self, player, minimum_base_energy=80):
        if type(minimum_base_energy) is not int or not 1 <= minimum_base_energy <= 1000:
            raise CheckpointError(
                "Hunting monitor needs a bounded positive food target"
            )
        super().__init__(player)
        self.minimum_base_energy = minimum_base_energy

    def read_observation(self, path):
        observation = super().read_observation(path)
        observation["food"] = read_bag_food(self.rt, path)
        return observation

    def goal(self, observation, pumps):
        return hunting_goal(observation, pumps, self.minimum_base_energy)

    def check_additional_progress(self, observation, history):
        for key, value in (
            observation.get("food", {}).get("raw_food_counts", {}).items()
        ):
            if key in history and value < history[key]:
                raise CheckpointError(
                    "Current-operation food decreased; operation continuity is unknown"
                )
            history[key] = value

    def wait(self, pumps=1, *, maximum_game_seconds=180, remaining_floor=25):
        if type(pumps) is not int or pumps != 1:
            raise CheckpointError(
                "Hunting monitoring supports the source one-pump operation only"
            )
        return super().wait(
            pumps,
            maximum_game_seconds=maximum_game_seconds,
            remaining_floor=remaining_floor,
        )


def verify_water_settlement(goal, settlement):
    """The bag target never substitutes for actual delivered water rewards."""
    stage_id = goal.get("stage_id", "sandbox_1_56")
    expected_stage = WATER_STAGES.get(stage_id)
    if expected_stage is None or goal.get("stage", expected_stage) != expected_stage:
        raise CheckpointError("Water completion must identify a reviewed pump stage")
    observed = settlement.get("verified_counts", {}).get("water")
    if (
        type(observed) is not int
        or observed < goal["target_water"]
        or settlement.get("stage") != expected_stage
    ):
        raise CheckpointError(
            "Water completion requires the named stage and sufficient observed settlement water"
        )
    return {
        "status": "water_target_settled",
        "target_water": goal["target_water"],
        "bag_water": goal["observed_water"],
        "settled_water": observed,
        "inventory_updated": False,
        "image": settlement["image"],
    }
