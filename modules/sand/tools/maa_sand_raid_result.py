"""Read raid results and collect once, keeping victory and final-life proof separate."""

import time
from dataclasses import asdict

from maa_sand_battle import RaidProgress, kill_fraction
from maa_sand_config import CheckpointError
from maa_sand_settlement import enlarged_count, read_rewards
from maa_sand_world import read_world

RESULT_COUNTER_ROI = [270, 335, 70, 23]


def remaining_fraction(reads):
    candidates = [
        kill_fraction(read.get("text", ""))
        for read in reads
        if read.get("score", 0) >= 0.85
    ]
    candidates = [value for value in candidates if value is not None]
    if len(candidates) != 1:
        raise CheckpointError(
            "Raid result needs one confident complete remaining/total reading"
        )
    return candidates[0]


def prove_completion(initial, last, trace, remaining, total, result_image):
    if (
        type(total) is not int
        or not 1 <= total <= 999
        or type(remaining) is not int
        or not 0 <= remaining <= total
    ):
        raise CheckpointError(
            "Raid result proof requires bounded observed enemy counts"
        )
    if initial is not None and not isinstance(initial, RaidProgress):
        raise CheckpointError("Initial raid HUD must be an observed RaidProgress")
    if last is not None and not isinstance(last, RaidProgress):
        raise CheckpointError("Last raid HUD must be an observed RaidProgress")
    if not isinstance(trace, list) or any(not isinstance(row, dict) for row in trace):
        raise CheckpointError("Raid proof needs structured observed HUD history")
    proof = {
        "raid_victory_verified": False,
        "lives_preserved_verified": False,
        "terminal_hud_verified": False,
        "final_lives": None,
        "lives_lost": None,
    }
    if initial is None or last is None or not trace:
        return {
            **proof,
            "reason": "Initial and terminal live HUD evidence is incomplete",
        }
    previous = initial
    for row in [asdict(initial), *trace, asdict(last)]:
        if (
            any(type(row.get(key)) is not int for key in ("kills", "total"))
            or row["total"] != total
            or not 0 <= row["kills"] <= total
            or (
                row.get("lives") is not None
                and (type(row["lives"]) is not int or not 0 <= row["lives"] <= 99)
            )
        ):
            raise CheckpointError(
                "Raid live trace does not bind the expected wave and numeric values"
            )
        current = RaidProgress(row["kills"], row["total"], row.get("lives"))
        current.delta(previous)
        previous = current
    if initial.kills != 0:
        raise CheckpointError("Raid result proof needs the owned fresh-wave baseline")
    final = trace[-1]
    if (
        not final.get("image")
        or final["image"] == str(result_image)
        or (final["kills"], final["total"], final.get("lives"))
        != (last.kills, last.total, last.lives)
    ):
        return {
            **proof,
            "reason": "Terminal live HUD is not bound to a distinct observed battle frame",
        }
    if last.kills + remaining > total:
        raise CheckpointError("Live kills contradict result remaining enemies")
    terminal = last.kills == total and last.lives is not None and last.lives > 0
    clear = terminal and remaining == 0
    return {
        **proof,
        "terminal_hud_verified": terminal,
        "raid_victory_verified": clear,
        "lives_preserved_verified": bool(
            clear and initial.lives is not None and initial.lives == last.lives
        ),
        "final_lives": last.lives if terminal else None,
        "lives_lost": initial.lives - last.lives
        if terminal and initial.lives is not None
        else None,
        "reason": "Terminal HUD and result agree"
        if clear
        else "Result alone cannot prove final lives or a complete clear",
    }


def read_raid_result(
    runtime, path, stage, expected_total, *, initial=None, last=None, trace=None
):
    if type(expected_total) is not int or not 1 <= expected_total <= 999:
        raise CheckpointError("Raid result requires the observed expected enemy total")
    hits = runtime.matches(
        path,
        ["SandAuto@Result", "SandAuto@RaidResultBadge", "SandAuto@RaidResultRemaining"],
    )
    if (
        hits.get("SandAuto@Result", {}).get("score", 0) < 0.85
        or hits.get("SandAuto@RaidResultBadge", {}).get("score", 0) < 0.92
    ):
        raise CheckpointError(
            "Named raid result control and distinct result badge are required"
        )
    reads = [hits.get("SandAuto@RaidResultRemaining", {})]
    prepared = None
    try:
        remaining, total = remaining_fraction(reads)
    except CheckpointError:
        prepared, roi = enlarged_count(path, RESULT_COUNTER_ROI)
        reads = runtime.ocr(prepared, roi)
        remaining, total = remaining_fraction(reads)
    if total != expected_total:
        raise CheckpointError("Raid result enemy total differs from the owned battle")
    settlement = read_rewards(runtime, path, stage)
    proof = prove_completion(initial, last, trace or [], remaining, total, path)
    return {
        "stage": stage,
        "image": str(path),
        "remaining_enemies": remaining,
        "enemy_total": total,
        "settlement": settlement,
        "rewards": settlement["verified_counts"],
        **proof,
        "evidence": {
            "badge": hits["SandAuto@RaidResultBadge"],
            "counter_reads": reads,
            "magnified_counter": str(prepared) if prepared else None,
        },
        "inventory_updated": False,
    }


def collect_raid_result(player, path, profile, entry, journal):
    """Read everything before one existing native result click; never advance a day."""
    if entry.get("collection_submitted") or entry.get("world_return_verified"):
        raise CheckpointError(
            "Previous raid result collection is pending or already returned; do not repeat"
        )
    baseline = entry.get("initial", {})
    latest = entry.get("latest_hud", {})
    initial = (
        RaidProgress(baseline["kills"], baseline["total"], baseline.get("lives"))
        if baseline
        else None
    )
    last = (
        RaidProgress(latest["kills"], latest["total"], latest.get("lives"))
        if latest
        else None
    )
    result = read_raid_result(
        player.rt,
        path,
        profile["stage"],
        profile["enemy_count"],
        initial=initial,
        last=last,
        trace=entry.get("hud_history", []),
    )
    entry.update(
        raid_result=result,
        raid_victory_verified=result["raid_victory_verified"],
        lives_preserved_verified=result["lives_preserved_verified"],
        collection_submitted=True,
        status="raid_result_collection_pending",
    )
    journal.save()  # Durable before the single existing Items received control.
    player.rt.task("SandPilot@GatherResult")
    for _ in range(10):
        returned, _image, states = player.frame("raid-world-return")
        if "SandAuto@World" in states:
            world = read_world(player.rt, returned)
            entry.update(
                status="raid_world_returned"
                if result["raid_victory_verified"]
                and result["lives_preserved_verified"]
                else "raid_world_returned_needs_review",
                settlement_collected=True,
                world_return_verified=True,
                world=world,
                rewards=result["rewards"],
                inventory_updated=False,
                act_debit_verified=False,
                day_advanced=False,
            )
            journal.save()
            return entry
        time.sleep(0.25)
    raise CheckpointError(
        "Raid collection submitted but world return unconfirmed; do not click again"
    )
