"""Read identified reward counts with existing native match/OCR callbacks."""

import re
import unicodedata
from pathlib import Path

from maa_sand_config import CheckpointError

ITEMS = {
    "Wood": "wood",
    "Water": "water",
    "Gold": "gold",
    "Wing": "fowlbeast_wing",
    "WildPlant": "wild_plant",
    "Tenderloin": "puffball_tenderloin",
}


def text_key(text):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", text)).casefold()


def quantity(reads):
    values = []
    for read in reads:
        match = re.fullmatch(r"\s*\+\s*(\d{1,3})\s*", read.get("text", ""))
        if match and read.get("score", 0) >= 0.85 and int(match[1]) > 0:
            values.append(int(match[1]))
    if len(values) != 1:
        raise CheckpointError(
            "Reward quantity requires one confident explicit +N reading"
        )
    return values[0]


def count_roi(match, *, wide=False):
    x, y, w, _h = match["rect"]
    center = x + w / 2
    slot = round((center - 103) / 104)
    if (
        not 0 <= slot <= 5
        or abs(center - (103 + 104 * slot)) > 18
        or not 530 <= y <= 565
    ):
        raise CheckpointError("Reward icon is outside the verified item row")
    return slot, (
        [108 + 104 * slot, 606, 60, 30] if wide else [128 + 104 * slot, 608, 32, 26]
    )


def enlarged_count(path, roi):
    """Magnify the identified counter for the same native OCR, never infer digits."""
    import cv2
    import numpy as np

    image = cv2.imread(str(path))
    if image is None:
        raise CheckpointError("Reward evidence image is unreadable")
    image = cv2.resize(image, (1280, 720))
    x, y, w, h = roi
    enlarged = cv2.resize(
        image[y : y + h, x : x + w], (w * 4, h * 4), interpolation=cv2.INTER_CUBIC
    )
    prepared = Path(path).with_name(Path(path).stem + f"-reward-count-{x}.png")
    # DebugImageTest normalizes full images to1280x720, so retain that canvas.
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    canvas[: h * 4, : w * 4] = enlarged
    if not cv2.imwrite(str(prepared), canvas):
        raise CheckpointError("Could not save magnified reward counter")
    return prepared, [0, 0, w * 4, h * 4]


def read_rewards(runtime, path, stage):
    if not runtime.matches(path, ["SandAuto@Result"]):
        raise CheckpointError("Reward accounting requires a verified result screen")
    titles = runtime.ocr(path, [45, 140, 380, 65])
    if not any(
        text_key(r.get("text", "")) == text_key(stage) and r.get("score", 0) >= 0.85
        for r in titles
    ):
        raise CheckpointError("Reward stage does not match the operation")
    tasks = ["SandAuto@Settlement" + item for item in ITEMS]
    hits = runtime.matches(path, tasks)
    counts, evidence, occupied = {}, {}, set()
    for item, resource in ITEMS.items():
        hit = hits.get("SandAuto@Settlement" + item)
        if not hit:
            continue
        if hit.get("score", 0) < 0.9:
            raise CheckpointError("Reward icon did not meet the native match threshold")
        slot, roi = count_roi(hit)
        if slot in occupied:
            raise CheckpointError("Conflicting reward identities share an item slot")
        occupied.add(slot)
        count_task = f"SandAuto@SettlementCount{slot}"
        count = runtime.matches(path, [count_task]).get(count_task)
        reads = [count] if count else []
        prepared = None
        count_source = "primary"
        try:
            value = quantity(reads)
        except CheckpointError:
            # Preserve the original high-confidence crop. Widen only on an actual failure.
            roi = count_roi(hit, wide=True)[1]
            wide_task = f"SandAuto@SettlementCountWide{slot}"
            widened = runtime.matches(path, [wide_task]).get(wide_task)
            if widened is None:
                raise CheckpointError(
                    "Reward counter unresolved in primary and widened native OCR"
                )
            reads = [widened]
            count_source = "wide"
            try:
                value = quantity(reads)
            except CheckpointError:
                # One magnified retry, keeping the same strict grammar and confidence.
                prepared, enlarged_roi = enlarged_count(path, roi)
                reads = runtime.ocr(prepared, enlarged_roi)
                value = quantity(reads)
                count_source = "wide_magnified"
        counts[resource] = value
        evidence[resource] = {
            "icon": hit,
            "quantity_reads": reads,
            "roi": roi,
            "enlarged_image": str(prepared) if prepared else None,
            "count_source": count_source,
        }
    return {
        "image": str(path),
        "stage": stage,
        "verified_counts": counts,
        "evidence": evidence,
        "inventory_updated": False,
        "complete_inventory": False,
        "status": "identified_rewards" if counts else "unresolved_rewards",
        "missing_item_rule": "An unmatched item is unknown, never zero.",
    }
