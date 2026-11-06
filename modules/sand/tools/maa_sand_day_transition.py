"""One journaled exhausted-day transition; never spends an Act or certifies a guide day."""

from maa_runtime import data_path

import copy
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from maa_sand_config import CheckpointError, anchor_spec, load_profile
from maa_sand_days import ActJournal
from maa_sand_world import read_world


def review_transition(state):
    if not isinstance(state, dict):
        raise CheckpointError("Day-transition state must be an object")
    day = state.get("day")
    source = state.get("last_day_observation", {})
    if (
        type(day) is not int
        or not 1 <= day <= 5
        or type(state.get("acts_used")) is not int
        or state["acts_used"] != 2
        or state.get("settled") is not True
        or state.get("snapshot_current") is not True
        or state.get("threat") not in ("clear", "later")
        or not isinstance(source, dict)
        or type(source.get("day")) is not int
        or source["day"] != day
        or not source.get("image")
        or any(
            not isinstance(state.get(key), str) or not state[key].strip()
            for key in ("campaign_id", "observation_id")
        )
    ):
        raise CheckpointError(
            "Day end requires an owned settled Day1-5, both Acts spent, known threat, and prior day evidence"
        )
    return {
        "day": day,
        "target_day": day + 1,
        "guide_day_complete": False,
        "scope": "Physical day transition only; guide objectives and production remain separate",
    }


def read_periodic_assessment(runtime, path, completed_day):
    """Recognize the Day3 score checkpoint; its continuation never proves Day4."""
    if completed_day != 3:
        return None
    reads = [
        r for r in runtime.ocr(path, [350, 120, 600, 450]) if r.get("score", 0) >= 0.85
    ]
    labels = {re.sub(r"\s+", "", r.get("text", "")).lower() for r in reads}
    if not {"survived", "score", "transformprosperity"} <= labels:
        return None
    if not any(
        re.fullmatch(r"1\s*[-–—~]\s*3", r.get("text", "").strip()) for r in reads
    ):
        return None
    return {
        "kind": "periodic_assessment",
        "completed_day": 3,
        "image": str(path),
        "evidence": reads,
    }


class DayTransition:
    def __init__(self, player, journal):
        self.player, self.rt, self.journal = player, player.rt, journal

    def observe(self, label):
        path, _, states = self.player.frame(label)
        if "SandAuto@Battle" in states:
            self.player.in_battle = True
            self.player.pause(True)
            raise CheckpointError("Unexpected day-transition battle preserved paused")
        return path, states

    def run(self, state):
        review = review_transition(state)
        if state["campaign_id"] != self.journal.campaign_id:
            raise CheckpointError("Day transition belongs to another campaign")
        with self.journal.locked() as journal:
            transitions = journal.data.setdefault("day_transitions", {})
            key = str(review["day"])
            entry = transitions.get(key)
            if entry is not None and entry.get("status") == "verified":
                return {**copy.deepcopy(entry), "already_verified": True}
            if entry is None:
                path, states = self.observe("day-end-before")
                if "SandAuto@World" not in states:
                    raise CheckpointError("Next Day requires the world map")
                before = read_world(self.rt, path)
                if before["acts_remaining"] != 0 or before["day"] not in (
                    None,
                    review["day"],
                ):
                    raise CheckpointError(
                        "Do not discard remaining Acts or advance another day"
                    )
                entry = {
                    "status": "pending",
                    **review,
                    "observation_id": state["observation_id"],
                    "last_day_observation": state["last_day_observation"],
                    "before": before,
                    "next_day_submitted": True,
                    "report_continue_submitted": False,
                }
                transitions[key] = entry
                journal.save()  # Persist before the only Next Day input.
                self.rt.task("SandPilot@NextDay")
            elif (
                entry.get("target_day") != review["target_day"]
                or entry.get("next_day_submitted") is not True
            ):
                raise CheckpointError("Unrecognized pending day-transition journal")
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    path, states = self.observe("day-end-arrival")
                    entry["last_image"] = str(path)
                    if "SandAuto@World" in states:
                        try:
                            after = read_world(self.rt, path)
                        except CheckpointError:
                            # Report/toast overlays can leave the map anchor visible.
                            # Observe again within the deadline; never resubmit Next Day.
                            after = None
                        if after is not None:
                            if (
                                after["day"] is not None
                                and after["day"] != review["target_day"]
                            ):
                                raise CheckpointError(
                                    "Actual day differs from the journaled next day"
                                )
                            if (after["day"], after["acts_remaining"]) == (
                                review["target_day"],
                                2,
                            ):
                                entry.update(
                                    status="verified",
                                    after=after,
                                    acts_restored=2,
                                    guide_day_complete=False,
                                    inventory_updated=False,
                                )
                                if "error" in entry:
                                    entry.setdefault("recovered_errors", []).append(
                                        entry.pop("error")
                                    )
                                journal.save()
                                self.rt.log("day_transition_verified", **entry)
                                return copy.deepcopy(entry)
                    controls = self.rt.matches(
                        path, ["SandPilot@StartToday", "SandAuto@FinishCalculation"]
                    )
                    if (
                        review["day"] == 3
                        and not entry.get("assessment_continue_submitted")
                        and controls.get("SandAuto@FinishCalculation", {}).get(
                            "score", 0
                        )
                        >= 0.85
                    ):
                        proof = read_periodic_assessment(self.rt, path, review["day"])
                        if proof is None:
                            raise CheckpointError(
                                "Calculation screen is not the owned Day1-3 assessment"
                            )
                        entry.update(
                            assessment_continue_submitted=True, assessment=proof
                        )
                        journal.save()
                        self.rt.task("SandAuto@FinishCalculation")
                        continue
                    if (
                        controls.get("SandPilot@StartToday", {}).get("score", 0) >= 0.85
                        and not entry["report_continue_submitted"]
                    ):
                        entry["report_continue_submitted"] = True
                        journal.save()
                        self.rt.task("SandPilot@StartToday")
                    time.sleep(0.5)
                raise CheckpointError(
                    "Day transition unresolved; Next Day will not be repeated"
                )
            except BaseException as exc:
                entry["error"] = str(exc)
                journal.save()
                raise


def run_day_transition_cli(args, parser, runtime_type):
    if not args.campaign_state or not args.journal:
        parser.error("--advance-day requires --campaign-state and --journal")
    try:
        state = json.loads(args.campaign_state.read_text(encoding="utf8"))
        review = review_transition(state)
        profile = load_profile(args.pack, args.route)
        assets = args.assets or Path(anchor_spec(args.pack, profile)["location"])
    except (CheckpointError, OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    if not args.execute or args.check:
        print(
            json.dumps(
                {**review, "game_connected": False, "journal": str(args.journal)},
                indent=2,
            )
        )
        return
    if not args.allow_experimental:
        parser.error(
            "Day transition requires --allow-experimental during live validation"
        )
    from maa_sand_player import SandPlayer

    output = args.output or data_path("sand-player", "day-transitions") / datetime.now(
        UTC
    ).strftime("%Y%m%dT%H%M%SZ")
    with runtime_type(args.runtime, output, args.pack) as runtime:
        player = SandPlayer(runtime, assets, profile)
        journal = ActJournal(args.journal, state["campaign_id"])
        DayTransition(player, journal).run(state)
