"""Exact known-script dialogue advancement through existing MaaCore callbacks."""

import hashlib
import json
import re
import time
from pathlib import Path

from maa_sand_battle import guard_unidentified_battle
from maa_sand_config import CheckpointError, default_pack
from maa_sand_settlement import text_key

BODY = [190, 555, 660, 80]
SPEAKER = [245, 505, 250, 55]
CHOICE = [875, 385, 390, 140]


def fingerprint(text):
    return hashlib.sha256(text_key(text).encode("utf8")).hexdigest()


def script_steps(text, *, include_narration=False):
    steps = []
    for line in text.splitlines():
        spoken = re.fullmatch(r'\[name="([^"]+)"[^\]]*\](.+)', line)
        if spoken:
            steps.append(
                {"kind": "line", "speaker": spoken[1], "digest": fingerprint(spoken[2])}
            )
        elif line.lower().startswith("[decision("):
            options = re.findall(r'option\d+="([^"]*)"', line, re.IGNORECASE)
            if len(options) != 1:
                raise CheckpointError(
                    "Only reviewed single-option decisions may be advanced"
                )
            steps.append({"kind": "choice", "digest": fingerprint(options[0])})
        elif include_narration and line.strip() and not line.startswith("["):
            steps.append({"kind": "narration", "digest": fingerprint(line.strip())})
    if not steps or len(steps) > 40:
        raise CheckpointError("Unsupported dialogue length")
    return steps


def ordered_text(reads):
    reads = [r for r in reads if r.get("text", "").strip()]
    if not reads or any(
        r.get("score", 0) < 0.85
        or len(r.get("rect", [])) != 4
        or any(type(v) not in (int, float) for v in r["rect"])
        or r["rect"][2] <= 0
        or r["rect"][3] <= 0
        for r in reads
    ):
        return None
    # Native detection can split a wrapped line into multiple boxes.
    rows = []
    for read in sorted(reads, key=lambda r: r["rect"][1] + r["rect"][3] / 2):
        center = read["rect"][1] + read["rect"][3] / 2
        if not rows or abs(center - rows[-1][0]) > 8:
            rows.append((center, [read]))
        else:
            rows[-1][1].append(read)
    return " ".join(
        r["text"] for _, row in rows for r in sorted(row, key=lambda r: r["rect"][0])
    )


def choice_point(reads, region=None):
    x, y, w, h = CHOICE if region is None else region
    if not reads or any(len(r.get("rect", [])) != 4 for r in reads):
        raise CheckpointError("Choice text has no verified rectangle")
    rects = [r["rect"] for r in reads]
    if any(
        rw <= 0 or rh <= 0 or rx < x or ry < y or rx + rw > x + w or ry + rh > y + h
        for rx, ry, rw, rh in rects
    ):
        raise CheckpointError("Choice text lies outside the verified choice region")
    left, top = min(r[0] for r in rects), min(r[1] for r in rects)
    right, bottom = max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)
    return (left + right) // 2, (top + bottom) // 2


def observe_step(runtime, path, step, *, body=BODY, speaker=SPEAKER, choice=CHOICE):
    reads = runtime.ocr(path, choice if step["kind"] == "choice" else body)
    text = ordered_text(reads)
    if text is None or fingerprint(text) != step["digest"]:
        return None
    if step["kind"] in ("line", "narration"):
        if step["kind"] == "line":
            name = ordered_text(runtime.ocr(path, speaker))
            if name is None or fingerprint(name) != fingerprint(step["speaker"]):
                return None
        return "advance"
    return choice_point(reads, choice)


class LiaisonDialogue:
    def __init__(self, runtime, pack=None):
        self.rt = runtime
        self.plan = json.loads(
            (
                (Path(pack) if pack else default_pack())
                / "guides/liaison-first-contact.json"
            ).read_text(encoding="utf8")
        )
        if (
            self.plan.get("schema_version") != 1
            or self.plan.get("autoplay_enabled") is not False
        ):
            raise CheckpointError("Unreviewed dialogue plan")
        for step in self.plan["steps"]:
            if step.get("kind") not in ("line", "choice") or not re.fullmatch(
                r"[a-f0-9]{64}", step.get("digest", "")
            ):
                raise CheckpointError("Invalid dialogue step")

    def observe(self, path, step):
        return observe_step(self.rt, path, step)

    def secure_return(self, path=None, states=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path is None:
                path, _ = self.rt.capture("liaison-return")
                states = self.rt.matches(
                    path, ["SandAuto@DialogueLog", "SandAuto@Battle", "SandAuto@Paused"]
                )
            if "SandAuto@DialogueLog" not in states and "SandAuto@Battle" in states:
                if "SandAuto@Paused" not in states:
                    self.rt.task("SandPilot@InitialPause", timeout=5)
                final, _ = self.rt.capture("liaison-paused")
                if not self.rt.matches(final, ["SandAuto@Paused"]):
                    raise CheckpointError(
                        "Dialogue ended but battle pause was not confirmed"
                    )
                return str(final)
            path = None
            time.sleep(0.1)
        raise CheckpointError("Dialogue return state unconfirmed; no further action")

    def run(self, stage_id, *, start_index=0, on_step=None):
        if stage_id not in self.plan["stage_ids"]:
            raise CheckpointError("Liaison intro is not admitted on this source stage")
        if type(start_index) is not int or not 0 <= start_index <= len(
            self.plan["steps"]
        ):
            raise CheckpointError("Invalid owned dialogue resume index")
        if on_step is not None and not callable(on_step):
            raise CheckpointError("Dialogue progress callback must be callable")
        evidence = []
        for index, step in enumerate(
            self.plan["steps"][start_index:], start=start_index
        ):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                path, _ = self.rt.capture("liaison-dialogue")
                states = self.rt.matches(
                    path,
                    [
                        "SandAuto@DialogueLog",
                        "SandAuto@Battle",
                        "SandAuto@Paused",
                        "BattleOfficiallyBegin",
                    ],
                )
                guard_unidentified_battle(self.rt, path, states)
                if "SandAuto@DialogueLog" not in states:
                    if "SandAuto@Battle" in states:
                        self.secure_return(path, states)
                        raise CheckpointError(
                            "Battle resumed before the known dialogue sequence completed"
                        )
                    time.sleep(0.25)
                    continue
                action = self.observe(path, step)
                if action is not None:
                    break
                time.sleep(0.25)
            else:
                raise CheckpointError(
                    "Unknown or incomplete dialogue token; no blind advance"
                )
            evidence.append(str(path))
            if on_step is not None:
                on_step("before", index, str(path), step["kind"])
            if action == "advance":
                self.rt.task("SandPilot@KnownDialogueAdvance")
            else:
                self.rt.click(action)
            if on_step is not None:
                on_step("after", index, str(path), step["kind"])
            self.rt.log(
                "known_dialogue_step",
                dialogue=self.plan["dialogue_id"],
                index=index,
                kind=step["kind"],
                image=str(path),
            )
        paused = self.secure_return()
        return {
            "status": "dialogue_sequence_observed_paused",
            "images": evidence,
            "paused_image": paused,
            "quest_save_verified": False,
            "route_unlock_verified": False,
        }
