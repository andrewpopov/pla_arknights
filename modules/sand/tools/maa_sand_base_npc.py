"""Bounded first HQ-upgrade NPC dialogue; initiation and persistent save remain separate."""

import copy
import hashlib
import json
import re
import time
from pathlib import Path

from maa_sand_battle import guard_unidentified_battle
from maa_sand_config import CheckpointError, default_pack
from maa_sand_construction import read_hq_details
from maa_sand_days import ActJournal
from maa_sand_dialogue import observe_step
from maa_sand_settlement import enlarged_count
from maa_sand_world import read_world

BODY = [180, 555, 1010, 100]
SPEAKER = [180, 500, 650, 55]
CAMP_TASKS = ["SandAuto@CampExit", "SandAuto@CampBag", "SandAuto@CampTent"]


def camp_identified(hits):
    return all(hits.get(task, {}).get("score", 0) >= 0.95 for task in CAMP_TASKS)


def read_stone_gift(runtime, path):
    hit = runtime.matches(path, ["SandAuto@BaseNpcStone"]).get(
        "SandAuto@BaseNpcStone", {}
    )
    rect = hit.get("rect", [])
    if (
        hit.get("score", 0) < 0.95
        or len(rect) != 4
        or any(type(v) is not int for v in rect)
        or rect[2:] != [94, 63]
        or not (535 <= rect[0] <= 656 and 290 <= rect[1] <= 367)
    ):
        raise CheckpointError("NPC gift requires the reviewed stone icon and position")
    roi = [rect[0] + 68, rect[1] + 64, 45, 30]
    reads = runtime.ocr(path, roi)
    prepared = None

    def exact_five(rows):
        return (
            len(rows) == 1
            and rows[0].get("score", 0) >= 0.85
            and re.fullmatch(r"\s*5\s*", rows[0].get("text", "")) is not None
        )

    if not exact_five(reads):
        prepared, large = enlarged_count(path, roi)
        reads = runtime.ocr(prepared, large)
    if not exact_five(reads):
        raise CheckpointError("NPC gift requires exactly five observed stone")
    return {
        "image": str(path),
        "item_id": "sandbox_1_stone",
        "quantity": 5,
        "icon": hit,
        "quantity_reads": reads,
        "prepared_image": str(prepared) if prepared else None,
        "inventory_updated": False,
        "scene_verified": False,
    }


def verify_npc_world(before, after, calendar_day):
    world = before["world"]
    day = before["calendar"]["day"]
    if (
        not after.get("image")
        or after["image"] == world["image"]
        or after.get("hq") != 2
        or after.get("acts_remaining") != world["acts_remaining"]
        or (
            after.get("day") != day
            and not (
                after.get("day") is None
                and after.get("acts_remaining") == 0
                and calendar_day == day
            )
        )
    ):
        raise CheckpointError(
            "NPC world return must preserve the observed day, Acts and HQ2"
        )
    for resource, old in world["resources"].items():
        if old is not None and after.get("resources", {}).get(resource) != old + (
            5 if resource == "stone" else 0
        ):
            raise CheckpointError(
                "NPC world return requires exactly stone+5 and no unrelated observed resource change"
            )
    return {
        "world_return_verified": True,
        "observed_stone_delta": 5,
        "act_consumed": False,
        "day_advanced": False,
        "inventory_updated": False,
        "quest_save_verified": False,
        "route_unlock_verified": False,
        "npc_withdrawal_verified": False,
    }


class BaseNpcDialogue:
    """Start only at the exact first English line. Never click an uncalibrated NPC."""

    def __init__(self, runtime, journal, campaign_id, pack=None):
        self.rt = runtime
        self.journal = ActJournal(journal, campaign_id + ":base-npc-first-upgrade")
        pack = Path(pack) if pack else default_pack()
        self.plan = json.loads(
            (pack / "guides/base-npc-first-upgrade.json").read_text(encoding="utf8")
        )
        if (
            self.plan.get("schema_version") != 1
            or self.plan.get("autoplay_enabled") is not False
            or self.plan.get("dialogue_id") != "dialog_sandbox_1_guide_trmedic1"
            or len(self.plan.get("steps", [])) != 5
            or [step.get("kind") for step in self.plan["steps"]]
            != ["line", "line", "line", "choice", "line"]
            or self.plan.get("reward", {}).get("quantity") != 5
        ):
            raise CheckpointError("Unreviewed base NPC sequence")

    def observe_step(self, path, step):
        return observe_step(self.rt, path, step, body=BODY, speaker=SPEAKER)

    def frame(self):
        path, _ = self.rt.capture("base-npc-dialogue")
        hits = self.rt.matches(
            path,
            [
                "SandAuto@DialogueLog",
                "SandAuto@Battle",
                "SandAuto@RaidBattle",
                "SandAuto@Paused",
                "BattleOfficiallyBegin",
                *CAMP_TASKS,
            ],
        )
        guard_unidentified_battle(self.rt, path, hits)
        if "SandAuto@DialogueLog" not in hits:
            if (
                camp_identified(hits)
                or "SandAuto@Battle" in hits
                or "SandAuto@RaidBattle" in hits
            ):
                self.secure_return(path, hits)
            raise CheckpointError(
                "Base NPC dialogue disappeared; preserve the checkpoint"
            )
        return path

    def secure_return(self, path=None, hits=None):
        return secure_camp_return(self.rt, path, hits)

    def bind_before(self, world_image, calendar_image):
        output = Path(self.rt.output).resolve()
        frames = []
        for image in (world_image, calendar_image):
            path = Path(image).resolve()
            if output not in path.parents or not path.is_file():
                raise CheckpointError(
                    "NPC baseline requires original captures in this active runtime output"
                )
            frames.append(
                {
                    "image": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        if len({frame["sha256"] for frame in frames}) != 2:
            raise CheckpointError(
                "NPC baseline needs distinct world and HQ calendar captures"
            )
        world = read_world(self.rt, world_image)
        calendar = read_hq_details(self.rt, calendar_image)
        if (
            type(calendar.get("day")) is not int
            or not 3 <= calendar["day"] <= 6
            or world.get("hq") != 2
            or type(world.get("acts_remaining")) is not int
            or not 0 <= world["acts_remaining"] <= 2
            or type(world.get("resources", {}).get("stone")) is not int
            or (
                world.get("day") != calendar["day"]
                and not (world.get("day") is None and world["acts_remaining"] == 0)
            )
        ):
            raise CheckpointError(
                "NPC baseline requires HQ2, known stone/Acts and a matching Day3–6 HQ calendar"
            )
        return {"world": world, "calendar": calendar, "frames": frames}

    def return_world(self):
        with self.journal.locked() as journal:
            entry = journal.data["acts"].get("base-npc", {})
            if entry.get("status") not in (
                "dialogue_observed_paused",
                "world_return_verified",
            ) or not entry.get("before"):
                raise CheckpointError(
                    "NPC return requires the owned completed dialogue and its pre-input baseline"
                )
            if (
                entry.get("gift", {}).get("scene_verified") is not True
                or entry["gift"].get("quantity") != 5
            ):
                raise CheckpointError(
                    "NPC return requires the identified five-stone gift"
                )
            if entry.get("return", {}).get("status") == "verified":
                return copy.deepcopy(entry["return"])
            operation = entry.get("return")
            submit_exit = operation is None
            if submit_exit:
                self.secure_return()
                operation = {
                    "status": "pending",
                    "exit_submitted": True,
                    "inventory_updated": False,
                }
                entry["return"] = operation
                journal.save()
                # Reuse the native exit/confirmation chain, bounded to one of each input.
            try:
                if submit_exit:
                    self.rt.task("SandPilot@NpcLeaveCamp")
                for _ in range(24):
                    path, _ = self.rt.capture("base-npc-world-return")
                    hits = self.rt.matches(
                        path,
                        [
                            "SandAuto@World",
                            "SandAuto@HQDetails",
                            "SandAuto@DialogueLog",
                            "SandAuto@Battle",
                            "SandAuto@RaidBattle",
                            "SandAuto@Paused",
                            "BattleOfficiallyBegin",
                            *CAMP_TASKS,
                        ],
                    )
                    if any(
                        key in hits
                        for key in ("SandAuto@Battle", "SandAuto@RaidBattle")
                    ) or camp_identified(hits):
                        self.secure_return(path, hits)
                        raise CheckpointError(
                            "NPC exit unresolved; never repeat the exit chain"
                        )
                    if "SandAuto@DialogueLog" in hits:
                        raise CheckpointError(
                            "Unexpected dialogue during camp exit; no further input"
                        )
                    if "SandAuto@World" in hits:
                        after = read_world(self.rt, path)
                        if (
                            after.get("day") is None
                            and after.get("acts_remaining") == 0
                            and not operation.get("calendar_after")
                        ):
                            if operation.get("hq_open_submitted"):
                                raise CheckpointError(
                                    "NPC post-return HQ calendar navigation unresolved"
                                )
                            operation["hq_open_submitted"] = True
                            journal.save()
                            self.rt.task("SandPilot@Headquarters")
                        else:
                            calendar = operation.get("calendar_after", {}).get("day")
                            facts = verify_npc_world(entry["before"], after, calendar)
                            operation.update(
                                status="verified", after=after, verification=facts
                            )
                            entry["status"] = "world_return_verified"
                            journal.save()
                            return copy.deepcopy(operation)
                    elif "SandAuto@HQDetails" in hits and operation.get(
                        "hq_open_submitted"
                    ):
                        if operation.get("hq_back_submitted"):
                            raise CheckpointError("NPC post-return HQ exit unresolved")
                        calendar = read_hq_details(self.rt, path)
                        if calendar["day"] != entry["before"]["calendar"]["day"]:
                            raise CheckpointError("NPC return crossed a calendar day")
                        operation.update(
                            calendar_after=calendar, hq_back_submitted=True
                        )
                        journal.save()
                        self.rt.task("SandPilot@Back")
                    time.sleep(0.25)
                raise CheckpointError(
                    "NPC world return unconfirmed; exit remains pending"
                )
            except BaseException as exc:
                operation["error"] = str(exc)
                journal.save()
                raise

    def run(self, before_world_image=None, before_calendar_image=None):
        with self.journal.locked() as journal:
            if journal.data["acts"].get("base-npc"):
                raise CheckpointError(
                    "Base NPC operation already pending or observed; never repeat gift choice"
                )
            first = self.frame()
            if self.observe_step(first, self.plan["steps"][0]) != "advance":
                raise CheckpointError(
                    "The exact first base NPC line and English speaker are required"
                )
            if (before_world_image is None) != (before_calendar_image is None):
                raise CheckpointError(
                    "Supply both pre-input world and calendar captures, or neither"
                )
            before = (
                self.bind_before(before_world_image, before_calendar_image)
                if before_world_image is not None
                else None
            )
            entry = {
                "status": "pending",
                "dialogue_id": self.plan["dialogue_id"],
                "first_image": str(first),
                "inputs": [],
                "inventory_updated": False,
                "quest_save_verified": False,
                "route_unlock_verified": False,
                "npc_withdrawal_verified": False,
                "before": before,
            }
            journal.data["acts"]["base-npc"] = entry
            journal.save()
            try:
                for index, step in enumerate(self.plan["steps"]):
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        path = self.frame()
                        action = self.observe_step(path, step)
                        if action is not None:
                            break
                        time.sleep(0.25)
                    else:
                        raise CheckpointError(
                            "Unknown or incomplete base NPC token; no blind advance"
                        )
                    if index == 4:
                        gift = read_stone_gift(self.rt, path)
                        gift["scene_verified"] = True
                        entry["gift"] = gift
                        entry["inputs"].append(
                            {"kind": "gift_ack", "image": str(path), "submitted": True}
                        )
                        journal.save()
                        self.rt.task("SandPilot@KnownDialogueAdvance")
                        # Acknowledge only once, then require the same final line without the modal.
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            path = self.frame()
                            if (
                                not self.rt.matches(path, ["SandAuto@BaseNpcStone"])
                                and self.observe_step(path, step) == "advance"
                            ):
                                break
                            time.sleep(0.25)
                        else:
                            raise CheckpointError(
                                "Gift acknowledgement unresolved; never repeat it"
                            )
                    entry["inputs"].append(
                        {
                            "kind": step["kind"],
                            "step": index,
                            "image": str(path),
                            "submitted": True,
                        }
                    )
                    journal.save()
                    if action == "advance":
                        self.rt.task("SandPilot@KnownDialogueAdvance")
                    else:
                        self.rt.click(action)
                paused = self.secure_return()
                entry.update(
                    status="dialogue_observed_paused",
                    paused_image=paused,
                    script_has_save=self.plan["script_has_save"],
                )
                journal.save()
                return copy.deepcopy(entry)
            except BaseException as exc:
                entry["error"] = str(exc)
                journal.save()
                # secure_return pauses recognized combat; unknown dialogue stays untouched.
                try:
                    self.secure_return()
                except CheckpointError as stop_error:
                    self.rt.log("base_npc_stop", reason=str(stop_error))
                raise


def review_base_npc(state, journal_path=None):
    for key, low, high in (("day", 3, 6), ("acts_used", 0, 2), ("hq", 2, 2)):
        if type(state.get(key)) is not int or not low <= state[key] <= high:
            raise CheckpointError(
                "Base NPC mode requires observed " + key + f" in {low}..{high}"
            )
    mode = state.get("npc_operation", "dialogue")
    if mode not in ("dialogue", "return"):
        raise CheckpointError("NPC operation must be dialogue or return")
    blockers = []
    if state.get("snapshot_current") is not True or state.get("settled") is not True:
        blockers.append("Require current settled campaign observations")
    if state.get("threat") not in ("clear", "later"):
        blockers.append(
            "Resolve unknown or urgent raid timing before the optional base visit"
        )
    for key in ("campaign_id", "observation_id"):
        if not isinstance(state.get(key), str) or not state[key].strip():
            blockers.append("Require explicit " + key)
    receipt = None
    if journal_path is not None and Path(journal_path).exists():
        receipt = json.loads(Path(journal_path).read_text(encoding="utf-8-sig"))
        if not isinstance(receipt, dict):
            raise CheckpointError("NPC journal must be an object")
        if (
            receipt.get("schema_version") != 1
            or receipt.get("campaign_id")
            != state.get("campaign_id", "") + ":base-npc-first-upgrade"
        ):
            blockers.append("NPC journal belongs to another campaign or schema")
            receipt = None
    acts = (receipt or {}).get("acts", {})
    if not isinstance(acts, dict):
        raise CheckpointError("NPC journal Acts must be an object")
    entry = acts.get("base-npc", {})
    if not isinstance(entry, dict):
        raise CheckpointError("NPC journal operation must be an object")
    if mode == "dialogue":
        if state.get("first_base_npc_pending") is not True:
            blockers.append("Observe that the first base NPC conversation is pending")
        if entry:
            blockers.append(
                "NPC dialogue already pending or observed; never repeat its choice"
            )
    elif (
        entry.get("status") not in ("dialogue_observed_paused", "world_return_verified")
        or not entry.get("before")
        or entry.get("gift", {}).get("scene_verified") is not True
    ):
        blockers.append(
            "Return requires an owned completed dialogue with pre-input world/calendar baseline and identified gift"
        )
    elif (
        entry["gift"].get("quantity") != 5
        or entry["before"].get("calendar", {}).get("day") != state["day"]
        or entry["before"].get("world", {}).get("hq") != state["hq"]
        or entry["before"].get("world", {}).get("acts_remaining")
        != 2 - state["acts_used"]
    ):
        blockers.append(
            "Owned NPC baseline or gift disagrees with the current day, HQ or Acts"
        )
    elif entry.get("return", {}).get("status") == "verified":
        blockers.append(
            "NPC return is already verified; use its existing receipt without replay"
        )
    return {
        "activity": "base-npc",
        "operation": mode,
        "blockers": blockers,
        "game_connected": False,
        "autoplay_enabled": False,
        "npc_initiation_enabled": False,
        "automatic_inventory_credit": False,
        "quest_save_verified": False,
        "day_advance_enabled": False,
        "dialogue_start": "Exact first English line and speaker; NPC selection is separate",
        "return_requirement": "Owned baseline captured before dialogue input; never import historical images as fresh proof",
    }


class BaseNpcCliWorkflow:
    def __init__(self, runtime, journal_path, campaign_id):
        self.dialogue = BaseNpcDialogue(
            runtime, journal_path, campaign_id, runtime.pack
        )

    def run(self, state):
        if state.get("npc_operation", "dialogue") == "return":
            return self.dialogue.return_world()
        return self.dialogue.run()


def run_base_npc_cli(args, parser, runtime_factory):
    from maa_sand_construction import run_construction_cli

    journal = (
        args.journal.with_name(args.journal.name + ".base-npc")
        if args.journal is not None
        else None
    )
    return run_construction_cli(
        args,
        parser,
        runtime_factory,
        lambda state: review_base_npc(state, journal),
        BaseNpcCliWorkflow,
        "--base-npc",
        ".base-npc",
        "base-npc",
        event_name="base_npc_result",
    )


def secure_camp_return(runtime, path=None, hits=None):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path is None:
            path, _ = runtime.capture("base-npc-camp-return")
            hits = runtime.matches(
                path,
                [
                    "SandAuto@DialogueLog",
                    "SandAuto@Battle",
                    "SandAuto@RaidBattle",
                    "SandAuto@Paused",
                    "BattleOfficiallyBegin",
                    *CAMP_TASKS,
                ],
            )
        guard_unidentified_battle(runtime, path, hits)
        if "SandAuto@DialogueLog" not in hits:
            camp = camp_identified(hits)
            field = any(
                task in hits for task in ("SandAuto@Battle", "SandAuto@RaidBattle")
            )
            if camp or field:
                if hits.get("SandAuto@Paused", {}).get("score", 0) < 0.85:
                    runtime.task("SandPilot@PauseNavigationBattle")
                final, _ = runtime.capture("base-npc-camp-paused")
                observed = runtime.matches(
                    final, ["SandAuto@Paused", "SandAuto@DialogueLog", *CAMP_TASKS]
                )
                if observed.get("SandAuto@Paused", {}).get("score", 0) < 0.85:
                    raise CheckpointError("Base NPC return pause was not confirmed")
                if (
                    field
                    or not camp
                    or not camp_identified(observed)
                    or "SandAuto@DialogueLog" in observed
                ):
                    raise CheckpointError(
                        "Unexpected field preserved paused; camp return unconfirmed"
                    )
                return str(final)
        path = None
        time.sleep(0.1)
    raise CheckpointError(
        "Base NPC camp return unconfirmed; no blind pause or navigation"
    )
