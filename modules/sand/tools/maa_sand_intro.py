"""Fresh camp introduction through the existing exact-script dialogue engine."""

from maa_runtime import data_path

import json
import re
import time
from pathlib import Path

from maa_sand_base_npc import secure_camp_return
from maa_sand_config import CheckpointError, default_pack
from maa_sand_dialogue import LiaisonDialogue, observe_step


class CampIntroduction(LiaisonDialogue):
    def __init__(self, runtime, pack=None):
        self.rt = runtime
        pack = Path(pack) if pack else default_pack()
        self.plan = json.loads(
            (pack / "guides/camp-introduction.json").read_text(encoding="utf8")
        )
        if (
            self.plan.get("schema_version") != 1
            or self.plan.get("autoplay_enabled") is not False
            or self.plan.get("dialogue_id") != "dialog_sandbox_1_main1_1_op"
            or self.plan.get("stage_ids") != ["sandbox_1_33"]
            or len(self.plan.get("steps", [])) != 15
        ):
            raise CheckpointError("Unreviewed camp introduction")
        for step in self.plan["steps"]:
            if step.get("kind") not in (
                "line",
                "choice",
                "narration",
            ) or not re.fullmatch(r"[a-f0-9]{64}", step.get("digest", "")):
                raise CheckpointError("Invalid introduction token")

    def observe(self, path, step):
        return observe_step(
            self.rt, path, step, body=[400, 555, 790, 100], speaker=[460, 505, 400, 55]
        )

    def secure_return(self, path=None, states=None):
        # Fresh complete camp identity is required; partial dialogue observations
        # cannot stand in for the return frame.
        return secure_camp_return(self.rt)


def run_journaled_intro(runtime, journal_path, run_id, pack=None):
    """Resume only an owned exact source token; never replay an uncertain choice."""
    from maa_sand_days import ActJournal

    if not isinstance(run_id, str) or not run_id.strip():
        raise CheckpointError("Camp introduction requires an explicit campaign/run ID")
    actor = CampIntroduction(runtime, pack)
    with ActJournal(journal_path, "camp-intro:" + run_id).locked() as journal:
        entry = journal.data["acts"].get("intro")
        source_hash = actor.plan["source"]["sha256"]
        if entry is not None:
            if entry.get("source_sha256") != source_hash:
                raise CheckpointError(
                    "Introduction source changed; review the owned journal"
                )
            if entry.get("status") == "observed-paused":
                raise CheckpointError(
                    "Introduction already completed; no replay submitted"
                )
        else:
            entry = {
                "status": "pending",
                "source_sha256": source_hash,
                "next_index": 0,
                "inputs": [],
                "inventory_updated": False,
                "quest_save_verified": False,
            }
        next_index = entry.get("next_index")
        if type(next_index) is not int or not 0 <= next_index <= len(
            actor.plan["steps"]
        ):
            raise CheckpointError("Malformed introduction journal index")
        candidates = [next_index]
        if entry.get("pending_input") is not None:
            pending = entry["pending_input"]
            if (
                type(pending) is not int
                or pending != next_index
                or pending >= len(actor.plan["steps"])
            ):
                raise CheckpointError("Malformed pending introduction input")
            candidates.append(pending + 1)
        start = None
        for _ in range(8):
            path, _image = runtime.capture("intro-owned-entry")
            hits = runtime.matches(path, ["SandAuto@DialogueLog"])
            if "SandAuto@DialogueLog" in hits:
                matched = [
                    index
                    for index in candidates
                    if index < len(actor.plan["steps"])
                    and actor.observe(path, actor.plan["steps"][index]) is not None
                ]
                if len(matched) == 1:
                    start = matched[0]
                    break
            elif len(actor.plan["steps"]) in candidates:
                # An owned final input may already have returned to camp. The
                # complete camp guard must still verify that closing transition.
                start = len(actor.plan["steps"])
                break
            time.sleep(0.25)
        if start is None:
            raise CheckpointError(
                "Current dialogue does not match the owned introduction token"
            )
        entry.update(status="pending", next_index=start)
        entry.pop("pending_input", None)
        journal.data["acts"]["intro"] = entry
        journal.save()

        def progress(event, index, image, kind):
            if event == "before":
                entry["pending_input"] = index
                entry["inputs"].append(
                    {"index": index, "kind": kind, "image": image, "submitted": True}
                )
            else:
                entry["next_index"] = index + 1
                entry.pop("pending_input", None)
            journal.save()

        try:
            result = actor.run("sandbox_1_33", start_index=start, on_step=progress)
            entry.update(
                status="observed-paused",
                result=result,
                next_index=len(actor.plan["steps"]),
            )
            entry.pop("pending_input", None)
            journal.save()
            return entry
        except BaseException as exc:
            entry.update(status="stopped", error=str(exc))
            journal.save()
            try:
                path, _image = runtime.capture("intro-stopped")
                if "SandAuto@DialogueLog" not in runtime.matches(
                    path, ["SandAuto@DialogueLog"]
                ):
                    actor.secure_return()
            except Exception as pause_error:  # noqa: BLE001 - preserve the original operation failure
                runtime.log("intro_stop_pause_unconfirmed", reason=str(pause_error))
            raise


def run_intro_cli(args, parser, runtime_factory):
    from datetime import UTC, datetime

    conflicts = (
        "base_npc",
        "prepare_planter",
        "upgrade_hq2",
        "campaign_act",
        "visit_liaison",
    )
    if (
        any(getattr(args, key, False) for key in conflicts)
        or args.route is not None
        or args.raid_profile is not None
        or args.campaign_state is not None
        or args.assets is not None
    ):
        parser.error("--camp-intro cannot combine other operation or route modes")
    try:
        actor = CampIntroduction(None, args.pack)
    except (OSError, ValueError, KeyError, CheckpointError) as exc:
        parser.error(str(exc))
    if args.check or not args.execute:
        print(
            json.dumps(
                {
                    "mode": "camp-introduction",
                    "game_connected": False,
                    "steps": len(actor.plan["steps"]),
                    "exact_source_first_line_required": True,
                    "owned_journal_required_for_execution": True,
                    "autoplay_enabled": False,
                }
            )
        )
        return
    if not args.allow_experimental or args.journal is None or not args.intro_run_id:
        parser.error(
            "Camp introduction execution needs --allow-experimental, --journal and --intro-run-id"
        )
    output = args.output or data_path("sand-player", "runs") / (
        "intro-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    with runtime_factory(args.runtime, output, args.pack) as runtime:
        result = run_journaled_intro(
            runtime, args.journal, args.intro_run_id, args.pack
        )
        print(json.dumps(result, indent=2))
