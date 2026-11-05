"""Commit an owned planter draft once, then verify the count after leaving and reopening HQ."""

import copy
import hashlib
import re
import time
from pathlib import Path

from maa_sand_config import CheckpointError
from maa_sand_construction import observe_construction, read_hq_details
from maa_sand_days import ActJournal
from maa_sand_planter import read_planter_observation
from maa_sand_settlement import enlarged_count
from maa_sand_world import read_world


def saved_fraction(reads):
    if len(reads) != 1 or reads[0].get("score", 0) < 0.85:
        raise CheckpointError("Saved HQ planter count requires one confident fraction")
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", reads[0].get("text", ""))
    if (
        match is None
        or int(match[2]) not in (2, 4)
        or not 0 <= int(match[1]) <= int(match[2])
    ):
        raise CheckpointError("Saved HQ planter count is not a reviewed count/capacity")
    return int(match[1]), int(match[2])


def read_saved_planters(runtime, path):
    hits = runtime.matches(
        path, ["SandAuto@Headquarters", "SandAuto@HQDetails", "SandAuto@HQPlanterName"]
    )
    if any(
        hits.get(task, {}).get("score", 0) < 0.85
        for task in (
            "SandAuto@Headquarters",
            "SandAuto@HQDetails",
            "SandAuto@HQPlanterName",
        )
    ):
        raise CheckpointError(
            "Saved planter proof needs English HQ details and the exact construct row"
        )
    roi = [350, 175, 60, 37]
    reads = runtime.ocr(path, roi)
    prepared = None
    try:
        count, limit = saved_fraction(reads)
    except CheckpointError:
        prepared, large = enlarged_count(path, roi)
        reads = runtime.ocr(prepared, large)
        count, limit = saved_fraction(reads)
    calendar = read_hq_details(runtime, path)
    return {
        "image": str(path),
        "count": count,
        "limit": limit,
        "day": calendar["day"],
        "evidence": hits,
        "quantity_reads": reads,
        "prepared_image": str(prepared) if prepared else None,
        "calendar": calendar,
        "freshness_verified": False,
        "production_verified": False,
    }


def read_build_editor(runtime, path):
    tasks = ["SandAuto@HQBuildTitle", "SandAuto@HQBuildSave", "SandAuto@HQBuildBack"]
    hits = runtime.matches(path, tasks)
    if any(
        hits.get(task, {}).get("score", 0) < (0.85 if task.endswith("Title") else 0.95)
        for task in tasks
    ):
        raise CheckpointError(
            "Build editor requires English Headquarters and actual Save/Back controls"
        )
    return {
        "image": str(path),
        "editor_verified": True,
        "evidence": hits,
        "placement_verified": False,
        "saved_layout_verified": False,
        "production_verified": False,
    }


def validate_draft(stock, baseline, before, after):
    if (
        stock.get("status") != "ready_for_placement"
        or stock.get("verification", {}).get("world_return_verified") is not True
    ):
        raise CheckpointError(
            "Owned planter stock preparation and world return must be verified first"
        )
    owned = stock.get("recipe_after", {})
    world = stock.get("after", {})
    if (
        owned.get("recipe_verified") is not True
        or type(owned.get("stock")) is not int
        or owned["stock"] not in (1, 2)
        or owned.get("limit") != 4
        or world.get("hq") != 2
    ):
        raise CheckpointError(
            "Draft needs actual owned stock and reviewed HQ2 capacity"
        )
    if any(view.get("recipe_verified") is not True for view in (before, after)):
        raise CheckpointError(
            "Both draft observations require the exact English planter recipe"
        )
    for view in (before, after):
        if any(type(view.get(key)) is not int for key in ("stock", "placed", "limit")):
            raise CheckpointError("Draft counts must be observed integers")
    if (
        baseline["limit"] != 4
        or baseline["count"] != owned["placed"]
        or baseline["day"] != world["day"]
        or before["stock"] != owned["stock"]
        or before["placed"] != baseline["count"]
        or before["limit"] != 4
        or after["stock"] != before["stock"] - 1
        or after["placed"] != before["placed"] + 1
        or after["limit"] != 4
    ):
        raise CheckpointError(
            "Draft must consume one owned planter and add exactly one deployed construct"
        )
    budget = {name: world["resources"][name] for name in ("water", "wood")}
    if before.get("available") != budget or after.get("available") != budget:
        raise CheckpointError(
            "Draft placement cannot spend crafting materials or borrow another operation"
        )
    return {
        "before_count": baseline["count"],
        "target_count": after["placed"],
        "limit": 4,
        "day": world["day"],
    }


def unchanged_world(expected, actual):
    if not actual.get("image") or actual["image"] == expected.get("image"):
        raise CheckpointError("Layout commit needs a new world observation")
    if any(
        actual.get(key) != expected.get(key) for key in ("day", "acts_remaining", "hq")
    ):
        raise CheckpointError("Layout commit changed or obscured day, Acts or HQ")
    for key, value in expected["resources"].items():
        if value is not None and actual["resources"].get(key) != value:
            raise CheckpointError(
                "Layout commit changed observed resources; production is not inferred"
            )


class PlanterLayoutCommit:
    """Save half only: a calibrated placement actor must supply owned before/after captures."""

    def __init__(self, runtime, stock_journal, campaign_id):
        self.rt = runtime
        self.journal = ActJournal(stock_journal, campaign_id + ":planter-stock")

    def owned_frames(self, paths):
        output = Path(self.rt.output).resolve()
        records = []
        for path in paths:
            resolved = Path(path).resolve()
            if output not in resolved.parents or not resolved.is_file():
                raise CheckpointError(
                    "Draft frames must come from this active controller output directory"
                )
            records.append(
                {
                    "image": str(path),
                    "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
                }
            )
        if (
            len({row["image"] for row in records}) != 3
            or len({row["sha256"] for row in records}) != 3
        ):
            raise CheckpointError(
                "Draft proof needs distinct original baseline/before/after captures"
            )
        return records

    def observe(self, label):
        return observe_construction(
            self.rt,
            label,
            ("SandAuto@HQBuildTitle", "SandAuto@HQBuildSave", "SandAuto@HQBuildBack"),
        )

    def run(self, baseline_image, before_recipe_image, after_recipe_image):
        # Secure a recognized unexpected battle before spending time on saved-frame analysis.
        admission, _ = self.observe("layout-admission")
        read_build_editor(self.rt, admission)
        frames = self.owned_frames(
            (baseline_image, before_recipe_image, after_recipe_image)
        )
        with self.journal.locked() as journal:
            stock = journal.data["acts"].get("planter-stock", {})
            if stock.get("layout"):
                raise CheckpointError(
                    "Layout commit already pending or verified; never repeat Save"
                )
            baseline = read_saved_planters(self.rt, baseline_image)
            before = read_planter_observation(self.rt, before_recipe_image)
            after = read_planter_observation(self.rt, after_recipe_image)
            expected = validate_draft(stock, baseline, before, after)
            path, _ = self.observe("layout-owned-editor")
            editor = read_build_editor(self.rt, path)
            layout = {
                "status": "pending",
                "draft": expected,
                "frames": frames,
                "baseline": baseline,
                "before_recipe": before,
                "after_recipe": after,
                "editor": editor,
                "save_submitted": True,
                "production_verified": False,
                "placement_location_verified": False,
            }
            stock["layout"] = layout
            journal.save()
            try:
                self.rt.task("SandPilot@HQBuildSave")
                for _ in range(20):
                    path, hits = self.observe("layout-save-transition")
                    if all(
                        task in hits
                        for task in (
                            "SandAuto@HQBuildTitle",
                            "SandAuto@HQBuildSave",
                            "SandAuto@HQBuildBack",
                        )
                    ):
                        read_build_editor(self.rt, path)
                        if layout.get("editor_back_submitted"):
                            raise CheckpointError(
                                "Editor exit unresolved; never repeat Back or Save"
                            )
                        layout["editor_back_submitted"] = True
                        journal.save()
                        self.rt.task("SandPilot@HQBuildBack")
                    elif "SandAuto@HQDetails" in hits:
                        view = read_saved_planters(self.rt, path)
                        view["freshness_verified"] = True
                        if (view["count"], view["limit"], view["day"]) != (
                            expected["target_count"],
                            4,
                            expected["day"],
                        ):
                            raise CheckpointError(
                                "Saved HQ construct count/day disagrees with the owned draft"
                            )
                        if layout.get("reopen_submitted"):
                            if layout.get("reopened_back_submitted"):
                                raise CheckpointError("Reopened HQ exit unresolved")
                            layout.update(reopened=view, reopened_back_submitted=True)
                            journal.save()
                        else:
                            if layout.get("initial_hq_back_submitted"):
                                raise CheckpointError("Initial HQ exit unresolved")
                            layout.update(
                                first_details=view, initial_hq_back_submitted=True
                            )
                            journal.save()
                        self.rt.task("SandPilot@Back")
                    elif "SandAuto@World" in hits:
                        world = read_world(self.rt, path)
                        unchanged_world(stock["after"], world)
                        if layout.get("reopened"):
                            layout.update(
                                status="saved_count_verified",
                                after=world,
                                layout_reopen_verified=True,
                                inventory_updated=False,
                                day_advanced=False,
                                act_consumed=False,
                            )
                            stock["status"] = "layout_count_verified"
                            journal.save()
                            return copy.deepcopy(layout)
                        if layout.get("reopen_submitted"):
                            raise CheckpointError(
                                "HQ reopen unconfirmed; never repeat navigation"
                            )
                        layout.update(reopen_submitted=True, intermediate_world=world)
                        journal.save()
                        self.rt.task("SandPilot@Headquarters")
                    time.sleep(0.5)
                raise CheckpointError(
                    "Save transition unconfirmed; preserve the owned draft without repeating inputs"
                )
            except BaseException as exc:
                layout["error"] = str(exc)
                journal.save()
                try:
                    self.observe("layout-stopped")
                except Exception as checkpoint_error:  # noqa: BLE001 - preserve the original commit failure
                    self.rt.log("layout_stop_checkpoint", reason=str(checkpoint_error))
                raise
