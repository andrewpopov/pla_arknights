"""Strict raid HUD observations, independent of controller inputs and stage routes."""

import re
from dataclasses import dataclass

from maa_sand_config import CheckpointError


def kill_fraction(text):
    match = re.fullmatch(r"\s*(\d{1,3})\s*/\s*(\d{1,3})\s*", text)
    if not match:
        return None
    kills, total = map(int, match.groups())
    return (kills, total) if 0 <= kills <= total and total > 0 else None


@dataclass(frozen=True)
class RaidProgress:
    kills: int
    total: int
    lives: int | None

    def delta(self, previous):
        if (
            self.total != previous.total
            or self.kills < previous.kills
            or (
                self.lives is not None
                and previous.lives is not None
                and self.lives > previous.lives
            )
        ):
            raise CheckpointError(
                "Raid observations do not belong to one monotonic battle"
            )
        return {
            "kills": self.kills - previous.kills,
            "lives_lost": (
                previous.lives - self.lives
                if self.lives is not None and previous.lives is not None
                else None
            ),
        }


def raid_progress(matches, require_lives=False):
    counter = matches.get("SandAuto@RaidKills", {})
    kills = (
        kill_fraction(counter.get("text", ""))
        if counter.get("score", 0) >= 0.85
        else None
    )
    if kills is None:
        return None
    life = matches.get("SandAuto@RaidLives", {})
    text = life.get("text", "").strip()
    lives = (
        int(text)
        if life.get("score", 0) >= 0.85 and re.fullmatch(r"\d{1,2}", text)
        else None
    )
    if lives is None and require_lives:
        raise CheckpointError("Raid lives were not confidently observed")
    return RaidProgress(*kills, lives)


def guard_unidentified_battle(runtime, path, matches):
    """Stop the clock on recognized battle controls when numeric identity fails."""
    if (
        matches.get("BattleOfficiallyBegin", {}).get("score", 0) < 0.85
        or any(
            name in matches
            for name in (
                "SandAuto@Battle",
                "SandAuto@RaidBattle",
                "SandAuto@DialogueLog",
                "SandAuto@Result",
            )
        )
        or all(
            matches.get(name, {}).get("score", 0) >= 0.95
            for name in ("SandAuto@CampExit", "SandAuto@CampBag", "SandAuto@CampTent")
        )
        or raid_progress(matches) is not None
    ):
        return
    if matches.get("SandAuto@Paused", {}).get("score", 0) < 0.85:
        runtime.task("SandPilot@PauseNavigationBattle")
    final, _ = runtime.capture("unidentified-battle-pause")
    verified = runtime.matches(final, ["SandAuto@Paused"])
    if verified.get("SandAuto@Paused", {}).get("score", 0) < 0.85:
        raise CheckpointError(f"Unidentified battle HUD; pause unconfirmed: {final}")
    runtime.log(
        "unidentified_battle_preserved_paused", before=str(path), image=str(final)
    )
    raise CheckpointError(f"Unidentified battle HUD preserved paused: {final}")
