"""Observe world HUD facts with native tasks; never infer absent counters or spend Acts."""

import re

from maa_sand_config import CheckpointError

RESOURCES = ("gold", "water", "wood", "stone", "rice")
# The legacy stone template was proved to be a food icon by a wing-only
# settlement. Preserve the API key as unknown until stone identity is calibrated.
HUD_RESOURCES = tuple(name for name in RESOURCES if name != "stone")
FIELDS = [
    "SandAuto@World",
    "SandAuto@WorldDaysLabel",
    "SandAuto@WorldDayNumber",
    "SandAuto@WorldHQLevel",
    "SandAuto@WorldActs0",
    "SandAuto@WorldActs1",
    "SandAuto@WorldActs2",
    *["SandAuto@World" + name.title() for name in HUD_RESOURCES],
    *["SandAuto@WorldIcon" + name.title() for name in HUD_RESOURCES],
]


def number(read, maximum=999999):
    text = read.get("text", "").strip()
    if read.get("score", 0) < 0.85 or not re.fullmatch(r"\d{1,6}", text):
        return None
    value = int(text)
    return value if value <= maximum else None


def acts_left(matches):
    candidates = [
        (matches[f"SandAuto@WorldActs{n}"].get("score", 0), n)
        for n in range(3)
        if f"SandAuto@WorldActs{n}" in matches
    ]
    candidates.sort(reverse=True)
    if not candidates or candidates[0][0] < 0.9:
        return None
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.05:
        return None
    return candidates[0][1]


def parse_world(matches, image):
    acts = acts_left(matches)
    label = matches.get("SandAuto@WorldDaysLabel", {}).get("score", 0) >= 0.85
    day_read = matches.get("SandAuto@WorldDayNumber", {})
    observed_day = number(day_read, 999)
    # The save icon can replace Days. Require both the numeric day and Act dots
    # at high confidence; a bare digit elsewhere on the map is insufficient.
    numeric_hud = (
        acts in (1, 2)
        and observed_day not in (None, 0)
        and day_read.get("score", 0) >= 0.95
        and matches.get(f"SandAuto@WorldActs{acts}", {}).get("score", 0) >= 0.95
    )
    if "SandAuto@World" not in matches or not (label or numeric_hud or acts == 0):
        raise CheckpointError(
            "World facts require the map control and identified day HUD"
        )
    day = observed_day if (label or numeric_hud) and acts != 0 else None
    if day == 0:
        day = None
    level = matches.get("SandAuto@WorldHQLevel", {})
    match = re.fullmatch(
        r"\s*LV\.?\s*(\d{1,2})\s*", level.get("text", ""), re.IGNORECASE
    )
    hq = int(match[1]) if match and level.get("score", 0) >= 0.85 else None
    if hq is not None and not 1 <= hq <= 10:
        hq = None
    resources = {
        name: (
            number(matches.get("SandAuto@World" + name.title(), {}))
            if name in HUD_RESOURCES
            and matches.get("SandAuto@WorldIcon" + name.title(), {}).get("score", 0)
            >= 0.9
            else None
        )
        for name in RESOURCES
    }
    return {
        "image": str(image),
        "day": day,
        "acts_remaining": acts,
        "hq": hq,
        "resources": resources,
        "evidence": matches,
        "unknown_fields": [
            name
            for name, value in {
                "day": day,
                "acts_remaining": acts,
                "hq": hq,
                **resources,
            }.items()
            if value is None
        ],
        "inventory_updated": False,
        "snapshot_current": False,
        "freshness": "Caller must establish capture freshness and campaign continuity.",
    }


def read_world(runtime, path):
    return parse_world(runtime.matches(path, FIELDS), path)


def reconcile_world(before, after, rewards=None):
    days = (before["day"], after["day"])
    if all(day is not None for day in days) and days[0] != days[1]:
        raise CheckpointError(
            "Day changed; do not attribute production or other Acts to this operation"
        )
    same_day = None not in days and days[0] == days[1]
    old, new = before["acts_remaining"], after["acts_remaining"]
    cost = old - new if old is not None and new is not None else None
    if same_day and cost is not None and cost < 0:
        raise CheckpointError("Act count increased within the observed day")
    deltas = {
        name: (
            after["resources"][name] - before["resources"][name]
            if before["resources"][name] is not None
            and after["resources"][name] is not None
            else None
        )
        for name in RESOURCES
    }
    checks = {
        name: (deltas[name] == value if deltas[name] is not None and same_day else None)
        for name, value in (rewards or {}).items()
        if name in deltas
    }
    return {
        "same_day_proven": same_day,
        "observed_act_difference": cost,
        "one_act_confirmed": cost == 1 if same_day and cost is not None else None,
        "resource_deltas": deltas,
        "reward_matches_world_delta": checks,
        "inventory_updated": False,
        "scope": "Observed facts only; caller must verify same campaign and no intervening actions.",
    }
