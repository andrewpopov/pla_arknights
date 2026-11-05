"""Headless RA2 campaign player using MaaCore OCR, hand detection and Custom inputs.

The first supported route is Shrubbery Galore. Unknown stages and unverified
transitions stop at a screenshot checkpoint. Runtime logs/images stay on I:.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from maa_sand_battle import guard_unidentified_battle, raid_progress
from maa_sand_config import (
    REPEAT_SKILLS,
    REVIEWED_FIELD_TOOLS,
    CheckpointError,
    LoadReadError,
    anchor_spec,
    default_pack,
    load_profile,
    require_executable,
    validate_harvest_skill,
    verify_anchors,
)
from maa_sand_settlement import read_rewards
from maa_sand_tools import ToolCrafter, load_tool_catalog
from maa_sand_world import read_world
from maa_session import NativeSession

sys.path.insert(0, str(Path(r"I:\MAA-data\build-tools\sand-python")))

PACK = default_pack()


def canonical(text):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", text)).casefold()


def fraction(text, peak_capacity=0, allow_zero_capacity=False):
    """Require an actual carrying fraction, never use a nearby resource count."""
    text = re.sub(r"^\s*[Oo](?=\s*/)", "0", text)
    text = re.sub(r"(?<=\d)\.(?=/)", "", text)
    match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{1,2})\s*", text)
    if not match:
        return None
    current, capacity = map(int, match.groups())
    if type(peak_capacity) is not int or not 0 <= peak_capacity <= 6:
        return None
    if type(allow_zero_capacity) is not bool:
        return None
    if capacity == 0:
        proven = peak_capacity > 0 and current <= peak_capacity
        return (
            (current, 0) if proven or (current == 0 and allow_zero_capacity) else None
        )
    return (
        (current, capacity)
        if 0 < capacity <= 36 and 0 <= current <= max(capacity, peak_capacity)
        else None
    )


def timer_seconds(text):
    text = text.replace("O", "0").replace("o", "0")
    match = re.fullmatch(r"\s*(\d{2}):(\d{2})\s*", text)
    if not match:
        return None
    minutes, seconds = map(int, match.groups())
    return minutes * 60 + seconds if minutes <= 10 and seconds < 60 else None


@dataclass(frozen=True)
class Load:
    name: str
    current: int
    capacity: int
    deployment_id: int = 0

    @property
    def full(self):
        return self.current > 0 and self.current >= self.capacity


class CarrierPolicy:
    """The plan changes only after observed deployment/load/retreat confirmations."""

    def __init__(self):
        self.banked = 0
        self.completed = set()
        self.active = {}
        self.peaks = {}
        self.zero_capacity = set()
        self.serial = 0

    def begin(self, name, allow_zero_capacity=False):
        if name in self.active:
            raise CheckpointError("An operator already has an active deployment")
        self.serial += 1
        self.active[name] = self.serial
        self.peaks[name] = 0
        if allow_zero_capacity:
            self.zero_capacity.add(name)
        return self.serial

    def current(self, name):
        if name not in self.active:
            raise CheckpointError("Operator has no confirmed active deployment")
        return self.active[name]

    def peak(self, name, deployment_id):
        if self.current(name) != deployment_id:
            raise CheckpointError("Capacity observation belongs to a stale deployment")
        return self.peaks[name]

    def observe_capacity(self, name, deployment_id, capacity):
        self.peak(name, deployment_id)
        if not 0 <= capacity <= 6 or (
            capacity == 0 and name not in self.zero_capacity and not self.peaks[name]
        ):
            raise CheckpointError(
                "Carrying capacity is outside the supported guide range"
            )
        self.peaks[name] = max(self.peaks[name], capacity)

    def validate_load(self, load):
        if self.current(load.name) != load.deployment_id:
            raise CheckpointError("Carried load belongs to a stale deployment")
        peak = self.peak(load.name, load.deployment_id)
        if (
            not 0 < load.current <= max(load.capacity, peak)
            or not 0 <= load.capacity <= 6
        ):
            raise CheckpointError(
                "Carried load has not been confirmed for this deployment"
            )
        if (load.name, load.deployment_id) in self.completed:
            raise CheckpointError("This deployment has already banked its load")

    def bank(self, load: Load, confirmed_cooling: bool):
        self.validate_load(load)
        if not confirmed_cooling:
            raise CheckpointError("Retreat did not confirm a new carried load")
        self.banked += load.current
        self.completed.add((load.name, load.deployment_id))
        self.active.pop(load.name)
        self.peaks.pop(load.name)
        self.zero_capacity.discard(load.name)

    def complete_empty_recall(self, load, confirmed_cooling):
        if (
            self.current(load.name) != load.deployment_id
            or type(load.current) is not int
            or load.current != 0
            or type(load.capacity) is not int
            or not 0 <= load.capacity <= 6
            or confirmed_cooling is not True
        ):
            raise CheckpointError(
                "Empty recall needs a fresh zero-load observation and confirmed cooling"
            )
        self.completed.add((load.name, load.deployment_id))
        self.active.pop(load.name)
        self.peaks.pop(load.name)
        self.zero_capacity.discard(load.name)

    @staticmethod
    def should_retreat(load: Load, remaining: int, source_empty=False):
        return load.current > 0 and (load.full or source_empty or remaining <= 25)


class SceneMap:
    """Register textured map scenery; reject repetitive or weak geometry."""

    def __init__(self, reference, *, extended_terrain=False):
        self.extended_terrain = extended_terrain
        import cv2

        self.cv = cv2
        self.reference = self.normalize(reference)
        self.sift = cv2.SIFT_create(nfeatures=3500)
        self.keypoints, self.descriptors = self.features(self.reference)
        if self.descriptors is None:
            raise CheckpointError("Map reference has no features")

    @staticmethod
    def normalize(image):
        import cv2

        return cv2.resize(image, (1280, 720))

    def features(self, image):
        import numpy as np

        mask = np.zeros((720, 1280), dtype=np.uint8)
        # Exclude HUD, portraits, minimap and hand. Roofs/floors remain.
        mask[70:580, 470:970] = 255
        if self.extended_terrain:
            mask[70:580, 970:1250] = 255
            mask[250:490, 980:1250] = 0  # Minimap.
            mask[490:580, 1130:1250] = 0  # DP and unit-limit HUD.
            mask[70:125, 1030:1250] = 0  # Speed controls.
        # PAUSE/Game Paused stays fixed while the map camera moves. Shared UI
        # descriptors must never contribute evidence for map registration.
        mask[300:455, 490:810] = 0
        return self.sift.detectAndCompute(
            self.cv.cvtColor(image, self.cv.COLOR_BGR2GRAY), mask
        )

    def transform(self, current):
        current = self.normalize(current)
        keypoints, descriptors = self.features(current)
        if descriptors is None:
            raise CheckpointError("No current map features")
        pairs = self.cv.BFMatcher().knnMatch(self.descriptors, descriptors, k=2)
        good = [
            a
            for pair in pairs
            if len(pair) == 2
            for a, b in [pair]
            if a.distance < 0.68 * b.distance
        ]
        try:
            return self._fit_transform(good, keypoints)
        except CheckpointError:
            if not self.extended_terrain:
                raise
        # Repeated Jungle floor tiles can assign several reference descriptors
        # to one target. Reciprocal matches remove those ambiguous assignments;
        # every geometric acceptance threshold below remains unchanged.
        reverse = self.cv.BFMatcher().knnMatch(descriptors, self.descriptors, k=2)
        backward = {
            (a.queryIdx, a.trainIdx)
            for pair in reverse
            if len(pair) == 2
            for a, b in [pair]
            if a.distance < 0.68 * b.distance
        }
        reciprocal = [
            match for match in good if (match.trainIdx, match.queryIdx) in backward
        ]
        return self._fit_transform(reciprocal, keypoints)

    def _fit_transform(self, good, keypoints):
        import numpy as np

        if len(good) < 20:
            raise CheckpointError("Insufficient distinct map matches")
        source = np.float32([self.keypoints[m.queryIdx].pt for m in good])
        target = np.float32([keypoints[m.trainIdx].pt for m in good])
        matrix, inliers = self.cv.findHomography(source, target, self.cv.RANSAC, 2.5)
        if matrix is None or inliers is None:
            raise CheckpointError("Map registration failed")
        selected = inliers.ravel().astype(bool)
        if selected.sum() < 18 or selected.mean() < 0.45:
            raise CheckpointError("Map registration has too few geometric inliers")
        spread = np.ptp(source[selected], axis=0)
        if spread[0] < 150 or spread[1] < 130:
            raise CheckpointError("Map matches occupy a narrow repetitive strip")
        predicted = self.cv.perspectiveTransform(source[selected][None], matrix)[0]
        if np.median(np.linalg.norm(predicted - target[selected], axis=1)) > 1.5:
            raise CheckpointError("Map reprojection error is too large")
        corners = np.float32([[[500, 100], [950, 100], [950, 570], [500, 570]]])
        moved = self.cv.perspectiveTransform(corners, matrix)[0]
        if not np.isfinite(moved).all() or not self.cv.isContourConvex(moved):
            raise CheckpointError("Invalid map geometry")
        area = abs(self.cv.contourArea(moved)) / (450 * 470)
        if not 0.45 < area < 2.1:
            raise CheckpointError("Map scale changed outside the calibrated range")
        return matrix

    def point(self, current, point):
        import numpy as np

        matrix = self.transform(current)
        result = self.cv.perspectiveTransform(np.float32([[point]]), matrix)[0, 0]
        x, y = map(float, result)
        if not (430 < x < 1000 and 80 < y < 580):
            raise CheckpointError("Registered tile is outside the clear map viewport")
        return round(x), round(y)


def facing_diamond(image):
    """Measure the post-drag selector instead of assuming its camera or size."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 224, 255)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        polygon = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        area = abs(cv2.contourArea(polygon))
        if (
            len(polygon) != 4
            or not cv2.isContourConvex(polygon)
            or not 24000 < area < 260000
        ):
            continue
        points = polygon[:, 0].astype(float)
        center = points.mean(axis=0)
        if 450 < center[0] < 1000 and 100 < center[1] < 590:
            lengths = np.linalg.norm(points - np.roll(points, 1, axis=0), axis=1)
            if lengths.max() / lengths.min() < 1.9:
                candidates.append((area, tuple(map(round, center)), points))
    if not candidates:
        raise CheckpointError("No unambiguous deployment-facing diamond")
    _area, center, points = max(candidates, key=lambda candidate: candidate[0])
    return center, points


def facing_center(image):
    """Facing diamonds are measured after dragging, because the camera shifts."""
    return facing_diamond(image)[0]


def facing_swipe(image, direction):
    """Release beyond the observed diamond; a short swipe can leave it pending."""
    import numpy as np

    vectors = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
    if direction not in vectors:
        raise CheckpointError("Invalid deployment facing direction")
    center, points = facing_diamond(image)
    vector = np.array(vectors[direction])
    distance = float(((points - np.array(center)) @ vector).max()) + 24
    end = tuple(round(c + d * distance) for c, d in zip(center, vector, strict=True))
    if not (0 <= end[0] < image.shape[1] and 0 <= end[1] < image.shape[0]):
        raise CheckpointError(
            "Facing diamond has no visible release point in this direction"
        )
    return center, end


def retreat_button_point(image):
    """Locate the red retreat glyph on its dark control after exact actor selection."""
    import cv2
    import numpy as np

    if image is None:
        raise CheckpointError("Retreat requires a captured selected-operator panel")
    hsv = cv2.cvtColor(SceneMap.normalize(image), cv2.COLOR_BGR2HSV)
    roi = hsv[130:300, 470:900]
    red = cv2.inRange(
        roi, np.array([0, 130, 100]), np.array([10, 255, 255])
    ) | cv2.inRange(roi, np.array([175, 130, 100]), np.array([179, 255, 255]))
    joined = cv2.dilate(red, np.ones((5, 5), np.uint8))
    _count, _labels, stats, _centers = cv2.connectedComponentsWithStats(joined)
    candidates = []
    for x, y, width, height, _area in stats[1:]:
        ink = cv2.countNonZero(red[y : y + height, x : x + width])
        px, py = int(470 + x + width // 2), int(130 + y + height // 2)
        dark = (hsv[py - 32 : py + 33, px - 37 : px + 38, 2] < 75).mean()
        if (
            25 <= width <= 65
            and 25 <= height <= 65
            and 0.65 < width / height < 1.5
            and 200 <= ink <= 1000
            and dark >= 0.7
        ):
            candidates.append((px, py))
    if len(candidates) != 1:
        raise CheckpointError("No unique retreat glyph on a dark operator control")
    return candidates[0]


def carry_image(image):
    """Normalize actual numerator, separator and denominator glyphs for MaaCore OCR."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(SceneMap.normalize(image), cv2.COLOR_BGR2GRAY)
    pieces = []
    for x, y, w, h in [(85, 280, 32, 43), (115, 290, 11, 32), (126, 290, 22, 32)]:
        mask = cv2.inRange(gray[y : y + h, x : x + w], 50, 255)
        ink = cv2.findNonZero(mask)
        if ink is None or len(ink) < 8:
            raise CheckpointError("Carrying fraction has an absent glyph or separator")
        xx, yy, ww, hh = cv2.boundingRect(ink)
        if hh < 7:
            raise CheckpointError("Carrying glyph is too small to verify")
        piece = mask[yy : yy + hh, xx : xx + ww]
        pieces.append(
            cv2.resize(
                piece, (round(64 * ww / hh), 64), interpolation=cv2.INTER_NEAREST
            )
        )
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    x = 15
    for piece in pieces:
        if x + piece.shape[1] > 310:
            raise CheckpointError("Carrying glyph normalization overflow")
        canvas[15:79, x : x + piece.shape[1]] = cv2.cvtColor(piece, cv2.COLOR_GRAY2BGR)
        x += piece.shape[1] + 8
    return canvas


def pause_button_state(image, paused_template, running_template):
    """Classify the fixed battle button; absence of play alone never means running."""
    import cv2

    gray = cv2.cvtColor(SceneMap.normalize(image), cv2.COLOR_BGR2GRAY)
    roi = gray[20:85, 1165:1240]
    scores = [
        cv2.minMaxLoc(cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED))[1]
        for template in (paused_template, running_template)
    ]
    paused, running = scores[0] >= 0.95, scores[1] >= 0.90
    if paused == running:
        return None
    return paused


class MaaRuntime:
    def __init__(
        self, runtime, output, pack=PACK, capture_backend="native", touch_mode="adb"
    ):
        if capture_backend not in {"native", "adb"}:
            raise ValueError("Unknown capture backend")
        self.capture_backend = capture_backend
        self.touch_mode = touch_mode
        self.pack = Path(pack)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.results = []
        self.events = []
        self.counter = 0
        self.finished = threading.Event()
        self.native = None
        sys.path.insert(0, str(Path(runtime) / "Python"))
        from asst.asst import Asst

        self.Asst = Asst

        @Asst.CallBackType
        def callback(number, payload, _):
            data = json.loads(payload.decode("utf8"))
            self.events.append((number, data))
            if data.get("what") == "DebugImageTest":
                self.results.append(data.get("details", {}))
            if number == 3:
                self.finished.set()

        self.callback = callback
        self.session = NativeSession(
            runtime,
            self.output,
            callback,
            overlays=[pack],
            touch_mode=touch_mode,
            deployment_with_pause=touch_mode != "adb",
        )

    def __enter__(self):
        self.native = self.session.__enter__()
        # Same native instance performs live control and saved-frame analysis.
        import ctypes

        self.lib = self.Asst._Asst__lib
        self.lib.AsstAsyncScreencap.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        self.lib.AsstAsyncScreencap.restype = ctypes.c_int
        self.lib.AsstAsyncClick.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_bool,
        ]
        self.lib.AsstAsyncClick.restype = ctypes.c_int
        return self

    def __exit__(self, *args):
        self.session.__exit__(*args)

    def log(self, what, **details):
        record = {"time": datetime.now(UTC).isoformat(), "what": what, **details}
        with (self.output / "player.jsonl").open("a", encoding="utf8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def run(self, kind, params, timeout=20):
        self.events.clear()
        self.results.clear()
        self.finished.clear()
        task_id = self.native.append_task(kind, params)
        if not task_id or not self.native.start():
            raise CheckpointError(f"MaaCore rejected {kind} task")
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.finished.is_set() and not self.native.running():
                break
            time.sleep(0.03)
        else:
            self.native.stop()
            raise CheckpointError(f"{kind} task exceeded {timeout}s")
        errors = [d for n, d in self.events if n in (10000, 20000)]
        results = list(self.results)
        self.native.stop()  # Clear completed queue, retaining this controller lease.
        if errors:
            raise CheckpointError(
                f"{kind} task failed: {errors[0].get('subtask', 'task chain')}"
            )
        return results

    def capture(self, label="frame"):
        import cv2
        import numpy as np

        if self.capture_backend == "adb":
            # Keep native OCR, inputs and the shared lease; bypass SDK capture only.
            try:
                result = subprocess.run(
                    [
                        r"I:\MuMuPlayerGlobal\nx_main\adb.exe",
                        "-s",
                        self.session.address,
                        "exec-out",
                        "screencap",
                        "-p",
                    ],
                    # MuMu can take10s to produce its first frame after idling.
                    capture_output=True,
                    check=True,
                    timeout=12,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                raise CheckpointError("ADB screen capture failed") from exc
            raw = result.stdout
        else:
            if self.lib.AsstAsyncScreencap(self.native._Asst__ptr, True) <= 0:
                raise CheckpointError("Native screen capture failed")
            raw = self.native.get_image(1280 * 720 * 8)
        if not raw:
            raise CheckpointError("Native screen buffer is empty")
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise CheckpointError("Native screenshot is not a decodable image")
        self.device_size = (image.shape[1], image.shape[0])
        self.counter += 1
        path = self.output / f"{self.counter:05d}-{label}.png"
        image = SceneMap.normalize(image)
        cv2.imwrite(str(path), image)
        return path, image

    def analyze(self, path, mode="ocr", **params):
        result = self.run("Debug", {"mode": mode, "images": [str(path)], **params})
        if len(result) != 1 or result[0].get("error"):
            raise CheckpointError("Native analysis did not produce exactly one result")
        return result[0]

    def ocr(self, path, roi):
        return self.analyze(path, roi=list(roi)).get("results", [])

    def matches(self, path, tasks):
        requested = list(dict.fromkeys(tasks))
        virtual_raid = "SandAuto@RaidBattle" in requested
        native = [task for task in requested if task != "SandAuto@RaidBattle"]
        if virtual_raid:
            native = list(
                dict.fromkeys([*native, "SandAuto@RaidKills", "SandAuto@RaidLives"])
            )
        hits = {
            x["task"]: x
            for x in self.analyze(path, "report", tasks=native).get("results", [])
            if x.get("hit")
        }
        if virtual_raid:
            progress = raid_progress(hits)
            if progress is not None:
                hits["SandAuto@RaidBattle"] = {
                    "task": "SandAuto@RaidBattle",
                    "algorithm": "ParsedRaidHUD",
                    "hit": True,
                    "score": hits["SandAuto@RaidKills"]["score"],
                    "kills": progress.kills,
                    "total": progress.total,
                    "lives": progress.lives,
                    "stage_verified": False,
                }
            for task in ("SandAuto@RaidKills", "SandAuto@RaidLives"):
                if task not in requested:
                    hits.pop(task, None)
        return hits

    def input(self, action, point, end=None, duration=550):
        self.counter += 1
        name = f"SandAuto@Input{self.counter}"
        task = {
            "algorithm": "JustReturn",
            "action": action,
            "specificRect": [*point, 1, 1],
            "postDelay": 450,
            "maxTimes": 1,
            "next": [],
        }
        if action == "Swipe":
            task.update(rectMove=[*end, 1, 1], specialParams=[duration, 0, 10, 10])
        overlay = self.output / "inputs"
        path = overlay / "resource/tasks/input.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({name: task}), encoding="utf8")
        if not self.lib.AsstLoadResource(str(overlay).encode("utf8")):
            raise CheckpointError("Native action resource was rejected")
        self.run("Custom", {"task_names": [name]}, timeout=8)

    def click(self, point):
        if (
            self.lib.AsstAsyncClick(
                self.native._Asst__ptr, int(point[0]), int(point[1]), True
            )
            <= 0
        ):
            raise CheckpointError("Native click was rejected")
        time.sleep(0.45)

    def swipe(self, start, end):
        if self.capture_backend != "adb" or self.touch_mode != "adb":
            self.input("Swipe", start, end)
            return
        # The native API has no async swipe. Reuse its ADB transport without
        # rebuilding the entire task graph for every variable endpoint.
        size = getattr(self, "device_size", None)
        if size is None:
            raise CheckpointError("ADB swipe requires a fresh physical screenshot")
        points = [start, end]
        if any(
            len(point) != 2
            or any(type(v) is not int for v in point)
            or not (0 <= point[0] < 1280 and 0 <= point[1] < 720)
            for point in points
        ):
            raise CheckpointError(
                "ADB swipe endpoint is outside the normalized viewport"
            )
        raw = [
            str(round(value * size[axis] / (1280, 720)[axis]))
            for point in points
            for axis, value in enumerate(point)
        ]
        try:
            subprocess.run(
                [
                    r"I:\MuMuPlayerGlobal\nx_main\adb.exe",
                    "-s",
                    self.session.address,
                    "shell",
                    "input",
                    "swipe",
                    *raw,
                    "550",
                ],
                capture_output=True,
                check=True,
                timeout=5,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise CheckpointError("ADB swipe failed; inspect before repeating") from exc
        self.log("adb_swipe", start=start, end=end, device_size=size, duration=550)
        time.sleep(0.15)

    def pause_battle(self, paused):
        """Stop the clock before slower OCR using the same calibrated native templates."""
        import cv2
        import numpy as np

        if type(paused) is not bool or self.capture_backend != "adb":
            raise CheckpointError(
                "Fast pause requires an ADB battle and a boolean target"
            )
        if not hasattr(self, "_pause_templates"):
            paths = (
                self.pack / "resource/template/SandPausedPlay.png",
                Path(self.session.install)
                / "resource/template/Battle/BattleFlag/BattleOfficiallyBegin.png",
            )
            self._pause_templates = tuple(
                cv2.imdecode(
                    np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE
                )
                for path in paths
            )
            if any(template is None for template in self._pause_templates):
                raise CheckpointError("Pause button templates are unavailable")
        for attempt in range(4):
            path, image = self.capture("pause-button")
            actual = pause_button_state(image, *self._pause_templates)
            if actual is None:
                raise CheckpointError(
                    "Battle pause button is unknown; no blind toggle issued"
                )
            if actual == paused:
                self.log(
                    "pause_button_confirmed",
                    paused=paused,
                    image=str(path),
                    attempts=attempt,
                )
                return
            if attempt >= 2:
                break
            self.click((1208, 52))
            time.sleep(0.2)
        raise CheckpointError("Battle pause button did not reach the requested state")

    def task(self, name, timeout=20):
        self.log("native_task", task=name)
        self.run("Custom", {"task_names": [name]}, timeout)


class SandPlayer:
    OBSERVERS: ClassVar[list[str]] = [
        "SandAuto@World",
        "SandAuto@Result",
        "SandAuto@Squad",
        "SandAuto@Battle",
        "SandAuto@Paused",
        "SandAuto@CancelFacing",
        "SandAuto@EndConfirm",
        "SandAuto@NoEnergy",
        "SandAuto@Headquarters",
    ]

    def __init__(self, runtime, assets, profile=None):
        import cv2

        self.rt = runtime
        self.assets = Path(assets)
        self.profile = profile if profile is not None else load_profile(PACK)
        if self.profile.get("theme") != "Tales":
            raise CheckpointError(
                "This route has not been calibrated for that theme/stage"
            )
        if self.profile.get("stage") != "Shrubbery Galore":
            catalog = json.loads(
                (self.rt.pack / "campaign/stages.json").read_text(encoding="utf8")
            )
            stage = catalog["stages"].get(self.profile.get("stage_id"))
            if not stage or stage["english"] != self.profile.get("stage"):
                raise CheckpointError(
                    "This route has not been calibrated for that theme/stage"
                )
        verify_anchors(self.rt.pack, self.assets, self.profile)
        for phase_name in self.profile.get("calibration_phases", {}):
            phase_profile = load_profile(
                self.rt.pack, self.profile["id"], phase=phase_name
            )
            verify_anchors(
                self.rt.pack,
                Path(anchor_spec(self.rt.pack, phase_profile)["location"]),
                phase_profile,
            )
        extended = self.profile.get("registration_mask") == "jungle"
        self.idle_map = SceneMap(
            cv2.imread(str(self.assets / self.profile["anchors"]["idle"])),
            extended_terrain=extended,
        )
        self.side_map = SceneMap(
            cv2.imread(str(self.assets / self.profile["anchors"]["side"])),
            extended_terrain=extended,
        )
        self.policy = CarrierPolicy()
        self.normal = {
            key: tuple(value) for key, value in self.profile["normal_points"].items()
        }
        self.side = {
            key: tuple(value) for key, value in self.profile["side_points"].items()
        }
        self.deployed = {}
        self.deployed_tools = {}
        self.tool_deployment_budgets = {}
        self.pending_tool_deployment = None
        self.in_battle = False
        self.raid_mode = False

    def refresh_calibration(self, phase=None):
        """Reload same-route geometry without losing active cargo or banked credits."""
        import cv2

        phase = self.profile.get("active_phase") if phase is None else phase
        profile = load_profile(self.rt.pack, self.profile["id"], phase=phase)
        identity = (
            "id",
            "theme",
            "stage_id",
            "stage",
            "required_squad",
            "zero_capacity_actors",
            "registration_mask",
        )
        if (
            getattr(self, "raid_mode", False)
            or any(profile.get(key) != self.profile.get(key) for key in identity)
            or getattr(self, "selected_hand_point", None) is not None
            or getattr(self, "pending_tool_deployment", None)
            or getattr(self, "pending_retreat", None)
        ):
            raise CheckpointError(
                "Calibration refresh requires the same route and no unresolved input"
            )
        occupied = set(self.deployed) | set(self.deployed_tools)
        if any(
            not occupied.issubset(profile[key])
            for key in ("normal_points", "side_points")
        ):
            raise CheckpointError(
                "Refreshed calibration omitted an active deployment slot"
            )
        assets = Path(anchor_spec(self.rt.pack, profile)["location"])
        verify_anchors(self.rt.pack, assets, profile)
        extended = profile.get("registration_mask") == "jungle"
        idle = SceneMap(
            cv2.imread(str(assets / profile["anchors"]["idle"])),
            extended_terrain=extended,
        )
        side = SceneMap(
            cv2.imread(str(assets / profile["anchors"]["side"])),
            extended_terrain=extended,
        )
        # Swap only after both new maps passed construction; the resource ledger stays owned.
        self.assets, self.profile = assets, profile
        self.idle_map, self.side_map = idle, side
        self.normal = {
            key: tuple(value) for key, value in profile["normal_points"].items()
        }
        self.side = {key: tuple(value) for key, value in profile["side_points"].items()}
        self.rt.log(
            "calibration_refreshed",
            route=profile["id"],
            banked=self.policy.banked,
            active_deployments=dict(self.deployed),
        )
        return {
            "route": profile["id"],
            "banked": self.policy.banked,
            "active_deployments": dict(self.deployed),
            "paid_action_submitted": False,
        }

    def frame(self, label="state"):
        path, image = self.rt.capture(label)
        tasks = (
            ["SandAuto@Battle", "SandAuto@Paused"]
            if self.in_battle
            else [
                "SandAuto@World",
                "SandAuto@Squad",
                "SandAuto@Battle",
                "SandAuto@Result",
                "SandAuto@NoEnergy",
                "SandAuto@Headquarters",
            ]
        )
        if label == "facing":
            tasks.append("SandAuto@CancelFacing")
        if label in ("settlement", "stopped"):
            tasks = self.OBSERVERS
        tasks = list(tasks)
        if not self.in_battle or getattr(self, "raid_mode", False):
            tasks.extend(
                ["SandAuto@RaidKills", "SandAuto@RaidLives", "SandAuto@Result"]
            )
        tasks.append("BattleOfficiallyBegin")
        states = self.rt.matches(path, tasks)
        guard_unidentified_battle(self.rt, path, states)
        progress = None if "SandAuto@Result" in states else raid_progress(states)
        if progress is not None:
            if not getattr(self, "raid_mode", False):
                self.rt.log(
                    "raid_hud_detected",
                    image=str(path),
                    kills=progress.kills,
                    total=progress.total,
                    lives=progress.lives,
                    stage_verified=False,
                )
            self.raid_mode = True
            self.raid_progress = progress
            states["SandAuto@RaidBattle"] = {
                "kills": progress.kills,
                "total": progress.total,
                "lives": progress.lives,
            }
            # Share only pause handling, never the gathering timer or route.
            states["SandAuto@Battle"] = states["SandAuto@RaidBattle"]
        states.pop("SandAuto@RaidKills", None)
        states.pop("SandAuto@RaidLives", None)
        if "SandAuto@NoEnergy" in states and label != "loading":
            raise CheckpointError(
                "Not enough energy drinks: brew food before retrying the expedition"
            )
        return path, image, states

    def stable_frame(self, label):
        """Require a paused, settled camera before computing any map input."""
        import numpy as np

        self.pause(True)
        previous_path, previous, _ = self.frame(label + "-settling")
        for _ in range(4):
            time.sleep(0.35)
            path, image, states = self.frame(label)
            if "SandAuto@Paused" not in states:
                raise CheckpointError("Map analysis requires a verified paused battle")
            try:
                matrix = SceneMap(previous).transform(image)
                points = np.array(
                    [
                        [500.0, 150.0, 1.0],
                        [900.0, 150.0, 1.0],
                        [500.0, 530.0, 1.0],
                        [900.0, 530.0, 1.0],
                    ]
                )
                moved = (matrix @ points.T).T
                projected = moved[:, :2] / moved[:, 2:]
                if np.max(np.linalg.norm(projected - points[:, :2], axis=1)) <= 2:
                    return path, image, states
            except CheckpointError:
                pass
            previous_path, previous = path, image
        raise CheckpointError(f"Camera did not settle for {label}: {previous_path}")

    def remaining(self, path):
        if getattr(self, "raid_mode", False):
            raise CheckpointError(
                "Raid battle uses kills, not the harvesting countdown"
            )
        for roi in ([560, 8, 175, 50], [608, 12, 105, 40]):
            readings = [
                timer_seconds(x.get("text", ""))
                for x in self.rt.ocr(path, roi)
                if x.get("score", 0) >= 0.85
            ]
            valid = [x for x in readings if x is not None]
            if len(valid) == 1:
                return valid[0]
        raise CheckpointError("Battle timer could not be read uniquely")

    def pause(self, paused=True):
        if (
            getattr(self, "in_battle", False)
            and getattr(self.rt, "capture_backend", None) == "adb"
        ):
            self.rt.pause_battle(paused)
            return
        _path, _, states = self.frame("pause-check")
        if "SandAuto@Battle" not in states:
            raise CheckpointError("Pause requested outside a verified gathering battle")
        actual = "SandAuto@Paused" in states
        if actual != paused:
            if paused:
                self.rt.task("SandPilot@PauseNavigationBattle")
            else:
                self.rt.click((1208, 52))
            for attempt in range(3):
                time.sleep(0.5)
                _, _, after = self.frame("pause-confirm")
                if paused and "SandAuto@Paused" in after:
                    return
                if (
                    not paused
                    and "SandAuto@Battle" in after
                    and "SandAuto@Paused" not in after
                ):
                    return
                # A missed pause tap must not leave the clock running while
                # an exception is reviewed. Retry only from an independently
                # recognized running pause button, never from an unknown frame.
                if (
                    paused
                    and attempt < 2
                    and after.get("BattleOfficiallyBegin", {}).get("score", 0) >= 0.85
                    and "SandAuto@Paused" not in after
                ):
                    self.rt.log("pause_retry", attempt=attempt + 1)
                    self.rt.task("SandPilot@PauseNavigationBattle")
            raise CheckpointError("Pause transition did not confirm")

    def name(self, path, *, minimum_confidence=None):
        reads = self.rt.ocr(path, [45, 105, 205, 48])
        if minimum_confidence is not None and any(
            x.get("text", "").strip() and x.get("score", 0) < minimum_confidence
            for x in reads
        ):
            raise CheckpointError(
                "Complete deployment name is not confidently observed"
            )
        return " ".join(x.get("text", "") for x in reads)

    def operator_matches(self, path, expected, observed):
        """Resolve the observed Młynar glyph only with his selected S3 identity."""
        if canonical(expected) == canonical(observed):
            return True
        # Keep these exact native observations local to this operator panel;
        # canonical() must not become a fuzzy name matcher for the roster.
        if expected != "Młynar" or canonical(observed) not in {
            "mlynar",
            "mtynar",
            "miynar",
        }:
            return False
        try:
            confident = self.name(path, minimum_confidence=0.85)
        except CheckpointError:
            return False
        if canonical(confident) != canonical(observed):
            return False
        titles = [
            read
            for read in self.rt.ocr(path, [75, 405, 360, 45])
            if read.get("score", 0) >= 0.9
        ]
        return len(titles) == 1 and canonical(titles[0].get("text", "")) == canonical(
            "Unbrilliant Glory"
        )

    def close_panel(self):
        selected = getattr(self, "selected_hand_point", None)
        if selected is not None:
            self.rt.click(selected)
            self.selected_hand_point = None
        self.rt.click((1100, 180))
        time.sleep(0.8)  # Let the inspection camera return before mapping ground tiles.

    def advance(self, seconds):
        if not 0 < seconds <= 5:
            raise CheckpointError(
                "Unobserved gathering intervals are limited to five seconds"
            )
        self.service_background_skills()
        if getattr(self, "rt", None) is not None:
            self.close_panel()
        self.pause(False)
        try:
            time.sleep(seconds)
        finally:
            self.pause(True)

    def service_background_skills(self):
        profile = getattr(self, "profile", {})
        if not isinstance(profile, dict):
            return
        specs = profile.get("background_skills", [])
        deployed = getattr(self, "deployed", {})
        active = [spec for spec in specs if deployed.get(spec["slot"]) == spec["name"]]
        if not active:
            return
        self.pause(True)
        path, _, _ = self.frame("background-skill-clock")
        if self.remaining(path) <= profile.get("background_skill_remaining_floor", 25):
            return
        for spec in active:
            self.repeated_skill(
                spec["name"], spec["slot"], spec["sp_cost"], spec["maximum"]
            )

    def open_operator(
        self, name, slot, *, minimum_confidence=None, deployment_point=None
    ):
        if (
            getattr(self, "profile", {}).get("reuse_operator_panel")
            and self.profile.get("stage_id") == "sandbox_1_40"
            and self.deployed.get(slot) == name
        ):
            current, pixels = self.rt.capture("operator-current")
            try:
                retreat_button_point(pixels)
            except CheckpointError:
                pass
            else:
                observed = (
                    self.name(current)
                    if minimum_confidence is None
                    else self.name(current, minimum_confidence=minimum_confidence)
                )
                if self.operator_matches(current, name, observed):
                    return current
        self.close_panel()
        self.pause(True)
        path, image, _ = self.stable_frame("operator-location")
        if deployment_point is not None:
            if (
                not isinstance(deployment_point, (list, tuple))
                or len(deployment_point) != 2
                or any(type(value) is not int for value in deployment_point)
                or not 430 < deployment_point[0] < 1000
                or not 80 < deployment_point[1] < 580
            ):
                raise CheckpointError(
                    "Observed deployment center is outside the clear viewport"
                )
            point = tuple(deployment_point)
        else:
            try:
                point = self.idle_map.point(image, self.normal[slot])
            except CheckpointError:
                pan = self.profile.get("camera_recovery_pan")
                if (
                    self.profile.get("stage_id") != "sandbox_1_40"
                    or pan != [[930, 180], [1070, 168]]
                    or getattr(self, "raid_mode", False)
                ):
                    raise
                if self.rt.matches(path, ["SandAuto@CancelFacing"]):
                    raise CheckpointError(
                        "Preserve the unresolved facing selector; do not pan"
                    )
                self.pause(True)
                self.rt.swipe(tuple(pan[0]), tuple(pan[1]))
                path, image, states = self.stable_frame("camera-recovery")
                if "SandAuto@Paused" not in states:
                    raise CheckpointError(
                        "Camera recovery requires a positively paused battle"
                    )
                point = self.idle_map.point(image, self.normal[slot])
                self.rt.log(
                    "camera_registration_recovered",
                    slot=slot,
                    image=str(path),
                    point=point,
                )
        self.pause(False)
        try:
            self.rt.click(point)
        finally:
            self.pause(True)
        time.sleep(1)
        path, _, _ = self.frame("operator-panel")
        observed = (
            self.name(path)
            if minimum_confidence is None
            else self.name(path, minimum_confidence=minimum_confidence)
        )
        if not self.operator_matches(path, name, observed):
            raise CheckpointError(f"Operator at {slot} was not verified as {name}")
        return path

    def load(self, name, slot):
        deployment_id = self.policy.current(name)
        path = self.open_operator(name, slot)
        # Native OCR on the original fraction preserves a slash lost by glyph stitching.
        peak = self.policy.peak(name, deployment_id)
        raw_values = [
            fraction(
                read.get("text", ""),
                peak_capacity=peak,
                allow_zero_capacity=name in self.policy.zero_capacity,
            )
            for read in self.rt.ocr(path, [75, 280, 83, 45])
            if read.get("score", 0) >= 0.85
        ]
        raw_values = [value for value in raw_values if value is not None]
        if len(raw_values) == 1:
            self.policy.observe_capacity(name, deployment_id, raw_values[0][1])
            return Load(name, *raw_values[0], deployment_id=deployment_id)
        import cv2

        canvas = carry_image(cv2.imread(str(path)))
        for suffix, pixels in [("carry", canvas), ("carry-inverse", 255 - canvas)]:
            prepared = path.with_name(path.stem + f"-{suffix}.png")
            cv2.imwrite(str(prepared), pixels)
            reads = self.rt.ocr(prepared, [0, 0, 320, 100])
            reads = [x for x in reads if x.get("score", 0) >= 0.8]
            peak = self.policy.peak(name, deployment_id)
            values = [
                fraction(
                    x.get("text", ""),
                    peak_capacity=peak,
                    allow_zero_capacity=name in self.policy.zero_capacity,
                )
                for x in reads
            ]
            values = [x for x in values if x is not None]
            if len(values) == 1:
                self.policy.observe_capacity(name, deployment_id, values[0][1])
                return Load(name, *values[0], deployment_id=deployment_id)
        raise LoadReadError(f"No unique carrying fraction for {name}")

    def deploy_tool(self, item_id, slot, direction=None, *, maximum=2):
        """Deploy a reviewed tool instance; never register it as a carrying operator."""
        if (
            not isinstance(item_id, str)
            or item_id not in REVIEWED_FIELD_TOOLS
            or type(maximum) is not int
            or not 1 <= maximum <= 2
        ):
            raise CheckpointError("Unreviewed tool or deployment budget")
        name, trap_id = REVIEWED_FIELD_TOOLS[item_id]
        tool = load_tool_catalog(self.rt.pack).get(item_id, {})
        identity = tool.get("battle_identity", {})
        if (
            tool.get("id") != item_id
            or tool.get("name") != name
            or identity.get("trap_id") != trap_id
            or identity.get("english_name") != name
            or identity.get("profession") != "TRAP"
        ):
            raise CheckpointError("Reviewed tool battle identity changed")
        budgets = getattr(self, "tool_deployment_budgets", {})
        if item_id in budgets and budgets[item_id] != maximum:
            raise CheckpointError(
                "Tool deployment budget cannot change within an operation"
            )
        if (
            sum(x["item_id"] == item_id for x in self.deployed_tools.values())
            >= maximum
        ):
            raise CheckpointError("Tool operation budget is exhausted")
        return self._deploy(
            name, slot, direction, tool_id=item_id, tool_maximum=maximum
        )

    def adopt_deployed(self, name, slot):
        """Recover a physical actor after takeover/error using fresh panel identity."""
        if (
            not self.in_battle
            or getattr(self, "raid_mode", False)
            or name not in self.profile.get("required_squad", [])
            or slot not in self.normal
            or slot not in self.side
            or slot in self.deployed
            or name in self.deployed.values()
            or name in self.policy.active
        ):
            raise CheckpointError(
                "Adoption requires an unclaimed calibrated gathering actor"
            )
        path = self.open_operator(name, slot)
        deployment_id = self.policy.begin(
            name,
            allow_zero_capacity=name in self.profile.get("zero_capacity_actors", []),
        )
        self.deployed[slot] = name
        result = {
            "name": name,
            "slot": slot,
            "image": str(path),
            "deployment_id": deployment_id,
            "identity_verified": True,
            "new_deployment": False,
            "orientation_independently_verified": False,
        }
        self.rt.log("deployment_adopted", **result)
        self.close_panel()
        return result

    def deployment_facing(self):
        """Observe a settling selector again before treating its animation as failure."""
        for attempt in range(3):
            path, image, states = self.frame("facing")
            if "SandAuto@CancelFacing" in states:
                return path, image, states
            if attempt < 2:
                time.sleep(0.35)
        return path, image, states

    def deploy(self, name, slot, direction="Left"):
        return self._deploy(name, slot, direction)

    def deploy_raid(self, name, slot, direction):
        if not self.in_battle or not getattr(self, "raid_mode", False):
            raise CheckpointError("Raid deployment requires the recognized raid battle")
        return self._deploy(name, slot, direction, combat=True)

    def _select_available_card(self, name, *, tool=False):
        """Reuse native deployment analysis and the existing selected-name verifier."""
        self.close_panel()
        self.pause(True)
        path, _, _ = self.frame("hand")
        hand = self.rt.analyze(path, "battle_deployment")
        candidates = [
            x
            for x in hand.get("operators", [])
            if x.get("available") and not x.get("cooling")
        ]
        if tool:
            candidates = [
                x
                for x in candidates
                if x.get("available") is True and x.get("cooling") is False
            ]
        else:
            # A previous exact-name match is only a search-order hint. Always
            # rescan the current hand and verify the selected identity again.
            hint = getattr(self, "hand_identity_hints", {}).get(name)
            if hint is not None:
                candidates.sort(key=lambda candidate: candidate.get("rect") != hint)
        for candidate in candidates:
            x, y, w, h = candidate["rect"]
            self.selected_hand_point = (x + w // 2, y + h // 2)
            self.rt.click(self.selected_hand_point)
            time.sleep(
                1
            )  # Card selection animates the map camera; never map a moving frame.
            selected, image, _ = self.stable_frame("selected-hand")
            observed = (
                self.name(selected, minimum_confidence=0.9)
                if tool
                else self.name(selected)
            )
            if self.operator_matches(selected, name, observed):
                if tool and (
                    type(hand.get("dp")) is not int
                    or type(candidate.get("cost")) is not int
                    or not 0 <= candidate["cost"] <= hand["dp"]
                ):
                    raise CheckpointError(
                        "Tool cost and sufficient DP must be freshly observed"
                    )
                if not tool:
                    if not hasattr(self, "hand_identity_hints"):
                        self.hand_identity_hints = {}
                    self.hand_identity_hints[name] = list(candidate["rect"])
                return (x + w // 2, y + h // 2), image, selected, candidate, hand
            self.close_panel()
        return None

    def wait_operator_ready(self, name, maximum_game_seconds=120, remaining_floor=30):
        """Wait for this named carrier's current cost/cooldown, with bounded clock advances."""
        if (
            not self.in_battle
            or getattr(self, "raid_mode", False)
            or name not in self.profile.get("required_squad", [])
            or name in self.deployed.values()
            or getattr(self, "pending_retreat", None) is not None
            or getattr(self, "pending_tool_deployment", None) is not None
            or type(maximum_game_seconds) is not int
            or not 1 <= maximum_game_seconds <= 120
            or type(remaining_floor) is not int
            or not 25 <= remaining_floor <= 240
        ):
            raise CheckpointError(
                "Carrier readiness requires a gathering battle, inactive squad actor and bounded reserve"
            )
        self.close_panel()
        self.pause(True)
        path, _, _ = self.frame("carrier-readiness-start")
        start = previous = self.remaining(path)
        # Also bound attempts if an unreadably frozen clock never progresses.
        for attempt in range(maximum_game_seconds + 1):
            path, _, _ = self.frame("carrier-readiness-clock")
            remaining = self.remaining(path)
            if remaining > previous:
                raise CheckpointError(
                    "Operation clock increased while waiting for a carrier"
                )
            if attempt and remaining == previous:
                raise CheckpointError(
                    "Operation clock did not advance during carrier readiness wait"
                )
            previous = remaining
            if (
                remaining <= remaining_floor
                or start - remaining >= maximum_game_seconds
            ):
                raise CheckpointError(
                    "Carrier readiness exceeded its game-time budget; battle remains paused"
                )
            selected = self._select_available_card(name)
            if selected is not None:
                center, _image, path, candidate, hand = selected
                # Cancel our positively identified card before servicing skills or deployment.
                self.rt.click(center)
                self.selected_hand_point = None
                cost, dp = candidate.get("cost"), hand.get("dp")
                if (
                    candidate.get("available") is not True
                    or candidate.get("cooling") is not False
                    or type(cost) is not int
                    or type(dp) is not int
                    or not 0 <= cost <= dp
                ):
                    raise CheckpointError(
                        "Named carrier readiness needs fresh affordable cost and non-cooling state"
                    )
                result = {"name": name, "cost": cost, "dp": dp, "image": str(path)}
                self.rt.log("carrier_ready", **result)
                return result
            seconds = min(
                3,
                remaining - remaining_floor,
                maximum_game_seconds - (start - remaining),
            )
            self.advance(seconds)
        raise CheckpointError(
            "Carrier readiness observation limit reached; battle remains paused"
        )

    def carrier_trip(self, name, slot, direction, minimum, timeout):
        target = self.profile.get("banked_wood_target")
        if (
            type(target) is not int
            or not 1 <= target <= 100
            or type(self.policy.banked) is not int
            or self.policy.banked < 0
            or type(minimum) is not int
            or not 1 <= minimum <= 6
            or type(timeout) is not int
            or not 1 <= timeout <= 120
        ):
            raise CheckpointError(
                "Carrier rotation needs bounded target, load and observed banked cargo"
            )
        needed = target - self.policy.banked
        if needed <= 0:
            self.rt.log(
                "carrier_trip_skipped",
                name=name,
                banked=self.policy.banked,
                target=target,
            )
            return
        self.wait_operator_ready(name)
        self.deploy(name, slot, direction)
        load = self.wait_load(name, slot, min(minimum, needed), timeout=timeout)
        self.retreat(load, slot)

    def verify_wood_settlement(self):
        target = self.profile.get("banked_wood_target")
        if target is None:
            return
        delivered = self.settlement.get("verified_counts", {}).get("wood")
        if (
            type(target) is not int
            or not 1 <= target <= 100
            or type(self.policy.banked) is not int
            or self.policy.banked < target
            or type(delivered) is not int
            or delivered < target
            or not self.settlement.get("image")
        ):
            raise CheckpointError(
                "Wood target was not independently confirmed in banked cargo and settlement"
            )
        self.wood_completion = {
            "target": target,
            "banked": self.policy.banked,
            "delivered": delivered,
            "image": self.settlement["image"],
        }
        self.rt.log("wood_target_settled", **self.wood_completion)

    def _deploy(
        self, name, slot, direction, *, tool_id=None, tool_maximum=None, combat=False
    ):
        if combat and (not getattr(self, "raid_mode", False) or tool_id is not None):
            raise CheckpointError(
                "Combat deployment requires a raid operator, not a field tool"
            )
        if getattr(self, "raid_mode", False) and not combat:
            raise CheckpointError("Harvest deployment is forbidden in a raid battle")
        vectors = {
            "Left": (-135, 0),
            "Right": (135, 0),
            "Up": (0, -135),
            "Down": (0, 135),
        }
        if direction not in vectors and not (tool_id and direction is None):
            raise CheckpointError(
                "Deployment direction has not been specified correctly"
            )
        if getattr(self, "pending_tool_deployment", None):
            raise CheckpointError(
                "Unresolved tool placement: do not spend another deployment"
            )
        if slot not in self.normal or slot not in self.side:
            raise CheckpointError("Deployment requires both calibrated camera points")
        if slot in self.deployed or slot in getattr(self, "deployed_tools", {}):
            raise CheckpointError("Deployment slot is already occupied")
        if not tool_id and (
            (combat and name in self.deployed.values())
            or (not combat and name in self.policy.active)
        ):
            raise CheckpointError(
                "Duplicate actor/clone deployment requires separate identity support"
            )
        selected = self._select_available_card(name, tool=tool_id is not None)
        if selected is None:
            raise CheckpointError(
                f"{name} was not available in the native detected hand"
            )
        found, image, _selected, _candidate, _hand = selected
        target = self.side_map.point(image, self.side[slot])
        # Require the observed green placement tile, not merely a projected point.
        import cv2
        import numpy as np

        x, y = target
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        roi = hsv[max(0, y - 18) : y + 19, max(0, x - 18) : x + 19]
        green = cv2.inRange(roi, np.array([30, 35, 30]), np.array([90, 255, 255]))
        if (green > 0).mean() < 0.14:
            # Cancel this positively identified hand card so it is not hidden
            # from the next native hand scan after a rejected tile.
            self.rt.click(found)
            self.selected_hand_point = None
            raise CheckpointError(f"{slot} is not a green deployment tile")
        if tool_id:
            if not hasattr(self, "tool_deployment_budgets"):
                self.tool_deployment_budgets = {}
            self.tool_deployment_budgets[tool_id] = tool_maximum
            self.pending_tool_deployment = {
                "item_id": tool_id,
                "name": name,
                "slot": slot,
                "maximum": tool_maximum,
            }
            self.rt.log("tool_deployment_pending", **self.pending_tool_deployment)
        self.selected_hand_point = None  # Drag consumes/cancels the selected hand card.
        self.rt.swipe(found, target)
        _facing, image, states = self.deployment_facing()
        has_facing = "SandAuto@CancelFacing" in states
        if has_facing:
            if direction is None:
                # Leave the selector unresolved: a second deployment could spend twice.
                raise CheckpointError(
                    "Tool requires a facing direction; placement remains pending"
                )
            start, end = facing_swipe(image, direction)
            self.rt.swipe(start, end)
        elif not tool_id or direction is not None:
            self.pause(True)
            raise CheckpointError(
                "Deployment did not reach the requested facing selector"
            )
        self.pause(True)
        if (
            not tool_id
            and has_facing
            and self.profile.get("verify_facing_center")
            and self.profile.get("stage_id") == "sandbox_1_40"
        ):
            verified = self.open_operator(name, slot, deployment_point=start)
        else:
            verified = (
                self.open_operator(name, slot, minimum_confidence=0.9)
                if tool_id
                else self.open_operator(name, slot)
            )
        if tool_id:
            record = {
                **self.pending_tool_deployment,
                "instance": len(self.deployed_tools) + 1,
                "requested_direction": direction,
                "facing_selector_observed": has_facing,
            }
            self.deployed_tools[slot] = record
            self.pending_tool_deployment = None
            self.rt.log(
                "tool_deployment_verified",
                **record,
                image=str(verified),
                inventory_debit_verified=False,
                orientation_independently_verified=False,
            )
            self.close_panel()
            return record
        if combat:
            self.combat_deployment_counter = (
                getattr(self, "combat_deployment_counter", 0) + 1
            )
            deployment_id = self.combat_deployment_counter
            if not hasattr(self, "combat_deployment_ids"):
                self.combat_deployment_ids = {}
            self.combat_deployment_ids[name] = deployment_id
        else:
            deployment_id = self.policy.begin(
                name,
                allow_zero_capacity=name
                in self.profile.get("zero_capacity_actors", []),
            )
        if hasattr(self, "skills_used"):
            self.skills_used.discard(name)
        self.deployed[slot] = name
        self.rt.log(
            "deployment_verified",
            deployment_id=deployment_id,
            name=name,
            slot=slot,
            direction=direction,
            image=str(verified),
            combat=combat,
        )
        if combat or not (
            self.profile.get("keep_operator_panel")
            and self.profile.get("stage_id") == "sandbox_1_40"
        ):
            self.close_panel()
        if combat:
            return {
                "image": str(verified),
                "name": name,
                "slot": slot,
                "requested_direction": direction,
                "identity_verified": True,
                "orientation_independently_verified": False,
            }

    def skill_once(self, name, slot):
        if not hasattr(self, "skills_used"):
            self.skills_used = set()
        if name in self.skills_used:
            return True
        path = self.open_operator(name, slot)
        labels = self.rt.ocr(path, [800, 435, 105, 60])
        ready = [
            x
            for x in labels
            if canonical(x.get("text", "")) in ("ready", "zready")
            and x.get("score", 0) >= 0.85
        ]
        if not ready:
            self.close_panel()
            return False
        x, y, w, _h = ready[0]["rect"]
        self.pause(False)
        try:
            self.rt.click((x + w // 2, y - 45))
        finally:
            self.pause(True)
        self.skills_used.add(name)
        self.rt.log("skill_clicked", name=name)
        self.close_panel()
        return True

    def repeated_skill(self, name, slot, sp_cost, maximum):
        """Activate only from READY; confirm spent SP before recording another cycle."""
        deployment_id = self.policy.current(name)
        if self.deployed.get(slot) != name:
            raise CheckpointError(
                "Repeated skill requires the matching confirmed deployment"
            )
        if not hasattr(self, "skill_cycles"):
            self.skill_cycles = {}
        key = (name, deployment_id)
        if not hasattr(self, "skill_pending"):
            self.skill_pending = set()
        if key in self.skill_pending:
            raise CheckpointError(
                "Prior skill submission is unresolved; preserve paused checkpoint"
            )
        count = self.skill_cycles.get(key, 0)
        if count >= maximum:
            return False
        expected = REPEAT_SKILLS.get(name)
        if expected is None or sp_cost != expected[1]:
            raise CheckpointError(
                "Repeated skill does not match the reviewed skill reference"
            )
        activation = self._verified_skill_click(name, slot, expected[0], sp_cost, key)
        if activation is None:
            return False
        self.skill_cycles[key] = count + 1
        self.rt.log(
            "skill_cycle_confirmed",
            name=name,
            deployment_id=deployment_id,
            cycle=count + 1,
            **activation,
        )
        return True

    def resume_repeated_skill(self, name, slot, sp_cost, maximum):
        """Confirm an owned pending activation by observation, without clicking again."""
        deployment_id = self.policy.current(name)
        key = (name, deployment_id)
        expected = REPEAT_SKILLS.get(name)
        count = getattr(self, "skill_cycles", {}).get(key, 0)
        if (
            self.deployed.get(slot) != name
            or expected is None
            or sp_cost != expected[1]
            or type(maximum) is not int
            or not 1 <= maximum <= 5
            or count >= maximum
            or key not in getattr(self, "skill_pending", set())
        ):
            raise CheckpointError("No matching pending repeated skill to confirm")
        activation = self._confirm_skill_spent(name, slot, sp_cost, key)
        self.skill_cycles[key] = count + 1
        self.rt.log(
            "skill_cycle_confirmed",
            name=name,
            deployment_id=deployment_id,
            cycle=count + 1,
            resumed=True,
            **activation,
        )
        return activation

    def _verified_skill_click(self, name, slot, expected_title, sp_cost, key):
        if not hasattr(self, "skill_pending"):
            self.skill_pending = set()
        if key in self.skill_pending:
            raise CheckpointError("Prior skill submission is unresolved; do not repeat")
        path = self.open_operator(name, slot)
        titles = self.rt.ocr(path, [75, 405, 360, 45])
        title = " ".join(r.get("text", "") for r in titles if r.get("score", 0) >= 0.85)
        if canonical(title) != canonical(expected_title):
            raise CheckpointError(
                "Selected skill name was not verified for repeat activation"
            )
        ready = [
            r
            for r in self.rt.ocr(path, [800, 435, 210, 80])
            if canonical(r.get("text", "")) in ("ready", "zready")
            and r.get("score", 0) >= 0.85
        ]
        if len(ready) != 1:
            self.close_panel()
            return None
        x, y, w, _h = ready[0]["rect"]
        self.skill_pending.add(key)
        self.pause(False)
        try:
            self.rt.click((x + w // 2, y - 45))
        finally:
            self.pause(True)
        # A submitted click is not proof of activation. Never retry this click
        # when the transition is ambiguous; stop at its paused screenshot.
        return self._confirm_skill_spent(name, slot, sp_cost, key)

    def _confirm_skill_spent(self, name, slot, sp_cost, key):
        if key not in self.skill_pending:
            raise CheckpointError(
                "Skill confirmation requires an owned pending submission"
            )
        after = self.open_operator(name, slot)
        reads = [
            r
            for r in self.rt.ocr(after, [800, 435, 210, 80])
            if r.get("score", 0) >= 0.85
        ]
        still_ready = any(
            canonical(r.get("text", "")) in ("ready", "zready") for r in reads
        )
        spent = []
        for read in reads:
            text = re.sub(r"^\s*[Oo](?=\s*/)", "0", read.get("text", ""))
            match = re.fullmatch(r"\s*(\d{1,3})\s*/\s*(\d{1,3})\s*", text)
            if match and int(match[2]) == sp_cost and 0 <= int(match[1]) < sp_cost:
                spent.append(int(match[1]))
        if still_ready or len(spent) != 1:
            raise CheckpointError(
                "Skill click submitted but spent SP unconfirmed; do not repeat"
            )
        self.skill_pending.remove(key)
        self._observe_skill_capacity(after, name, key)
        self.close_panel()
        return {"image": str(after), "sp": spent[0], "sp_cost": sp_cost}

    def _observe_skill_capacity(self, image, name, key):
        # Reuse the positively identified spent-SP panel while the temporary
        # block/carry increase is visible. No extra unpause or operator click.
        if (
            getattr(self, "raid_mode", False)
            or name not in getattr(self, "profile", {}).get("zero_capacity_actors", [])
            or name not in self.policy.active
            or key != (name, self.policy.current(name))
        ):
            return

        def capacities(reads):
            values = [
                fraction(
                    read.get("text", ""), peak_capacity=self.policy.peak(name, key[1])
                )
                for read in reads
                if read.get("score", 0) >= 0.9
            ]
            return [
                value for value in values if value is not None and 0 < value[1] <= 6
            ]

        values = capacities(self.rt.ocr(image, [75, 280, 83, 45]))
        path = Path(image)
        if not values and path.is_file():
            import cv2

            pixels = cv2.imread(str(path))
            try:
                canvas = carry_image(pixels) if pixels is not None else None
            except CheckpointError:
                canvas = None
            if canvas is not None:
                for suffix, prepared_pixels in [
                    ("carry", canvas),
                    ("carry-inverse", 255 - canvas),
                ]:
                    prepared = path.with_name(path.stem + "-skill-" + suffix + ".png")
                    cv2.imwrite(str(prepared), prepared_pixels)
                    values = capacities(self.rt.ocr(prepared, [0, 0, 320, 100]))
                    if values:
                        break
        if len(values) == 1:
            self.policy.observe_capacity(name, key[1], values[0][1])
            self.rt.log(
                "skill_carry_capacity_observed",
                name=name,
                deployment_id=key[1],
                capacity=values[0][1],
                carried=values[0][0],
                image=str(image),
            )

    def raid_skill(self, name, slot, expected_title, sp_cost):
        if (
            not self.in_battle
            or not getattr(self, "raid_mode", False)
            or self.deployed.get(slot) != name
            or name not in getattr(self, "combat_deployment_ids", {})
        ):
            raise CheckpointError(
                "Raid skill requires the matching confirmed combat deployment"
            )
        key = ("raid", name, self.combat_deployment_ids[name])
        return self._verified_skill_click(name, slot, expected_title, sp_cost, key)

    def maintain_skills(self, skills, duration, remaining_floor):
        """Service permanent DPS while advancing in existing bounded pause windows."""
        path, _, _ = self.frame("skills-start")
        start = previous = self.remaining(path)
        if start <= remaining_floor:
            raise CheckpointError("Not enough operation time for skill maintenance")
        for _ in range(duration + 1):
            for spec in skills:
                self.repeated_skill(
                    spec["name"], spec["slot"], spec["sp_cost"], spec["maximum"]
                )
            path, _, _ = self.frame("skills-progress")
            remaining = self.remaining(path)
            if remaining > previous:
                raise CheckpointError(
                    "Operation clock increased during skill maintenance"
                )
            if start - remaining >= duration or remaining <= remaining_floor:
                return
            previous = remaining
            self.advance(min(4, remaining - remaining_floor))
        raise CheckpointError("Skill maintenance clock stalled; stopped paused")

    def _retreat_controls(self, name, slot, deployment_id):
        # The caller has just identified this actor and read its actual cargo panel.
        if getattr(self, "pending_retreat", None) is not None:
            raise CheckpointError(
                "Previous retreat is unresolved; do not click it again"
            )
        before, image, _ = self.frame("retreat-before")
        point = retreat_button_point(image)
        old_hand = self.rt.analyze(before, "battle_deployment")
        old_cooling = sum(bool(x.get("cooling")) for x in old_hand.get("operators", []))
        self.pending_retreat = {
            "name": name,
            "slot": slot,
            "deployment_id": deployment_id,
            "point": point,
        }
        self.rt.log("retreat_pending", **self.pending_retreat)
        self.pause(False)
        try:
            self.rt.click(point)
        finally:
            self.pause(True)
        time.sleep(0.5)
        path, _, _ = self.frame("retreat-confirm")
        hand = self.rt.analyze(path, "battle_deployment")
        new_cooling = sum(bool(x.get("cooling")) for x in hand.get("operators", []))
        # An older card may finish cooling during this click. In that case,
        # require a positively parsed new hand card and a cooling card instead
        # of treating the net cooling count as operator identity.
        returned_card = (
            old_hand.get("hit") is True
            and hand.get("hit") is True
            and len(hand.get("operators", [])) == len(old_hand.get("operators", [])) + 1
            and new_cooling >= 1
        )
        if new_cooling != old_cooling + 1 and not returned_card:
            raise CheckpointError("Retreat did not produce a cooling operator")
        self.pending_retreat = None

    def retreat(self, load, slot):
        # load() leaves the verified actor panel open. Refuse empty banking.
        if load.current <= 0 or self.deployed.get(slot) != load.name:
            raise CheckpointError("Retreat requires a verified nonempty carrier")
        self.policy.validate_load(load)
        self._retreat_controls(load.name, slot, load.deployment_id)
        self.policy.bank(load, True)
        self.deployed.pop(slot)
        self.rt.log(
            "wood_banked",
            name=load.name,
            deployment_id=load.deployment_id,
            quantity=load.current,
            total=self.policy.banked,
        )

    def retreat_raid(self, name, slot):
        """Vacate an identified combat lane through existing retreat confirmation; credit no cargo."""
        deployment = getattr(self, "combat_deployment_ids", {}).get(name)
        if (
            not self.in_battle
            or not getattr(self, "raid_mode", False)
            or self.deployed.get(slot) != name
            or type(deployment) is not int
            or deployment < 1
            or getattr(self, "pending_retreat", None) is not None
        ):
            raise CheckpointError(
                "Combat retreat requires the current owned raid deployment and no pending retreat"
            )
        self.open_operator(name, slot)
        self._retreat_controls(name, slot, deployment)
        self.deployed.pop(slot)
        self.combat_deployment_ids.pop(name)
        proof = {
            "name": name,
            "slot": slot,
            "deployment_id": deployment,
            "cooling_transition_verified": True,
            "resource_credit": 0,
        }
        self.rt.log("raid_operator_retreated", **proof)
        return proof

    def recall(self, name, slot):
        """Recall a hunter through the same identified retreat; never invent banked cargo."""
        if (
            not self.in_battle
            or getattr(self, "raid_mode", False)
            or self.deployed.get(slot) != name
            or getattr(self, "pending_retreat", None) is not None
        ):
            raise CheckpointError(
                "Recall requires this active gathering deployment and no unresolved retreat"
            )
        load = self.load(name, slot)
        if load.name != name or load.deployment_id != self.policy.current(name):
            raise CheckpointError("Recall cargo belongs to a different deployment")
        if load.current > 0:
            self.retreat(load, slot)
        else:
            if (
                type(load.current) is not int
                or load.current != 0
                or type(load.capacity) is not int
                or not 0 <= load.capacity <= 6
            ):
                raise CheckpointError(
                    "Recall needs a confident nonnegative cargo observation"
                )
            self._retreat_controls(name, slot, load.deployment_id)
            self.policy.complete_empty_recall(load, True)
            self.deployed.pop(slot)
            self.rt.log(
                "hunter_recalled", name=name, deployment_id=load.deployment_id, banked=0
            )

    def wait_load(self, name, slot, minimum, skill=False, timeout=100):
        validate_harvest_skill(name, skill)
        end = time.monotonic() + timeout * 8
        clock, _, _ = self.frame("collection-start-clock")
        start_remaining = self.remaining(clock)
        if start_remaining <= 25:
            raise CheckpointError(
                f"{name} did not collect the expected load; exit reserve reached"
            )
        activated = False
        while time.monotonic() < end:
            if skill and not activated:
                activated = self.skill_once(name, slot)
            try:
                load = self.load(name, slot)
            except LoadReadError:
                self.rt.log("carrying_unreadable", name=name)
                self.close_panel()
                clock, _, _ = self.frame("unreadable-collection-clock")
                remaining = self.remaining(clock)
                elapsed = start_remaining - remaining
                if remaining <= 25 or elapsed >= timeout:
                    break
                self.advance(min(4, (remaining - 25) / 2, (timeout - elapsed) / 2))
                continue
            path, _, _ = self.frame("load-check")
            remaining = self.remaining(path)
            self.rt.log(
                "carrying",
                name=name,
                current=load.current,
                capacity=load.capacity,
                remaining=remaining,
            )
            if load.full and load.current < minimum:
                raise CheckpointError(
                    f"{name} is full at {load.current}/{load.capacity}; requested {minimum}. "
                    "Review current block/stance before continuing to wait."
                )
            if load.current >= minimum or (remaining <= 25 and load.current > 0):
                return load
            elapsed = start_remaining - remaining
            if remaining <= 25 or elapsed >= timeout:
                break
            self.close_panel()
            self.advance(min(4, (remaining - 25) / 2, (timeout - elapsed) / 2))
        raise CheckpointError(f"{name} did not collect the expected load")

    def click_label(self, path, text, roi):
        labels = [
            x
            for x in self.rt.ocr(path, roi)
            if canonical(x.get("text", "")) == canonical(text)
        ]
        if len(labels) != 1:
            raise CheckpointError(f"Expected one {text} control")
        x, y, w, h = labels[0]["rect"]
        self.rt.click((x + w // 2, y + h // 2))

    def energy_counts(self, path):
        values = self.rt.matches(path, ["SandAuto@EnergyStock", "SandAuto@EnergyReady"])
        counts = {}
        for key in ("Stock", "Ready"):
            read = values.get("SandAuto@Energy" + key, {})
            text = read.get("text", "").strip().replace("O", "0")
            if read.get("score", 0) < 0.85 or not re.fullmatch(r"\d{1,3}", text):
                raise CheckpointError(f"Energy {key} counter was not confirmed")
            counts[key.lower()] = int(text)
        return counts

    def selected_energy(self, path):
        readings = self.rt.ocr(path, [550, 270, 120, 230])
        values = []
        for read in readings:
            text = read.get("text", "").strip().replace("O", "0")
            match = re.fullmatch(r"(\d{1,3})/60", text)
            if read.get("score", 0) >= 0.85 and match:
                values.append(int(match[1]))
        if len(values) != 1:
            raise CheckpointError("Selected ingredient energy was not confirmed")
        return values[0]

    def restore_energy(self, target=2, return_state="SandAuto@Squad"):
        # AUTO selects ingredients only; commit once, after full-trip affordability.
        if target != 2 or return_state not in ("SandAuto@Squad", "SandAuto@World"):
            raise CheckpointError("The bounded recovery target is exactly two drinks")
        path, _ = self.rt.capture("recovery-entry")
        labels = self.rt.ocr(path, [250, 80, 470, 100])
        if not any(canonical(x.get("text", "")) == "energydrink" for x in labels):
            if not self.rt.matches(path, ["SandAuto@Squad"]):
                raise CheckpointError(
                    "Energy recovery requires squad or cooking screen"
                )
            self.rt.click((1004, 680))
            for _ in range(4):
                path, _ = self.rt.capture("recovery-cooking")
                labels = self.rt.ocr(path, [250, 80, 470, 100])
                if any(canonical(x.get("text", "")) == "energydrink" for x in labels):
                    break
                time.sleep(0.5)
            else:
                raise CheckpointError("Energy cooking did not open")
        source = self.rt.matches(
            path, ["SandAuto@EnergyIngredients", "SandAuto@EnergyProvisions"]
        )
        if "SandAuto@EnergyProvisions" in source:
            self.rt.click((1180, 115))
            for _ in range(4):
                path, _ = self.rt.capture("recovery-ingredients")
                if self.rt.matches(path, ["SandAuto@EnergyIngredients"]):
                    break
                time.sleep(0.5)
            else:
                raise CheckpointError("Raw ingredient mode was not confirmed")
        elif "SandAuto@EnergyIngredients" not in source:
            raise CheckpointError("Energy ingredient source was not identified")
        counts = self.energy_counts(path)
        baseline_energy = self.selected_energy(path)
        if counts["ready"] != 0 or not 0 <= baseline_energy < 60:
            raise CheckpointError(
                "Preserve an existing ingredient selection; clear it before recovery"
            )
        if baseline_energy:
            idle = self.rt.matches(path, ["SandAuto@EnergyIdleIngredients"])
            if idle.get("SandAuto@EnergyIdleIngredients", {}).get("score", 0) < 0.98:
                raise CheckpointError(
                    "Partial bottle may contain an unowned ingredient draft; preserve it"
                )
            self.rt.log(
                "stored_energy_observed", energy=baseline_energy, image=str(path)
            )
        for _ in range(target):
            if counts["stock"] + counts["ready"] >= target:
                break
            before = counts.copy()
            self.click_label(path, "AUTO", [900, 540, 90, 65])
            time.sleep(0.5)
            path, _ = self.rt.capture("recovery-preview")
            counts = self.energy_counts(path)
            self.rt.log("energy_preview", **counts, image=str(path))
            if counts == before:
                break
        if counts["stock"] + counts["ready"] < target:
            # Cancel only this method's preview; do not consume the last partial supply.
            self.rt.click((780, 575))
            path, _ = self.rt.capture("recovery-cancelled")
            cleared = self.energy_counts(path)
            if (
                cleared["ready"] != 0
                or cleared["stock"] != counts["stock"]
                or self.selected_energy(path) != baseline_energy
            ):
                raise CheckpointError("Energy preview cancellation was not confirmed")
            raise CheckpointError(
                f"Food covers only {counts['ready']} new drinks; need {target - counts['stock']}; ingredients preserved"
            )
        if counts["ready"]:
            expected = counts["stock"] + counts["ready"]
            if counts["ready"] > target:
                raise CheckpointError("Energy preview exceeds recovery budget")
            self.click_label(path, "Prepare now", [1000, 540, 240, 65])
            for _ in range(4):
                time.sleep(0.5)
                path, _ = self.rt.capture("recovery-reward")
                if any(
                    canonical(x.get("text", "")) == "resourcegained"
                    for x in self.rt.ocr(path, [500, 220, 300, 80])
                ):
                    break
            else:
                raise CheckpointError(
                    "Recovery craft submitted; reward unconfirmed; do not craft again"
                )
            self.rt.click((640, 460))
            for _ in range(4):
                path, _ = self.rt.capture("recovery-stock")
                try:
                    after = self.energy_counts(path)
                except CheckpointError:
                    time.sleep(0.5)
                    continue
                if after["stock"] == expected and after["ready"] == 0:
                    break
                time.sleep(0.5)
            else:
                raise CheckpointError("Recovery stock increase was not confirmed")
            self.rt.log(
                "energy_recovered",
                quantity=counts["ready"],
                stock=after["stock"],
                image=str(path),
            )
        self.rt.task("SandAuto@CookingBack")
        self.wait_for_state(return_state, "recovery-return")

    def prepare_pumps(self, target=1, reserve_wood=0):
        if not hasattr(self, "tool_crafter"):
            self.tool_crafter = ToolCrafter(self.rt, self.rt.pack)
        return self.tool_crafter.prepare_pumps(target, reserve_wood)

    def prepare_hubs(self, target=1, *, observed_hq, reserve_wood=0, reserve_stone=0):
        if not hasattr(self, "tool_crafter"):
            self.tool_crafter = ToolCrafter(self.rt, self.rt.pack)
        return self.tool_crafter.prepare_hubs(
            target,
            observed_hq=observed_hq,
            reserve_wood=reserve_wood,
            reserve_stone=reserve_stone,
        )

    def prepare_campaign_tools(self, state, *, reserve_wood=0, reserve_stone=0):
        from maa_sand_campaign import load_campaign, prepare_campaign_tools

        if not hasattr(self, "tool_crafter"):
            self.tool_crafter = ToolCrafter(self.rt, self.rt.pack)
        return prepare_campaign_tools(
            state,
            self.tool_crafter,
            load_campaign(self.rt.pack),
            reserve_wood=reserve_wood,
            reserve_stone=reserve_stone,
        )

    def prepare_energy(self):
        if getattr(self, "campaign_no_brew", False):
            raise CheckpointError(
                "Campaign trip became unfunded; stop without unplanned ingredient spending"
            )
        # One bounded batch using the game's own ingredient selector. No day skip.
        path, _ = self.rt.capture("energy-dialog")
        if not self.rt.matches(path, ["SandAuto@NoEnergy"]):
            raise CheckpointError("Energy prompt was not confirmed")
        self.rt.click((960, 483))
        path, _ = self.rt.capture("cooking")
        labels = self.rt.ocr(path, [250, 80, 470, 100])
        if not any(canonical(x.get("text", "")) == "energydrink" for x in labels):
            raise CheckpointError("Energy-drink cooking screen did not open")
        reads = self.rt.ocr(path, [550, 270, 120, 230])
        if not any(x.get("text", "") == "60/60" for x in reads):
            self.click_label(path, "AUTO", [900, 540, 90, 65])
            path, _ = self.rt.capture("auto-ingredients")
            reads = self.rt.ocr(path, [550, 270, 120, 230])
        if not any(x.get("text", "") == "60/60" for x in reads):
            raise CheckpointError("Insufficient ingredients for one energy drink")
        self.click_label(path, "Prepare now", [1000, 540, 240, 65])
        path, _ = self.rt.capture("cooked")
        if not any(
            canonical(x.get("text", "")) == "resourcegained"
            for x in self.rt.ocr(path, [500, 220, 300, 80])
        ):
            raise CheckpointError("Energy drink was not confirmed as gained")
        self.rt.click((640, 460))
        self.rt.click((29, 33))
        path, _, states = self.frame("cooking-return")
        if "SandAuto@Squad" not in states:
            raise CheckpointError("Cooking did not return to squad screen")
        self.rt.log("energy_drink_prepared", image=str(path))

    def wait_for_state(self, expected, label):
        for _ in range(4):
            path, image, states = self.frame(label)
            if expected in states:
                return path, image, states
            time.sleep(0.25)
        raise CheckpointError(f"{expected} did not appear at {label}")

    def dismiss_world_hints(self, path):
        for _ in range(4):
            if not self.rt.matches(path, ["SandAuto@WorldHint"]):
                return
            self.rt.task("SandAuto@WorldHint")
            path, _, states = self.frame("world-hint-return")
            if "SandAuto@World" not in states:
                raise CheckpointError("World hint did not return to a verified map")
        raise CheckpointError("World hint sequence exceeded its bounded limit")

    def resolve_campaign_encounter(self, state):
        from maa_sand_encounter import CampaignEncounter

        if not hasattr(self, "encounter_player"):
            self.encounter_player = CampaignEncounter(self.rt, self.rt.pack)
        return self.encounter_player.resolve(state)

    def prepare_campaign_team(self, scope, journal, *, allow_experimental=False):
        """Prepare the route team and skills through resumable helpers; never launch."""
        from maa_sand_team import CampaignTeamPreparer

        return CampaignTeamPreparer(
            self, journal, allow_experimental=allow_experimental
        ).prepare(scope)

    def open_campaign_roster(self, entry_id, journal, *, allow_experimental=False):
        """Open operator selection once, without clearing or confirming the loadout."""
        from maa_sand_formation import RosterEntrySelector

        return RosterEntrySelector(
            self.rt, journal, allow_experimental=allow_experimental, pack=self.rt.pack
        ).open(entry_id)

    def confirm_campaign_roster(
        self, confirmation_id, journal, *, names=None, allow_experimental=False
    ):
        """Confirm operator selection once and verify the exact returned formation."""
        from maa_sand_formation import RosterConfirmationSelector

        return RosterConfirmationSelector(
            self.rt,
            journal,
            self.profile["required_squad"] if names is None else names,
            self.rt.session.install / "resource/battle_data.json",
            allow_experimental=allow_experimental,
            pack=self.rt.pack,
        ).confirm(confirmation_id)

    def select_visible_campaign_actor(
        self, character_id, selection_id, journal, *, allow_experimental=False
    ):
        """One explicit journaled roster action; never commits a formation or launches an Act."""
        from maa_sand_formation import RosterSelector

        return RosterSelector(
            self.rt, journal, allow_experimental=allow_experimental, pack=self.rt.pack
        ).select_visible(character_id, selection_id)

    def select_visible_campaign_role(
        self, role, selection_id, journal, *, allow_experimental=False
    ):
        """Select one visible class filter during preparation; no squad confirmation or launch."""
        from maa_sand_formation import RosterRoleSelector

        return RosterRoleSelector(
            self.rt, journal, allow_experimental=allow_experimental, pack=self.rt.pack
        ).select_visible_role(role, selection_id)

    def find_campaign_roster_actor(
        self,
        character_id,
        role,
        *,
        allow_experimental=False,
        maximum_pages=12,
        maximum_rewinds=12,
    ):
        """Find an actor in an already selected class, without selecting or launching."""
        from maa_sand_formation import RosterSearcher

        return RosterSearcher(
            self.rt, allow_experimental=allow_experimental, pack=self.rt.pack
        ).seek(
            character_id,
            role,
            maximum_pages=maximum_pages,
            maximum_rewinds=maximum_rewinds,
        )

    def prepare_requested_campaign_actors(
        self, scope, journal, *, names=None, allow_experimental=False
    ):
        """Prepare requested operators before DayRunner; exact formation/skills/tools remain separate."""
        from maa_sand_squad import RequestedActorsPreparer

        return RequestedActorsPreparer(
            self.rt,
            journal,
            self.rt.session.install / "resource/battle_data.json",
            allow_experimental=allow_experimental,
            pack=self.rt.pack,
        ).prepare(self.profile["required_squad"] if names is None else names, scope)

    def verify_requested_campaign_squad(self, path, *, names=None):
        """Read the exact final squad; skill and tool checks remain separate."""
        from maa_sand_squad import verify_exact_squad

        return verify_exact_squad(
            self.rt,
            path,
            self.profile["required_squad"] if names is None else names,
            self.rt.session.install / "resource/battle_data.json",
        )

    def select_campaign_skill(
        self,
        name,
        skill,
        selection_id,
        journal,
        *,
        names=None,
        allow_experimental=False,
    ):
        """Set one unlocked final-formation skill without starting an expedition."""
        from maa_sand_squad import FormationSkillSelector

        return FormationSkillSelector(
            self.rt,
            journal,
            self.profile["required_squad"] if names is None else names,
            name,
            skill,
            self.rt.session.install / "resource/battle_data.json",
            minimum_rank=(
                self.profile.get("required_formation_ranks", {}).get(name)
                if self.profile.get("required_formation_skills", {}).get(name) == skill
                else None
            ),
            allow_experimental=allow_experimental,
            pack=self.rt.pack,
        ).select_skill(selection_id)

    def prepare_required_campaign_skills(
        self, scope, journal, *, allow_experimental=False
    ):
        """Set route skill requirements and verify their final ranks without launching."""
        from maa_sand_config import validate_formation_skills
        from maa_sand_navigation import CampaignNavigator

        if (
            allow_experimental is not True
            or not isinstance(scope, str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,40}", scope) is None
        ):
            raise CheckpointError(
                "Skill preparation requires experimental execution and a stable scope ID"
            )
        requirements = self.profile.get("required_formation_skills", {})
        validate_formation_skills(
            requirements,
            self.profile["required_squad"],
            self.profile.get("required_formation_ranks", {}),
        )
        selections = [
            self.select_campaign_skill(
                name, skill, f"{scope}:skill:{index}", journal, allow_experimental=True
            )
            for index, (name, skill) in enumerate(requirements.items())
        ]
        path, _states = CampaignNavigator(self.rt, self.rt.pack).frame(
            "campaign-skills-prepared"
        )
        proof = self.verify_required_campaign_skills(path)
        return {
            "status": "required_skills_prepared",
            "selections": selections,
            "verification": proof,
            "expedition_started": False,
        }

    def verify_required_campaign_skills(self, path, *, names=None):
        """Observe supported route skill selections without changing them."""
        from maa_sand_squad import verify_formation_skills

        return verify_formation_skills(
            self.rt,
            path,
            self.profile["required_squad"] if names is None else names,
            self.profile.get("required_formation_skills", {}),
            self.rt.session.install / "resource/battle_data.json",
            minimum_ranks=self.profile.get("required_formation_ranks", {}),
        )

    def verify_campaign_power(self, path, *, names=None):
        """Verify guide levels and promotion lower bounds on the current formation."""
        from maa_sand_squad import verify_formation_power

        return verify_formation_power(
            self.rt,
            path,
            self.profile["required_squad"] if names is None else names,
            self.profile.get("required_formation_levels", {}),
            self.profile.get("required_formation_elites", {}),
            self.profile.get("required_formation_skills", {}),
            self.rt.session.install / "resource/battle_data.json",
            self.rt.pack,
        )

    def prepare_campaign_formation(self, state, *, request_tools=True):
        from maa_sand_navigation import CampaignNavigator

        return CampaignNavigator(self.rt, self.rt.pack).prepare_next(
            state, request_tools=request_tools
        )

    def visit_campaign_liaison(self, state):
        from maa_sand_visit import LiaisonVisit

        if not hasattr(self, "liaison_visit"):
            self.liaison_visit = LiaisonVisit(self)
        return self.liaison_visit.run(state)

    def prepare_empty_campaign_squad(self, state):
        from maa_sand_navigation import CampaignNavigator

        if not hasattr(self, "campaign_navigator"):
            self.campaign_navigator = CampaignNavigator(self.rt, self.rt.pack)
        return self.campaign_navigator.prepare_empty_next(state)

    def prepare_squad(self):
        if self.profile.get("squad_mode") == "empty-pumps":
            state = getattr(self, "campaign_state", None)
            if state is None:
                raise CheckpointError(
                    "Empty-pump route requires the observed Day6 campaign Act"
                )
            result = self.prepare_empty_campaign_squad(state)
            return Path(result["formation_image"])
        if self.profile["stage"] != "Shrubbery Galore":
            from maa_sand_navigation import CampaignNavigator

            result = CampaignNavigator(self.rt, self.rt.pack).prepare_formation(
                self.profile["stage_id"]
            )
            return Path(result["formation_image"])
        path, _, states = self.frame("entry")
        if "SandAuto@Headquarters" in states:
            self.rt.task("SandPilot@Back")
            path, _, states = self.frame("headquarters-back")
            if "SandAuto@World" not in states:
                raise CheckpointError("Headquarters Back did not confirm the world map")
        if "SandAuto@World" in states:
            self.dismiss_world_hints(path)
        from maa_sand_navigation import CampaignNavigator

        stage_id = getattr(self, "profile", {}).get("stage_id", "sandbox_1_01")
        result = CampaignNavigator(self.rt, self.rt.pack).prepare_formation(stage_id)
        return Path(result["formation_image"])

    def validate_squad(self, path):
        if self.profile.get("squad_mode") == "empty-pumps":
            tasks = [f"SandAuto@EmptySquadSlot{i}" for i in range(1, 8)]
            hits = self.rt.matches(path, tasks)
            if not all(hits.get(task, {}).get("score", 0) >= 0.9 for task in tasks):
                raise CheckpointError(
                    "All seven empty operator slots must be verified before launch"
                )
            return
        names = canonical(
            " ".join(x.get("text", "") for x in self.rt.ocr(path, [260, 70, 850, 570]))
        )
        missing = [
            name
            for name in self.profile["required_squad"]
            if canonical(name) not in names
        ]
        if missing:
            # Tight native recognition excludes steam glyphs merged with card titles.
            crops = self.rt.matches(
                path, [f"SandAuto@SquadName{i}" for i in range(1, 9)]
            )
            recognized = {
                canonical(x.get("text", ""))
                for x in crops.values()
                if x.get("score", 0) >= 0.85
            }
            if "Młynar" in missing:
                skill = self.rt.matches(path, ["SandAuto@SquadMlynarSelectedS3"]).get(
                    "SandAuto@SquadMlynarSelectedS3", {}
                )
                icon = skill.get("rect", [])
                for card in crops.values():
                    rect = card.get("rect", [])
                    if (
                        card.get("score", 0) >= 0.85
                        and canonical(card.get("text", ""))
                        in {"mlynar", "mtynar", "miynar"}
                        and skill.get("score", 0) >= 0.95
                        and len(rect) == len(icon) == 4
                        and abs(icon[0] - (rect[0] + 193)) <= 3
                        and abs(icon[1] - (rect[1] + 36)) <= 3
                    ):
                        recognized.add(canonical("Młynar"))
            missing = [name for name in missing if canonical(name) not in recognized]
        if missing:
            raise CheckpointError(
                f"The selected gathering squad is missing {missing[0]}"
            )

    def navigate(self):
        path = self.prepare_squad()
        self.validate_squad(path)
        if getattr(self, "before_launch", None) is not None:
            self.before_launch(path)
        return self._launch_formation()

    def launch_prepared(self, receipt):
        """Launch a named prepared formation using captured frames, then stop paused."""
        if (
            self.in_battle
            or getattr(self, "prepared_launch_pending", False)
            or not isinstance(receipt, dict)
            or receipt.get("status") != "named_formation_prepared"
            or receipt.get("stage_id") != self.profile["stage_id"]
            or receipt.get("battle_started") is not False
            or not receipt.get("formation_image")
        ):
            raise CheckpointError(
                "A matching prepared formation and no unresolved launch are required"
            )
        path, _, states = self.frame("prepared-launch-before")
        if "SandAuto@Squad" not in states:
            raise CheckpointError(
                "Prepared launch requires the current formation screen"
            )
        self.validate_squad(path)
        self.prepared_launch_pending = True
        # An uncertain launch stays pending; never repeat its paid Start blindly.
        result = self._launch_formation()
        self.prepared_launch_pending = False
        return result

    def _launch_formation(self):
        """Shared launch loop observes the configured capture backend during loading."""
        empty_confirmation = False
        for attempt in range(4):
            self.rt.task("SandPilot@SquadStart")
            end = time.monotonic() + 45
            while time.monotonic() < end:
                path, _, states = self.frame("loading")
                if self.profile.get("squad_mode") == "empty-pumps":
                    hits = self.rt.matches(path, ["SandAuto@VisitStartConfirm"])
                    if (
                        hits.get("SandAuto@VisitStartConfirm", {}).get("score", 0)
                        >= 0.9
                    ):
                        if empty_confirmation:
                            raise CheckpointError(
                                "Empty-squad confirmation repeated; do not submit again"
                            )
                        empty_confirmation = True
                        self.rt.task("SandPilot@VisitStartConfirm")
                        continue
                if "SandAuto@NoEnergy" in states:
                    if attempt >= 3:
                        raise CheckpointError(
                            "Squad still requires energy after three batches"
                        )
                    self.prepare_energy()
                    break
                if "SandAuto@Battle" in states:
                    self.in_battle = True
                    self.pause(True)
                    if getattr(self, "raid_mode", False):
                        raise CheckpointError(
                            "Raid battle preserved paused; harvesting route is not applicable"
                        )
                    return
                time.sleep(0.5)
            else:
                raise CheckpointError("Gathering battle did not start")

    def wait_until_remaining(self, remaining, maximum_game_seconds):
        """Let hub gatherers work using actual game-clock reads and bounded pause windows."""
        if (
            type(remaining) is not int
            or not 25 <= remaining <= 180
            or type(maximum_game_seconds) is not int
            or not 1 <= maximum_game_seconds <= 180
            or getattr(self, "raid_mode", False)
        ):
            raise CheckpointError(
                "Passive harvest wait requires a bounded gathering policy"
            )
        self.pause(True)
        start = previous = None
        for _ in range(61):
            path, _, _ = self.frame("passive-harvest-clock")
            current = self.remaining(path)
            if current < 25:
                raise CheckpointError("Harvest exit reserve already exhausted")
            if start is None:
                start = current
            elif current >= previous:
                raise CheckpointError(
                    "Harvest clock stalled or increased after bounded advance"
                )
            if current <= remaining:
                return {
                    "remaining": current,
                    "elapsed_game_seconds": start - current,
                    "paused": True,
                }
            elapsed = start - current
            if elapsed >= maximum_game_seconds:
                raise CheckpointError(
                    "Passive harvesting exceeded its observed game-time budget"
                )
            previous = current
            seconds = min(
                5, (current - remaining) / 2, (maximum_game_seconds - elapsed) / 2
            )
            if seconds < 0.5:
                raise CheckpointError("No bounded harvest interval remains")
            self.advance(seconds)
        raise CheckpointError("Passive harvest wait exceeded its poll limit")

    def wait_for_water(self, pumps=2, *, maximum_game_seconds=180, remaining_floor=25):
        from maa_sand_bag import WaterHarvestMonitor

        self.water_target = None
        from maa_sand_config import WATER_STAGES

        stage_id = self.profile.get("stage_id")
        if (
            stage_id not in WATER_STAGES
            or self.profile.get("stage") != WATER_STAGES[stage_id]
            or (stage_id == "sandbox_1_40" and pumps != 1)
        ):
            raise CheckpointError(
                "Guide water completion requires a reviewed named pump operation"
            )
        if not hasattr(self, "water_monitor"):
            self.water_monitor = WaterHarvestMonitor(self)
        self.water_target = self.water_monitor.wait(
            pumps,
            maximum_game_seconds=maximum_game_seconds,
            remaining_floor=remaining_floor,
        )
        self.water_target.update(stage_id=stage_id, stage=self.profile["stage"])
        self.rt.log("water_target_observed", **self.water_target)
        return self.water_target

    def wait_for_hunting(
        self,
        pumps=1,
        *,
        minimum_base_energy=80,
        maximum_game_seconds=180,
        remaining_floor=25,
    ):
        from maa_sand_bag import HuntingHarvestMonitor

        if (
            self.profile.get("stage_id") != "sandbox_1_56"
            or self.profile.get("stage") != "Straight Into the Abyss"
        ):
            raise CheckpointError(
                "Hunting completion requires the reviewed Abyss operation"
            )
        self.hunting_target = self.water_target = None
        if getattr(getattr(self, "hunting_monitor", None), "pending", False):
            raise CheckpointError(
                "Previous hunting bag toggle is unresolved; preserve the existing monitor"
            )
        self.hunting_monitor = HuntingHarvestMonitor(self, minimum_base_energy)
        target = self.hunting_monitor.wait(
            pumps,
            maximum_game_seconds=maximum_game_seconds,
            remaining_floor=remaining_floor,
        )
        target.update(stage_id=self.profile["stage_id"], stage=self.profile["stage"])
        self.hunting_target = self.water_target = target
        self.rt.log("hunting_target_observed", **target)
        return target

    def verify_hunting_settlement(self):
        from maa_sand_food import verify_hunting_food

        target = getattr(self, "hunting_target", None)
        if target is None:
            return
        self.hunting_completion = verify_hunting_food(
            self.settlement,
            target["target_base_food_energy"],
            expected_stage=target["stage"],
        )
        self.rt.log("hunting_target_settled", **self.hunting_completion)
        if not self.hunting_completion["food_reward_verified"]:
            raise CheckpointError(
                "Hunting bag target does not substitute for sufficient delivered food; preserve result for review"
            )

    def finish(self, *, stage=None):
        stage = self.profile["stage"] if stage is None else stage
        self.close_panel()
        self.pause(False)
        self.rt.task("SandPilot@LeaveCamp")
        end = time.monotonic() + 35
        while time.monotonic() < end:
            path, _, states = self.frame("settlement")
            if "SandAuto@Battle" in states and "SandAuto@EndConfirm" not in states:
                self.in_battle = True
                self.pause(True)
                raise CheckpointError(
                    "Exit did not reach settlement; field preserved paused, exit not repeated"
                )
            if "SandAuto@Result" in states:
                self.in_battle = False
                self.settlement = read_rewards(self.rt, path, stage)
                self.rt.log("settlement_rewards", **self.settlement)
                self.verify_wood_settlement()
                if getattr(self, "water_target", None) is not None:
                    from maa_sand_bag import verify_water_settlement

                    self.water_completion = verify_water_settlement(
                        self.water_target, self.settlement
                    )
                    self.rt.log("water_target_settled", **self.water_completion)
                self.verify_hunting_settlement()
                self.rt.log(
                    "expedition_result", image=str(path), banked=self.policy.banked
                )
                self.rt.task("SandPilot@GatherResult")
                for _ in range(10):
                    checkpoint, _, after = self.frame("returned-world")
                    if "SandAuto@World" in after:
                        self.world_return_image = str(checkpoint)
                        try:
                            self.world_observation = read_world(self.rt, checkpoint)
                            self.rt.log("world_hud_observed", **self.world_observation)
                        except CheckpointError as error:
                            self.world_observation = None
                            self.rt.log(
                                "world_hud_unavailable",
                                reason=str(error),
                                image=str(checkpoint),
                            )
                        self.rt.log("world_return_verified", image=str(checkpoint))
                        return
                    time.sleep(0.5)
                raise CheckpointError(
                    "Settlement collected but world-map return not confirmed"
                )
            time.sleep(0.5)
        raise CheckpointError("No verified expedition settlement")

    def play(self):
        self.navigate()
        self.gather()

    def gather(self):
        self.pause(True)
        if getattr(self, "raid_mode", False):
            raise CheckpointError(
                "Raid battle preserved paused; no gathering route will run"
            )
        loads = {}
        for index, step in enumerate(self.profile["steps"]):
            self.rt.log("route_step", route=self.profile["id"], index=index, **step)
            action = step["action"]
            if action == "phase":
                self.refresh_calibration(phase=step["name"])
            elif action == "wait_dp":
                while True:
                    path, _, _ = self.frame("wait-dp")
                    hand = self.rt.analyze(path, "battle_deployment")
                    if hand.get("dp", -1) >= step["minimum"]:
                        break
                    if self.remaining(path) < step["remaining_floor"]:
                        raise CheckpointError("Insufficient early DP for this route")
                    self.advance(4)
            elif action == "carrier_trip":
                self.carrier_trip(
                    step["name"],
                    step["slot"],
                    step["direction"],
                    step["minimum"],
                    step["timeout"],
                )
            elif action == "wait_operator":
                self.wait_operator_ready(
                    step["name"], step["maximum_game_seconds"], step["remaining_floor"]
                )
            elif action == "wait_until_remaining":
                self.wait_until_remaining(
                    step["remaining"], step["maximum_game_seconds"]
                )
            elif action == "wait_water":
                self.wait_for_water(
                    step["pumps"],
                    maximum_game_seconds=step["maximum_game_seconds"],
                    remaining_floor=step["remaining_floor"],
                )
            elif action == "wait_hunting":
                self.wait_for_hunting(
                    step["pumps"],
                    minimum_base_energy=step["minimum_base_energy"],
                    maximum_game_seconds=step["maximum_game_seconds"],
                    remaining_floor=step["remaining_floor"],
                )
            elif action == "deploy_tool":
                self.deploy_tool(
                    step["item_id"],
                    step["slot"],
                    step["direction"],
                    maximum=step["maximum"],
                )
            elif action == "deploy":
                self.deploy(step["name"], step["slot"], step["direction"])
            elif action == "collect":
                loads[step["slot"]] = self.wait_load(
                    step["name"],
                    step["slot"],
                    step["minimum"],
                    skill=step["skill_once"],
                    timeout=step["timeout"],
                )
            elif action == "maintain_skills":
                self.maintain_skills(
                    step["skills"], step["duration"], step["remaining_floor"]
                )
            elif action == "recall":
                self.recall(step["name"], step["slot"])
            elif action == "bank":
                self.retreat(loads.pop(step["slot"]), step["slot"])
            elif action == "finish":
                self.finish()
        self.rt.log("completed", wood_banked=self.policy.banked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    bundled_runtime = Path(__file__).resolve().parents[1] / "runtime"
    parser.add_argument(
        "--runtime",
        type=Path,
        default=(
            bundled_runtime
            if bundled_runtime.is_dir()
            else Path.home() / "MAA-build/source/build/bin/Debug"
        ),
    )
    parser.add_argument("--pack", type=Path, default=PACK)
    parser.add_argument(
        "--capture-backend",
        choices=["native", "adb"],
        default="adb",
        help="Use ADB screenshots with native MAA recognition and input",
    )
    parser.add_argument("--route")
    parser.add_argument(
        "--raid-profile",
        type=Path,
        help="Use a calibrated raid profile for battle takeover or --campaign-act interception",
    )
    parser.add_argument("--raid-run-id", help="Unique ID for this observed raid battle")
    parser.add_argument(
        "--prepare-team",
        action="store_true",
        help="Prepare only the route team and skills from formation; no expedition launch",
    )
    parser.add_argument(
        "--team-plan",
        type=Path,
        help="Formation-only plan for --prepare-team; no combat anchors or launch",
    )
    parser.add_argument(
        "--team-scope", help="Stable preparation action scope, up to24 ASCII characters"
    )
    parser.add_argument(
        "--team-run-id",
        help="Campaign ID owning the persistent team-preparation journal",
    )
    parser.add_argument(
        "--advance-day",
        action="store_true",
        help="Run or resume one journaled exhausted-day transition",
    )
    parser.add_argument(
        "--camp-intro",
        action="store_true",
        help="Run or resume the exact fresh-camp introduction",
    )
    parser.add_argument(
        "--intro-run-id",
        help="Unique fresh campaign ID for introduction journal ownership",
    )
    parser.add_argument(
        "--base-npc",
        action="store_true",
        help="Run the exact first base NPC dialogue or resume an owned world return",
    )
    parser.add_argument(
        "--prepare-planter",
        action="store_true",
        help="Prepare one extra Planting Box Group in stock; placement is separate",
    )
    parser.add_argument(
        "--upgrade-hq2",
        action="store_true",
        help="Run one journaled HQ1-to-HQ2 upgrade",
    )
    parser.add_argument(
        "--campaign-act", action="store_true", help="Execute one journaled Day 1–6 Act"
    )
    parser.add_argument(
        "--journal",
        type=Path,
        help="Persistent campaign, raid, or construction journal",
    )
    parser.add_argument(
        "--visit-liaison",
        action="store_true",
        help="Run the reviewed Day4 empty-squad visit",
    )
    parser.add_argument(
        "--campaign-state",
        type=Path,
        help="Observed campaign state for an Act, Liaison visit, or HQ upgrade",
    )
    parser.add_argument("--allow-experimental", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration and calibration without connecting",
    )
    parser.add_argument(
        "--assets", type=Path, help="Override this route camera asset directory"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute the selected supported operation",
    )
    args = parser.parse_args()
    if args.prepare_team:
        from maa_sand_team import run_team_cli

        return run_team_cli(args, parser, MaaRuntime)
    if args.team_plan is not None:
        parser.error("--team-plan requires --prepare-team")
    if args.team_scope is not None or args.team_run_id is not None:
        parser.error("--team-scope and --team-run-id require --prepare-team")
    if args.advance_day:
        if any(
            (
                args.camp_intro,
                args.base_npc,
                args.prepare_planter,
                args.upgrade_hq2,
                args.campaign_act,
                args.visit_liaison,
                args.raid_profile is not None,
            )
        ):
            parser.error("Select only one day-transition or campaign activity")
        from maa_sand_day_transition import run_day_transition_cli

        return run_day_transition_cli(args, parser, MaaRuntime)
    if args.intro_run_id and not args.camp_intro:
        parser.error("--intro-run-id requires --camp-intro")
    if (
        sum((args.upgrade_hq2, args.prepare_planter, args.base_npc, args.camp_intro))
        > 1
    ):
        parser.error("Select one construction mode at a time")
    if args.camp_intro:
        from maa_sand_intro import run_intro_cli

        return run_intro_cli(args, parser, MaaRuntime)
    if args.base_npc:
        from maa_sand_base_npc import run_base_npc_cli

        return run_base_npc_cli(args, parser, MaaRuntime)
    if args.prepare_planter:
        from maa_sand_planter import run_planter_cli

        return run_planter_cli(args, parser, MaaRuntime)
    if args.upgrade_hq2:
        from maa_sand_construction import run_hq_cli

        return run_hq_cli(args, parser, MaaRuntime)
    if args.raid_profile is not None and (args.visit_liaison or args.route is not None):
        parser.error("--raid-profile cannot combine visit or gathering route modes")
    if (
        args.raid_profile is not None
        and args.execute
        and not args.check
        and not args.campaign_act
        and (args.journal is None or not args.raid_run_id)
    ):
        parser.error("Raid execution requires --journal and --raid-run-id")
    if args.raid_run_id is not None and args.raid_profile is None:
        parser.error("--raid-run-id requires --raid-profile")
    if args.campaign_act and (
        args.visit_liaison or args.campaign_state is None or args.journal is None
    ):
        parser.error(
            "--campaign-act requires --campaign-state and --journal; cannot combine --visit-liaison"
        )
    if args.journal is not None and not (
        args.campaign_act or args.raid_profile is not None
    ):
        parser.error("--journal requires --campaign-act or --raid-profile")
    if args.visit_liaison and (args.campaign_state is None or args.route is not None):
        parser.error(
            "--visit-liaison requires --campaign-state and cannot select a battle --route"
        )
    if args.campaign_state is not None and not (
        args.visit_liaison or args.campaign_act
    ):
        parser.error("--campaign-state requires --visit-liaison or --campaign-act")
    visit_state = visit_review = campaign_state = campaign_review = None
    try:
        if args.raid_profile is not None:
            from maa_sand_raid import load_raid_profile

            profile = load_raid_profile(args.raid_profile, args.pack)
        else:
            profile = load_profile(args.pack, args.route)
        args.assets = args.assets or Path(anchor_spec(args.pack, profile)["location"])
        verify_anchors(args.pack, args.assets, profile)
        if args.visit_liaison:
            from maa_sand_visit import review_visit

            visit_state = json.loads(
                args.campaign_state.read_text(encoding="utf-8-sig")
            )
            visit_review, visit_advice = review_visit(
                visit_state, args.pack, check_only=True
            )
        if args.campaign_act:
            from maa_sand_days import review_act

            campaign_state = json.loads(
                args.campaign_state.read_text(encoding="utf-8-sig")
            )
            campaign_review, campaign_contract = review_act(campaign_state, args.pack)
            if (
                campaign_review["next"]["objective"]
                not in ("talk", "encounter", "raid")
                and args.route is None
            ):
                raise CheckpointError(
                    "Campaign gathering requires an explicit calibrated --route"
                )
        if args.check or not args.execute:
            summary = {
                "route": profile["id"],
                "autoplay_enabled": profile["autoplay_enabled"],
                "status": profile["validation_status"],
                "anchors": "verified",
                "game_connected": False,
            }
            if args.visit_liaison:
                summary.pop("route", None)
                summary.pop("anchors", None)
                summary.update(
                    activity="liaison-first-contact",
                    stage=visit_review["stage"],
                    stage_id=visit_review["stage_id"],
                    autoplay_enabled=False,
                    status="offline_visit_plan_checked",
                    blockers=visit_advice["blockers"],
                    fresh_world_and_formation_required=True,
                )
            if args.raid_profile is not None:
                summary.update(
                    activity="raid-act" if args.campaign_act else "raid-combat",
                    enemy_count=profile["enemy_count"],
                    campaign_launch_enabled=args.campaign_act,
                    result_collection_enabled=profile.get(
                        "result_collection_enabled", False
                    ),
                )
            if args.campaign_act:
                summary.update(
                    activity="campaign-act",
                    advice=campaign_review,
                    execution_contract=campaign_contract,
                )
            print(json.dumps(summary, indent=2))
            return
        if args.campaign_act:
            if not args.allow_experimental or campaign_review["blockers"]:
                raise CheckpointError(
                    "Campaign requires --allow-experimental and resolved state blockers: "
                    + "; ".join(campaign_review["blockers"])
                )
        elif args.visit_liaison:
            if not args.allow_experimental:
                raise CheckpointError(
                    "Liaison visit is experimental; use --allow-experimental for bounded validation"
                )
            review_visit(visit_state, args.pack)
        else:
            require_executable(profile, args.allow_experimental)
    except (CheckpointError, OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path(r"I:\MAA-data\sand-player\runs") / stamp
    if output.drive.upper() == "C:":
        parser.error("Player logs and images must remain off C:")
    with MaaRuntime(
        args.runtime, output, args.pack, capture_backend=args.capture_backend
    ) as runtime:
        player = SandPlayer(runtime, args.assets, profile)
        try:
            if args.raid_profile is not None and not args.campaign_act:
                from maa_sand_raid import RaidExecutor

                result = RaidExecutor(
                    player, profile, args.journal, args.raid_run_id
                ).run()
                runtime.log("raid_battle_checkpoint", **result)
            elif args.campaign_act:
                from maa_sand_days import ActJournal, DayRunner, NativeDayBackend
                from maa_sand_equipment import ToolLoadoutVerifier

                backend = NativeDayBackend(
                    player,
                    allow_experimental=args.allow_experimental,
                    verify_equipment=ToolLoadoutVerifier(runtime),
                    campaign_journal=args.journal,
                )
                journal = ActJournal(args.journal, campaign_state.get("campaign_id"))
                result = DayRunner(backend, journal, args.pack).run_act(campaign_state)
                runtime.log("campaign_act_result", **result)
                if result["status"] != "verified":
                    raise CheckpointError(
                        "Act consumed but outcome needs review; inspect the journal"
                    )
            elif args.visit_liaison:
                player.visit_campaign_liaison(visit_state)
            else:
                player.play()
        except (Exception, KeyboardInterrupt) as exc:
            runtime.log("checkpoint_stop", reason=str(exc))
            try:
                path, _, states = player.frame("stopped")
                if "SandAuto@Battle" in states:
                    player.pause(True)
                runtime.log("checkpoint_saved", image=str(path))
            except Exception as stop_error:  # noqa: BLE001 - log any failure to secure the paused checkpoint
                runtime.log("pause_not_confirmed", reason=str(stop_error))
            raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
