"""Read selected formation tool cards; never equate workbench stock with equipped tools."""

import re

from maa_sand_config import CheckpointError
from maa_sand_settlement import enlarged_count

TOOLS = {"Pump": "Crabbie Pumpie", "Hub": "Sawing Harvester Hub"}


def exact_number(reads, expected=None):
    values = []
    for read in reads:
        text = read.get("text", "").strip()
        if not text:
            continue
        if read.get("score", 0) < 0.85 or re.fullmatch(r"[1-9][0-9]?", text) is None:
            raise CheckpointError(
                "Equipped quantity/ordinal requires exact confident digits"
            )
        values.append(int(text))
    if len(values) != 1 or (expected is not None and values[0] != expected):
        raise CheckpointError(
            "Selected tool quantity/ordinal is missing, ambiguous or different"
        )
    return values[0]


def read_quantity(runtime, path, roi):
    reads = runtime.ocr(path, roi)
    prepared = None
    try:
        value = exact_number(reads)
    except CheckpointError:
        # Saved native replay verifies this numeral-only subcrop avoids badge-edge contamination.
        tight = [roi[0] + 8, roi[1] + 3, 22, 24]
        prepared, larger = enlarged_count(path, tight)
        reads = runtime.ocr(prepared, larger)
        value = exact_number(reads)
    return value, reads, str(prepared) if prepared else None


def rectangle(hit, slot, shape):
    rect = hit.get("rect", [])
    if (
        hit.get("score", 0) < 0.95
        or len(rect) != 4
        or any(type(v) is not int for v in rect)
    ):
        raise CheckpointError(
            "Equipped-tool evidence needs a confident native rectangle"
        )
    x, y, w, h = rect
    top = 80 + 140 * (slot - 1)
    if (w, h) != shape or not (
        920 <= x and x + w <= 1280 and top <= y and y + h <= top + 130
    ):
        raise CheckpointError(
            "Selected tool card lies outside its reviewed formation row"
        )
    return rect


def bounded_roi(x, y, w, h):
    if not (0 <= x and 0 <= y and x + w <= 1280 and y + h <= 720):
        raise CheckpointError(
            "Equipped-tool quantity is clipped; a partial card cannot prove the loadout"
        )
    return [x, y, w, h]


def read_tool_cards(runtime, path):
    """Component observer only. English formation identity is checked separately."""
    tasks = [
        f"SandAuto@Equipped{kind}{slot}"
        for slot in range(1, 4)
        for kind in (*TOOLS, "Empty")
    ]
    hits = runtime.matches(path, tasks)
    counts = {}
    evidence = []
    for slot in range(1, 4):
        identities = [
            kind
            for kind in TOOLS
            if hits.get(f"SandAuto@Equipped{kind}{slot}", {}).get("score", 0) >= 0.95
        ]
        empty = hits.get(f"SandAuto@EquippedEmpty{slot}")
        if empty and empty.get("score", 0) >= 0.95:
            if identities:
                raise CheckpointError(
                    "Conflicting tool and empty-slot identities in the selected loadout"
                )
            x, y, _w, _h = rectangle(empty, slot, (57, 57))
            ordinal_roi = bounded_roi(x - 70, y - 15, 58, 75)
            ordinal_reads = runtime.ocr(path, ordinal_roi)
            exact_number(ordinal_reads, slot)
            capacity_roi = bounded_roi(x - 74, y + 60, 72, 25)
            capacity_reads = runtime.ocr(path, capacity_roi)
            capacity = [r for r in capacity_reads if r.get("text", "").strip()]
            if (
                len(capacity) != 1
                or capacity[0].get("score", 0) < 0.85
                or re.fullmatch(r"\s*/\s*12\s*", capacity[0].get("text", "")) is None
            ):
                raise CheckpointError(
                    "Next empty tool slot must show the actual /12 capacity"
                )
            if any(
                hits.get(f"SandAuto@Equipped{kind}{later}", {}).get("score", 0) >= 0.95
                for later in range(slot + 1, 4)
                for kind in TOOLS
            ):
                raise CheckpointError(
                    "Noncontiguous selected tool cards contradict the empty-prefix proof"
                )
            evidence.append(
                {
                    "slot": slot,
                    "empty": empty,
                    "ordinal_reads": ordinal_reads,
                    "capacity_reads": capacity_reads,
                }
            )
            return {
                "status": "selected_tool_cards_observed",
                "image": str(path),
                "counts": counts,
                "next_empty_slot": slot,
                "evidence": evidence,
                "formation_verified": False,
                "inventory_updated": False,
                "inputs_issued": False,
            }
        if len(identities) != 1 or slot == 3:
            raise CheckpointError(
                "Complete selected tool prefix and next empty slot are required; unknown cards are not empty"
            )
        kind = identities[0]
        name = TOOLS[kind]
        if name in counts:
            raise CheckpointError(
                "Repeated tool cards require separate reviewed layout support"
            )
        icon = hits[f"SandAuto@Equipped{kind}{slot}"]
        x, y, _w, _h = rectangle(icon, slot, (58, 56))
        roi = bounded_roi(x + 62, y + (39 if kind == "Pump" else 63), 42, 29)
        count, reads, prepared = read_quantity(runtime, path, roi)
        if count not in (1, 2):
            raise CheckpointError(
                "Guide loadouts support one or two of each selected tool only"
            )
        counts[name] = count
        evidence.append(
            {
                "slot": slot,
                "name": name,
                "icon": icon,
                "quantity_roi": roi,
                "quantity_reads": reads,
                "prepared_image": prepared,
            }
        )
    raise CheckpointError("Selected tool prefix has no verified end")


class ToolLoadoutVerifier:
    """Read-only callback for the existing same-frame campaign launch hook."""

    def __init__(self, runtime):
        self.rt = runtime

    def __call__(self, path, required):
        if (
            not isinstance(required, dict)
            or not required
            or any(
                name not in TOOLS.values()
                or type(value) is not int
                or value not in (1, 2)
                for name, value in required.items()
            )
        ):
            raise CheckpointError(
                "Equipped-tool proof requires the reviewed nonempty pump/hub loadout"
            )
        hits = self.rt.matches(path, ["SandAuto@Squad"])
        if hits.get("SandAuto@Squad", {}).get("score", 0) < 0.85:
            raise CheckpointError(
                "Equipped-tool proof requires the actual English formation screen"
            )
        observation = read_tool_cards(self.rt, path)
        if observation["counts"] != required:
            raise CheckpointError(
                "Actual equipped quantities differ from the complete campaign loadout"
            )
        return {
            **observation,
            "verified": True,
            "formation_verified": True,
            "required": dict(required),
        }
