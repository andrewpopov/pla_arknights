"""Prepare the guide's extra planter stock; placement, save and rice production are separate."""

import copy
import json
import re
import time
from pathlib import Path

from maa_sand_config import CheckpointError, default_pack
from maa_sand_construction import observe_construction, run_construction_cli
from maa_sand_days import ActJournal
from maa_sand_tools import ToolCrafter, count, read_hub_materials
from maa_sand_world import read_world

ITEM = "sandbox_1_building_1"
MATERIALS = {"water": 10, "wood": 30}


def load_planter(pack=None):
    data = json.loads(
        (
            (Path(pack) if pack else default_pack()) / "campaign/buildings.json"
        ).read_text(encoding="utf8")
    )
    recipe = data.get("items", {}).get(ITEM, {})
    if (
        data.get("schema_version") != 1
        or data.get("placement_is_separate") is not True
        or recipe.get("name") != "Planting Box Group"
        or recipe.get("trap_id") != "trap_456_xbfarmm"
        or recipe.get("materials") != MATERIALS
        or list(recipe["materials"]) != list(MATERIALS)
        or recipe.get("min_hq") != 2
        or recipe.get("output_ratio") != 1
        or recipe.get("reviewed_hq2_placement_cap") != 4
    ):
        raise CheckpointError(
            "Review the exact exported planter recipe and UI material order"
        )
    return recipe


def placed_fraction(read):
    match = re.fullmatch(
        r"\s*(\d{1,2})\s*/\s*MAX\s*(\d{1,2})\s*", read.get("text", ""), re.IGNORECASE
    )
    if (
        read.get("score", 0) < 0.85
        or match is None
        or int(match[2]) != 4
        or not 0 <= int(match[1]) <= 4
    ):
        raise CheckpointError(
            "Planter requires the observed deployed/MAX4 fraction; stock is separate"
        )
    return int(match[1]), int(match[2])


def read_planter_fields(runtime, path):
    """Native component replay helper; does not prove an English unlocked recipe."""
    hits = runtime.matches(
        path,
        [
            "SandAuto@ToolRecipeStock",
            "SandAuto@ToolCraftQuantity",
            "SandAuto@PlanterPlacedFraction",
        ],
    )
    placed, limit = placed_fraction(hits.get("SandAuto@PlanterPlacedFraction", {}))
    return {
        "image": str(path),
        "stock": count(hits, "SandAuto@ToolRecipeStock"),
        "quantity": count(hits, "SandAuto@ToolCraftQuantity"),
        "placed": placed,
        "limit": limit,
        "available": read_hub_materials(runtime, path, MATERIALS),
        "evidence": hits,
        "recipe_verified": False,
        "placement_verified": False,
        "production_verified": False,
    }


def read_planter_observation(runtime, path):
    hits = runtime.matches(path, ["SandAuto@PlanterRecipeScreen"])
    if hits.get("SandAuto@PlanterRecipeScreen", {}).get("score", 0) < 0.85:
        raise CheckpointError("Planter observation requires the exact English recipe")
    return {
        **read_planter_fields(runtime, path),
        "recipe_verified": True,
        "recipe_identity": hits,
    }


def review_planter(state):
    ranges = (
        ("day", 4, 6),
        ("acts_used", 0, 1),
        ("hq", 2, 2),
        ("wood", 0, 999999),
        ("water", 0, 999999),
        ("planter_stock", 0, 2),
        ("planter_placed", 0, 3),
    )
    for key, low, high in ranges:
        if type(state.get(key)) is not int or not low <= state[key] <= high:
            raise CheckpointError(
                "Planter preparation requires observed " + key + f" in {low}..{high}"
            )
    reserves = state.get("construction_reserves")
    if (
        not isinstance(reserves, dict)
        or set(reserves) != set(MATERIALS)
        or any(
            type(value) is not int or not 0 <= value <= 999999
            for value in reserves.values()
        )
    ):
        raise CheckpointError(
            "Declare explicit observed wood/water construction reserves"
        )
    blockers = []
    if state.get("snapshot_current") is not True or state.get("settled") is not True:
        blockers.append("Require a current settled observation")
    if state.get("threat") not in ("clear", "later"):
        blockers.append(
            "Resolve unknown or urgent raids before optional planter spending"
        )
    for key in ("campaign_id", "observation_id"):
        if not isinstance(state.get(key), str) or not state[key].strip():
            blockers.append("Require explicit " + key)
    missing = 1 if state["planter_stock"] == 0 else 0
    shortfall = {
        name: max(0, missing * cost + reserves[name] - state[name]) if missing else 0
        for name, cost in MATERIALS.items()
    }
    if any(shortfall.values()):
        blockers.append(
            "Defer optional planter: complete materials and protected reserves are not funded"
        )
    return {
        "activity": "prepare-one-extra-planter-stock",
        "guide_optional": True,
        "target_stock": 1,
        "expected_crafts": missing,
        "costs": dict(MATERIALS),
        "reserves": dict(reserves),
        "shortfall": shortfall,
        "blockers": blockers,
        "placement_required_afterwards": True,
        "production_verified": False,
        "autoplay_enabled": False,
        "game_connected": False,
        "inventory_updated": False,
    }


class PlanterCrafter(ToolCrafter):
    def __init__(self, runtime, pack=None):
        self.rt = runtime
        self.catalog = {ITEM: load_planter(pack)}
        self.pending = False
        self.expected_placed = None
        self.expected_materials = None
        self.select_recipe(ITEM)

    def select_recipe(self, item_id):
        if self.pending or item_id != ITEM:
            raise CheckpointError(
                "Planter preparation cannot change recipe or repeat an uncertain craft"
            )
        self.kind = "Planter"
        self.recipe = self.catalog[ITEM]

    def recipe_frame(self):
        path, stock, available = super().recipe_frame()
        field = self.rt.matches(path, ["SandAuto@PlanterPlacedFraction"]).get(
            "SandAuto@PlanterPlacedFraction", {}
        )
        placed, limit = placed_fraction(field)
        if placed >= limit:
            raise CheckpointError(
                "Planter placement cap is already met; skip this optional craft"
            )
        if self.expected_placed is not None and placed != self.expected_placed:
            raise CheckpointError("Actual deployed planter count changed; do not craft")
        if (
            not self.pending
            and self.expected_materials is not None
            and available != self.expected_materials
        ):
            raise CheckpointError(
                "Actual planter recipe materials differ from the observed world budget"
            )
        self.last_snapshot = {
            "image": str(path),
            "stock": stock,
            "placed": placed,
            "limit": limit,
            "available": available,
            "placed_evidence": field,
            "recipe_verified": True,
        }
        return path, stock, available

    def stock_frame(self):
        # Reuse the full recipe observation so deployed count cannot be confused with new stock.
        path, stock, _available = self.recipe_frame()
        return path, stock

    def prepare_one(self, state):
        if state["hq"] != 2:
            raise CheckpointError("Reviewed planter preparation requires HQ2")
        self.expected_placed = state["planter_placed"]
        self.expected_materials = {name: state[name] for name in MATERIALS}
        return self._prepare(
            1, state["construction_reserves"], expected_stock=state["planter_stock"]
        )


def verify_world_stock(state, before, after, crafted):
    if type(crafted) is not int or crafted not in (0, 1):
        raise CheckpointError("Planter preparation owns at most one new stock item")
    if not after.get("image") or after["image"] == before["image"]:
        raise CheckpointError("Planter preparation needs a new world return")
    if (after.get("hq"), after.get("day"), after.get("acts_remaining")) != (
        2,
        state["day"],
        2 - state["acts_used"],
    ):
        raise CheckpointError(
            "Planter stock preparation must preserve HQ, day and Acts"
        )
    for name, old in before["resources"].items():
        new = after["resources"].get(name)
        if name in MATERIALS:
            if (
                type(old) is not int
                or type(new) is not int
                or new != old - crafted * MATERIALS[name]
            ):
                raise CheckpointError(
                    "Planter craft world debit differs from actual confirmed output"
                )
        elif old is not None and new != old:
            raise CheckpointError(
                "Unrelated observed resources changed during planter preparation"
            )
    return {
        "world_return_verified": True,
        "stock_prepared": True,
        "placement_verified": False,
        "production_verified": False,
        "act_consumed": False,
        "day_advanced": False,
        "inventory_updated": False,
    }


class PlanterPreparation:
    def __init__(self, runtime, journal_path, campaign_id):
        self.rt = runtime
        self.journal = ActJournal(journal_path, campaign_id + ":planter-stock")

    def observe(self, label):
        return observe_construction(
            self.rt, label, ("SandAuto@WorkbenchScreen", "SandAuto@PlanterRecipeScreen")
        )

    def run(self, state):
        review = review_planter(state)
        if review["blockers"]:
            raise CheckpointError("; ".join(review["blockers"]))
        if self.journal.campaign_id != state["campaign_id"] + ":planter-stock":
            raise CheckpointError("Planter journal belongs to another campaign")
        with self.journal.locked() as journal:
            if journal.data["acts"]:
                raise CheckpointError(
                    "Planter preparation already pending or owned; never repeat it"
                )
            path, hits = self.observe("planter-world-before")
            if "SandAuto@World" not in hits:
                raise CheckpointError(
                    "Start planter preparation from the actual world map"
                )
            before = read_world(self.rt, path)
            if (before.get("hq"), before.get("day"), before.get("acts_remaining")) != (
                2,
                state["day"],
                2 - state["acts_used"],
            ):
                raise CheckpointError(
                    "Fresh planter world observation disagrees with HQ/day/Acts"
                )
            if any(before["resources"].get(name) != state[name] for name in MATERIALS):
                raise CheckpointError(
                    "Fresh world materials disagree with planter budget"
                )
            entry = {
                "status": "pending",
                "before": before,
                "observation_id": state["observation_id"],
                "submitted": False,
                "placement_verified": False,
                "production_verified": False,
                "inventory_updated": False,
            }
            journal.data["acts"]["planter-stock"] = entry
            journal.save()
            try:
                self.rt.task("SandPilot@Workbench")
                path, hits = self.observe("planter-workbench")
                if "SandAuto@PlanterRecipeScreen" not in hits:
                    if "SandAuto@WorkbenchScreen" not in hits:
                        raise CheckpointError(
                            "Workbench did not open; preserve checkpoint"
                        )
                    self.rt.task("SandPilot@HeadquartersConstructs")
                crafter = PlanterCrafter(self.rt, self.rt.pack)

                def before_submit(intent):
                    if entry["submitted"]:
                        raise CheckpointError(
                            "Planter craft already submitted; never repeat"
                        )
                    entry.update(
                        submitted=True,
                        intent=intent,
                        recipe_before=copy.deepcopy(crafter.last_snapshot),
                    )
                    journal.save()

                crafter.before_submit = before_submit
                result = crafter.prepare_one(state)
                if result["stock"] < 1 or result["crafted"] not in (0, 1):
                    raise CheckpointError("Planter target stock not observed")
                entry.update(
                    craft=result, recipe_after=copy.deepcopy(crafter.last_snapshot)
                )
                journal.save()
                crafter.close_recipe()
                path, hits = self.observe("planter-workbench-return")
                if (
                    "SandAuto@WorkbenchScreen" not in hits
                    or "SandAuto@PlanterRecipeScreen" in hits
                ):
                    raise CheckpointError("Recipe did not return to workbench")
                if (
                    self.rt.matches(path, ["SandAuto@WorkbenchBack"])
                    .get("SandAuto@WorkbenchBack", {})
                    .get("score", 0)
                    < 0.85
                ):
                    raise CheckpointError("Workbench return arrow is unverified")
                entry["return_submitted"] = True
                journal.save()
                self.rt.task("SandPilot@WorkbenchBack")
                for _ in range(8):
                    path, hits = self.observe("planter-world-after")
                    if "SandAuto@World" in hits:
                        after = read_world(self.rt, path)
                        facts = verify_world_stock(
                            state, before, after, result["crafted"]
                        )
                        entry.update(
                            status="ready_for_placement",
                            after=after,
                            verification=facts,
                        )
                        journal.save()
                        return copy.deepcopy(entry)
                    time.sleep(0.5)
                raise CheckpointError(
                    "Planter workbench return unconfirmed; do not repeat craft or back"
                )
            except BaseException as exc:
                entry["error"] = str(exc)
                journal.save()
                try:
                    self.observe("planter-stopped")
                except Exception as checkpoint_error:  # noqa: BLE001 - preserve the original crafting failure
                    self.rt.log("planter_stop_checkpoint", reason=str(checkpoint_error))
                raise


def run_planter_cli(args, parser, runtime_factory):
    return run_construction_cli(
        args,
        parser,
        runtime_factory,
        review_planter,
        PlanterPreparation,
        "--prepare-planter",
        ".planter",
        "planter-stock",
    )
