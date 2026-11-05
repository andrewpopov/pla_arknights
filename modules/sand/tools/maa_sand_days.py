"""Bounded Day 1–6 execution using existing helpers and a durable Act journal."""

import argparse
import copy
import json
import os
from contextlib import contextmanager
from pathlib import Path

from maa_sand_campaign import advise, load_campaign
from maa_sand_config import (
    REVIEWED_FIELD_TOOLS,
    CheckpointError,
    default_pack,
    require_executable,
)
from maa_sand_world import reconcile_world


def load_days(pack=None):
    pack = Path(pack) if pack else default_pack()
    plan = load_campaign(pack)
    data = json.loads((pack / "campaign/day-execution.json").read_text(encoding="utf8"))
    keys = [f"{step['day']}.{step['act']}" for step in plan["steps"]]
    if data.get("schema_version") != 1 or list(data.get("acts", {})) != keys:
        raise CheckpointError(
            "One ordered execution contract is required for every campaign Act"
        )
    for contract in data["acts"].values():
        food_target = contract.get("minimum_raw_food_base_energy", 80)
        if type(food_target) is not int or not 1 <= food_target <= 1000:
            raise CheckpointError("Invalid minimum raw-food base-energy target")
        if any(
            type(v) is not int or v < 1 for v in contract["minimum_rewards"].values()
        ):
            raise CheckpointError("Invalid minimum observed reward")
        if any(
            not isinstance(flag, str) or not flag for flag in contract["required_flags"]
        ):
            raise CheckpointError("Invalid outcome flag")
    return plan, data


def review_act(state, pack=None):
    plan, days = load_days(pack)
    advice = advise(state, plan, execution=True)
    if advice["next"] is None:
        raise CheckpointError(
            "Both Acts consumed: review construction and day end separately"
        )
    key = f"{state['day']}.{state['acts_used'] + 1}"
    contract = copy.deepcopy(days["acts"][key])
    if advice["next"]["objective"] != "raid" and state["squad_size"] > contract.get(
        "maximum_squad", 12
    ):
        advice["blockers"].append("Observed squad exceeds this guide Act squad budget")
    if advice["next"]["objective"] == "raid":
        contract.update(
            minimum_rewards={},
            required_flags=["raid_victory_verified", "lives_preserved_verified"],
        )
    return advice, contract


def verify_world(state, world):
    if (
        not isinstance(world, dict)
        or not world.get("image")
        or (world.get("day"), world.get("acts_remaining"), world.get("hq"))
        != (state["day"], 2 - state["acts_used"], state["hq"])
    ):
        raise CheckpointError("Fresh world observation disagrees with campaign state")
    for name in ("wood", "water", "stone"):
        if name in state and world.get("resources", {}).get(name) != state[name]:
            raise CheckpointError(f"World {name} differs from campaign state")


class ActJournal:
    """One file per campaign. An uncertain action prevents another paid action."""

    def __init__(self, path, campaign_id):
        self.path = Path(path)
        if not isinstance(campaign_id, str) or not campaign_id.strip():
            raise CheckpointError("An explicit campaign ID is required")
        self.campaign_id = campaign_id

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_name(self.path.name + ".lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise CheckpointError(
                "Campaign journal locked: inspect previous operation before retrying"
            ) from exc
        try:
            os.close(fd)
            if self.path.exists():
                self.data = json.loads(self.path.read_text(encoding="utf8"))
                if (
                    self.data.get("schema_version") != 1
                    or self.data.get("campaign_id") != self.campaign_id
                ):
                    raise CheckpointError(
                        "Journal belongs to another campaign or schema"
                    )
            else:
                self.data = {
                    "schema_version": 1,
                    "campaign_id": self.campaign_id,
                    "acts": {},
                }
            yield self
        finally:
            lock.unlink()

    def save(self):
        temporary = self.path.with_name(self.path.name + ".tmp")
        with temporary.open("w", encoding="utf8") as stream:
            json.dump(self.data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)


class DayRunner:
    """Run one Act or two freshly observed Acts; never advance the game day."""

    def __init__(self, backend, journal, pack=None):
        self.backend, self.journal, self.pack = backend, journal, pack

    def run_act(self, state):
        advice, contract = review_act(state, self.pack)
        if advice["blockers"]:
            raise CheckpointError("; ".join(advice["blockers"]))
        identity = state.get("observation_id")
        if not isinstance(identity, str) or not identity:
            raise CheckpointError("Each Act requires a distinct current observation ID")
        if state.get("campaign_id") != self.journal.campaign_id:
            raise CheckpointError("Observation belongs to another campaign")
        step = advice["next"]
        key = f"{step['day']}.{step['act']}"
        with self.journal.locked() as journal:
            for previous in journal.data["acts"].values():
                if previous["status"] != "verified":
                    raise CheckpointError(
                        "Prior Act pending or needs review; do not repeat or skip it"
                    )
                if previous["observation_id"] == identity:
                    raise CheckpointError("Observation already used for a paid Act")
            if key in journal.data["acts"]:
                raise CheckpointError("This campaign Act was already executed")
            self.backend.preflight(
                step, state, contract
            )  # Read-only, before journal submission.
            before = self.backend.observe_world()
            verify_world(state, before)
            entry = {
                "status": "pending",
                "observation_id": identity,
                "step": step,
                "contract": contract,
                "before": before,
                "inventory_updated": False,
            }
            journal.data["acts"][key] = entry
            journal.save()  # Durable before the first native input, including navigation.
            try:
                outcome = self.backend.execute(step, state, contract)
                entry["outcome"] = outcome
                after = outcome["world"]
                if not after.get("image") or after["image"] == before["image"]:
                    raise CheckpointError("A new world-return observation is required")
                facts = reconcile_world(before, after, outcome.get("rewards", {}))
                if facts["observed_act_difference"] != 1:
                    raise CheckpointError("Exactly one consumed Act must be observed")
                if after.get("day") is None and after.get("acts_remaining") != 0:
                    raise CheckpointError(
                        "Missing day supported only at the zero-Act day-end HUD"
                    )
                issues = []
                for name, minimum in contract["minimum_rewards"].items():
                    value = outcome.get("rewards", {}).get(name)
                    if type(value) is not int or value < minimum:
                        issues.append(
                            f"Observed {name} reward must be at least {minimum}; got {value}"
                        )
                if contract["minimum_rewards"] and not outcome.get("settlement_image"):
                    issues.append("Named expedition settlement evidence missing")
                for flag in contract["required_flags"]:
                    if outcome.get(flag) is not True:
                        issues.append(f"Missing verified outcome: {flag}")
                if any(
                    v is False for v in facts["reward_matches_world_delta"].values()
                ):
                    issues.append(
                        "Settlement differs from observed world inventory change"
                    )
                entry.update(
                    status="needs_review" if issues else "verified",
                    outcome=outcome,
                    reconciliation=facts,
                    issues=issues,
                    next="review_day_end" if step["act"] == 2 else "observe_next_act",
                )
                journal.save()
                return copy.deepcopy(entry)
            except BaseException as exc:
                entry.update(error=str(exc), status="pending")
                try:
                    journal.save()
                finally:
                    self.backend.secure_checkpoint()
                raise

    def run_day(self, observe):
        results, initial_day = [], None
        for _ in range(2):
            state = observe()
            initial_day = state["day"] if initial_day is None else initial_day
            if state["day"] != initial_day:
                raise CheckpointError("Day changed: stop for day-end review")
            result = self.run_act(state)
            results.append(result)
            if result["status"] != "verified" or result["next"] == "review_day_end":
                break
        _, days = load_days(self.pack)
        return {
            "day_end_review": days["day_end"][str(initial_day)],
            "status": results[-1]["next"]
            if results[-1]["status"] == "verified"
            else "needs_review",
            "acts": results,
            "day_advanced": False,
            "inventory_updated": False,
        }


class NativeDayBackend:
    """Share the player's native runtime, encounter executor and Liaison executor."""

    def __init__(
        self,
        player,
        *,
        allow_experimental=False,
        verify_equipment=None,
        campaign_journal=None,
    ):
        self.player = player
        self.allow_experimental = allow_experimental
        self.verify_equipment = verify_equipment
        self.campaign_journal = (
            Path(campaign_journal) if campaign_journal is not None else None
        )

    def observe_world(self):
        from maa_sand_world import read_world

        path, _ = self.player.rt.capture("campaign-act-world")
        return read_world(self.player.rt, path)

    def preflight(self, step, state, contract):
        if not self.allow_experimental or self.player.in_battle:
            raise CheckpointError(
                "Begin bounded experimental campaign validation outside battle"
            )
        if step["objective"] == "raid":
            if (
                self.player.profile.get("kind") != "raid-combat"
                or self.campaign_journal is None
            ):
                raise CheckpointError(
                    "Raid Act interception requires an explicit raid profile and campaign journal"
                )
            from maa_sand_raid_launch import review_raid_state

            review_raid_state(state, self.player.profile)
            return
        if step["objective"] in ("encounter", "talk"):
            if step["objective"] == "talk":
                from maa_sand_visit import review_visit

                review_visit(state, self.player.rt.pack)
            return
        profile = self.player.profile
        require_executable(profile, self.allow_experimental)
        if (
            profile.get("stage_id", "sandbox_1_01") != step["stage_id"]
            or profile["stage"] != step["stage"]
            or profile["id"] == "shrubbery-development"
        ):
            raise CheckpointError(
                "Bind a calibrated guide route for this exact campaign map"
            )
        if step["objective"] == "water_hunt":
            target = profile["steps"][-2] if len(profile.get("steps", [])) >= 2 else {}
            if (
                target.get("action") != "wait_hunting"
                or type(target.get("minimum_base_energy")) is not int
                or target["minimum_base_energy"]
                < contract.get("minimum_raw_food_base_energy", 80)
            ):
                raise CheckpointError(
                    "Hunting Act requires a joint food/water monitor meeting the campaign food target"
                )
        if set(state["squad"]) != set(profile["required_squad"]):
            raise CheckpointError("Observed squad must match the bound route roster")
        tools = {}
        for action in profile["steps"]:
            if action["action"] == "deploy_tool":
                name = REVIEWED_FIELD_TOOLS[action["item_id"]][0]
                tools[name] = tools.get(name, 0) + 1
        if tools != step["required_tools"]:
            raise CheckpointError("Route tool deployments must match this Act exactly")
        if tools and self.verify_equipment is None:
            raise CheckpointError(
                "Tool Acts need actual equipped-tool verification before launch"
            )

    def before_launch(self, path, state, step):
        from maa_sand_squad import verify_launch_squad
        from maa_sand_visit import read_trip_energy

        if len(state["squad"]) != state["squad_size"]:
            raise CheckpointError("Campaign squad names and headcount disagree")
        squad = verify_launch_squad(self.player, path, state["squad"])
        self.player.rt.log("campaign_launch_squad_verified", proof=squad)
        hits = self.player.rt.matches(path, ["SandAuto@FormationTripEnergy"])
        energy = read_trip_energy(
            self.player.rt, path, hits.get("SandAuto@FormationTripEnergy", {})
        )
        expected = 2 if state["squad_size"] <= 6 else 3
        if (energy["cost"], energy["stock"], energy["funded"]) != (
            expected,
            state["drinks"],
            True,
        ):
            raise CheckpointError(
                "Actual formation drink cost/stock differs from campaign budget"
            )
        tools = None
        if step["required_tools"]:
            proof = self.verify_equipment(path, step["required_tools"])
            if (
                not isinstance(proof, dict)
                or proof.get("verified") is not True
                or proof.get("image") != str(path)
            ):
                raise CheckpointError(
                    "Equipped tools not verified on actual launch frame"
                )
            tools = proof
        return {
            "image": str(path),
            "squad": squad,
            "energy": energy,
            "tools": tools,
            "launch_submitted": False,
        }

    def execute(self, step, state, contract):
        if step["objective"] == "raid":
            from maa_sand_raid_launch import RaidActWorkflow

            if self.campaign_journal is None:
                raise CheckpointError("Raid Act requires a persistent campaign journal")
            suffix = f".raid-{state['day']}-{state['acts_used'] + 1}"
            journal = self.campaign_journal.with_name(
                self.campaign_journal.name + suffix
            )
            run_id = f"{state['campaign_id']}:{state['day']}.{state['acts_used'] + 1}"
            return RaidActWorkflow(
                self.player, self.player.profile, journal, run_id
            ).run(state)
        if step["objective"] == "encounter":
            report = self.player.resolve_campaign_encounter(state)
            return {**report, "world": report["after"]}
        if step["objective"] == "talk":
            return self.player.visit_campaign_liaison(state)
        old_hook = getattr(self.player, "before_launch", None)
        old_no_brew = getattr(self.player, "campaign_no_brew", False)
        old_state = getattr(self.player, "campaign_state", None)
        self.player.campaign_state = state
        self.player.before_launch = lambda path: self.before_launch(path, state, step)
        self.player.campaign_no_brew = True
        try:
            self.player.play()
        finally:
            self.player.before_launch = old_hook
            self.player.campaign_no_brew = old_no_brew
            self.player.campaign_state = old_state
        settlement = self.player.settlement
        report = {
            "world": self.player.world_observation,
            "rewards": settlement["verified_counts"],
            "settlement_image": settlement["image"],
            "inventory_updated": False,
        }
        if step["objective"] == "water_hunt":
            from maa_sand_food import verify_hunting_food

            food = verify_hunting_food(
                settlement,
                contract.get("minimum_raw_food_base_energy", 80),
                expected_stage=step["stage"],
            )
            report.update(food_reward_verified=food["food_reward_verified"], food=food)
        return report

    def secure_checkpoint(self):
        try:
            _, _, states = self.player.frame("campaign-stopped")
            if "SandAuto@Battle" in states:
                self.player.pause(True)
        except Exception as exc:  # noqa: BLE001 - preserve original failure and log uncertainty
            self.player.rt.log("campaign_pause_not_confirmed", reason=str(exc))


def build_day6_water_route(calibration):
    """Compile the source routine against stage-bound, independently reviewed camera slots."""
    if calibration.get("stage_id") != "sandbox_1_56":
        raise CheckpointError(
            "Day6 water calibration must identify Straight Into the Abyss"
        )
    for camera in ("normal_points", "side_points"):
        if set(calibration.get(camera, {})) != {"pump1", "pump2"}:
            raise CheckpointError(
                "Both camera poses need distinct pump1 and pump2 slots"
            )
        if calibration[camera]["pump1"] == calibration[camera]["pump2"]:
            raise CheckpointError("Pumps require separate water tiles")
    if not calibration.get("anchor_manifest") or not calibration.get(
        "water_tile_evidence"
    ):
        raise CheckpointError(
            "Pinned stage anchors and reviewed water-tile evidence are required"
        )
    directions = calibration.get("directions", {})
    if set(directions) != {"pump1", "pump2"} or any(
        direction not in ("Left", "Right", "Up", "Down")
        for direction in directions.values()
    ):
        raise CheckpointError("Each pump needs an explicitly reviewed facing")
    return {
        "schema_version": 1,
        "id": "day6-water",
        "theme": "Tales",
        "stage": "Straight Into the Abyss",
        "stage_id": "sandbox_1_56",
        "autoplay_enabled": False,
        "validation_status": "Compiled source routine; live validation pending",
        "coordinate_system": "registered-1280x720",
        "required_squad": [],
        "squad_mode": "empty-pumps",
        "anchor_manifest": calibration["anchor_manifest"],
        "anchors": calibration.get("anchors", {"idle": "idle.png", "side": "side.png"}),
        "normal_points": calibration["normal_points"],
        "side_points": calibration["side_points"],
        "water_tile_evidence": calibration["water_tile_evidence"],
        "steps": [
            {"action": "wait_dp", "minimum": 5, "remaining_floor": 180},
            {
                "action": "deploy_tool",
                "item_id": "sandbox_1_tactical_15",
                "slot": "pump1",
                "direction": directions["pump1"],
                "maximum": 2,
            },
            {"action": "wait_dp", "minimum": 5, "remaining_floor": 160},
            {
                "action": "deploy_tool",
                "item_id": "sandbox_1_tactical_15",
                "slot": "pump2",
                "direction": directions["pump2"],
                "maximum": 2,
            },
            {
                "action": "wait_water",
                "pumps": 2,
                "maximum_game_seconds": 180,
                "remaining_floor": 25,
            },
            {"action": "finish"},
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Review a Day 1–6 Act without connecting to the game"
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--state", type=Path)
    inputs.add_argument(
        "--water-calibration",
        type=Path,
        help="Compile the Day6 routine against reviewed camera slots",
    )
    parser.add_argument(
        "--output", type=Path, help="Destination for a compiled experimental route"
    )
    parser.add_argument("--pack", type=Path, default=default_pack())
    args = parser.parse_args()
    if args.water_calibration:
        if args.output is None:
            parser.error("--water-calibration requires --output")
        route = build_day6_water_route(
            json.loads(args.water_calibration.read_text(encoding="utf-8-sig"))
        )
        args.output.write_text(json.dumps(route, indent=2) + chr(10), encoding="utf8")
        print(
            json.dumps(
                {
                    "route": str(args.output),
                    "autoplay_enabled": False,
                    "game_connected": False,
                }
            )
        )
        return
    if args.output is not None:
        parser.error("--output requires --water-calibration")
    advice, contract = review_act(
        json.loads(args.state.read_text(encoding="utf-8-sig")), args.pack
    )
    print(
        json.dumps(
            {"advice": advice, "execution_contract": contract, "game_connected": False},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
