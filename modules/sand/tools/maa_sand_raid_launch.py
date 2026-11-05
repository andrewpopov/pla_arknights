"""Own one observed raid Act through existing named navigation, combat and result controls."""

import copy
import time
from pathlib import Path

from maa_sand_config import CheckpointError
from maa_sand_days import ActJournal, verify_world
from maa_sand_navigation import CampaignNavigator
from maa_sand_raid import RaidExecutor
from maa_sand_settlement import text_key
from maa_sand_visit import read_trip_energy
from maa_sand_world import read_world, reconcile_world


def review_raid_state(state, profile):
    if type(state.get("acts_used")) is not int or not 0 <= state["acts_used"] <= 1:
        raise CheckpointError(
            "Raid interception requires an observed unspent daily Act"
        )
    if profile.get("stage_id") not in ("sandbox_1_38", "sandbox_1_56"):
        raise CheckpointError(
            "Raid interception guards support only the reviewed water and jungle examples"
        )
    if (
        profile.get("kind") != "raid-combat"
        or profile.get("result_collection_enabled") is not True
        or state.get("snapshot_current") is not True
        or state.get("settled") is not True
        or state.get("threat") not in ("urgent", "later")
    ):
        raise CheckpointError(
            "Raid Act needs current settled observations and result-to-world support"
        )
    if (
        state.get("raid_reachable") is not True
        or state.get("raid_stage_id") != profile["stage_id"]
        or type(state.get("raid_enemy_count")) is not int
        or state["raid_enemy_count"] != profile["enemy_count"]
    ):
        raise CheckpointError(
            "Observe the reachable raid map and enemy total; a guide date is insufficient"
        )
    if (
        set(state.get("squad", [])) != set(profile["required_squad"])
        or state.get("squad_size") != len(profile["required_squad"])
        or not 1 <= state["squad_size"] <= 6
    ):
        raise CheckpointError(
            "Observed raid squad differs from the reviewed combat profile"
        )
    if set(state["squad"]) & set(state.get("tired", [])):
        raise CheckpointError("Raid squad contains tired operators")
    if type(state.get("drinks")) is not int or state["drinks"] < 2:
        raise CheckpointError("Prepare the complete two-drink raid trip before launch")


class RaidActWorkflow:
    def __init__(self, player, profile, journal_path, run_id):
        self.player, self.profile = player, profile
        self.journal = ActJournal(journal_path, "raid-launch:" + run_id)
        self.battle_journal = Path(journal_path).with_name(
            Path(journal_path).name + ".battle.json"
        )
        self.run_id = run_id
        self.nav = CampaignNavigator(player.rt, player.rt.pack)

    def verify_mode(self, path, stage_id):
        if stage_id != self.profile["stage_id"]:
            raise CheckpointError("Selected raid details belong to a different stage")
        hits = self.player.rt.matches(
            path, ["SandAuto@RaidWorldMarker", "SandAuto@RaidInterceptionStart"]
        )
        if any(
            hits.get(task, {}).get("score", 0) < 0.92
            for task in ("SandAuto@RaidWorldMarker", "SandAuto@RaidInterceptionStart")
        ):
            raise CheckpointError(
                "Selected stage lacks observed raid marker and red interception control"
            )
        rect = hits["SandAuto@RaidWorldMarker"].get("rect", [])
        if len(rect) != 4 or any(type(value) is not int for value in rect):
            raise CheckpointError("Raid marker needs an actual native rectangle")
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            raise CheckpointError("Raid marker rectangle is empty")
        cx, cy = x + w / 2, y + h / 2
        bound = []
        for read in self.player.rt.ocr(path, [35, 100, 825, 525]):
            if read.get("score", 0) < 0.85 or text_key(
                read.get("text", "")
            ) != text_key(self.profile["stage"]):
                continue
            label = read.get("rect", [])
            if len(label) != 4 or any(type(value) is not int for value in label):
                continue
            lx, ly, lw, lh = label
            if (
                lw > 0
                and lh > 0
                and cx + 0.6 * w <= lx <= cx + 4 * w
                and cy + 0.8 * h <= ly + lh / 2 <= cy + 2.4 * h
            ):
                bound.append(read)
        if len(bound) != 1:
            raise CheckpointError(
                "Raid marker is not uniquely bound to the selected stage map label"
            )
        self.mode_evidence = {
            "image": str(path),
            "stage_id": stage_id,
            "matches": hits,
            "node_label": bound[0],
        }

    def run(self, state):
        review_raid_state(state, self.profile)
        with self.journal.locked() as journal:
            if journal.data["acts"]:
                raise CheckpointError(
                    "Raid launch already pending or returned; do not submit another Start"
                )
            if self.battle_journal.exists():
                raise CheckpointError(
                    "Existing battle ledger needs review before another raid launch"
                )
            path, _image, states = self.player.frame("raid-launch-world")
            if "SandAuto@Battle" in states:
                self.player.in_battle = True
                self.player.pause(True)
                raise CheckpointError(
                    "Raid Act interception starts from the world; existing battle preserved paused"
                )
            if "SandAuto@World" not in states:
                raise CheckpointError(
                    "Raid launch requires the actual world-map control"
                )
            before = read_world(self.player.rt, path)
            verify_world(state, before)
            entry = {
                "status": "pending",
                "before": before,
                "stage_id": self.profile["stage_id"],
                "enemy_count": self.profile["enemy_count"],
                "launch_submitted": False,
                "inventory_updated": False,
            }
            journal.data["acts"]["launch"] = entry
            journal.save()  # Own navigation too; never replay an uncertain sequence after restart.
            try:
                formation = self.nav.prepare_formation(
                    self.profile["stage_id"], before_formation=self.verify_mode
                )
                entry.update(mode=self.mode_evidence, formation=formation)
                journal.save()
                path = Path(formation["formation_image"])
                self.player.validate_squad(path)
                from maa_sand_squad import verify_launch_squad

                squad = verify_launch_squad(
                    self.player,
                    path,
                    self.profile["required_squad"],
                    requirements=self.profile.get("required_formation_skills", {}),
                )
                entry["exact_squad"] = squad
                journal.save()
                hits = self.player.rt.matches(
                    path, ["SandAuto@FormationTripEnergy", "SandAuto@NoEquippedTools"]
                )
                if hits.get("SandAuto@NoEquippedTools", {}).get("score", 0) < 0.95:
                    raise CheckpointError(
                        "Raid formation requires the observed empty first tool slot"
                    )
                energy = read_trip_energy(
                    self.player.rt, path, hits.get("SandAuto@FormationTripEnergy", {})
                )
                if (energy["cost"], energy["stock"], energy["funded"]) != (
                    2,
                    state["drinks"],
                    True,
                ):
                    raise CheckpointError(
                        "Actual raid drink cost/stock differs from the observed complete budget"
                    )
                entry.update(
                    mode=self.mode_evidence,
                    formation=formation,
                    energy=energy,
                    launch_submitted=True,
                )
                journal.save()  # Durable before the single paid squad Start.
                self.player.rt.task("SandPilot@SquadStart")
                for _ in range(90):
                    path, _image, states = self.player.frame("loading")
                    if "SandAuto@Battle" in states:
                        self.player.in_battle = True
                        self.player.pause(True)
                    entry["latest_launch_frame"] = {
                        "image": str(path),
                        "states": list(states),
                    }
                    journal.save()
                    if "SandAuto@NoEnergy" in states:
                        raise CheckpointError(
                            "Raid launch reports insufficient drinks; do not brew or repeat Start"
                        )
                    if "SandAuto@Battle" in states:
                        if "SandAuto@RaidBattle" not in states:
                            raise CheckpointError(
                                "Expected raid mode; ordinary battle preserved paused without harvest actions"
                            )
                        progress = self.player.raid_progress
                        if (
                            progress.total != self.profile["enemy_count"]
                            or progress.kills != 0
                        ):
                            raise CheckpointError(
                                "Launched wave differs from the owned fresh raid observation"
                            )
                        break
                    time.sleep(0.5)
                else:
                    raise CheckpointError(
                        "Raid start transition unconfirmed; do not repeat the paid launch"
                    )
                outcome = RaidExecutor(
                    self.player, self.profile, self.battle_journal, self.run_id
                ).run()
                entry["outcome"] = outcome
                if not outcome.get("world_return_verified") or not outcome.get("world"):
                    raise CheckpointError(
                        "Raid Act has no verified result-to-world handoff"
                    )
                reconciliation = reconcile_world(
                    before, outcome["world"], outcome.get("rewards", {})
                )
                if reconciliation["observed_act_difference"] != 1:
                    raise CheckpointError(
                        "Raid return did not show exactly one Act consumed"
                    )
                entry.update(status="returned", reconciliation=reconciliation)
                journal.save()
                result = copy.deepcopy(outcome)
                result["reconciliation"] = reconciliation
                result["settlement_image"] = (
                    outcome.get("raid_result", {}).get("settlement", {}).get("image")
                )
                return result
            except BaseException as exc:
                entry["error"] = str(exc)
                try:
                    journal.save()
                finally:
                    if self.player.in_battle:
                        try:
                            self.player.pause(True)
                        except Exception as pause_error:  # noqa: BLE001 - preserve original failure
                            self.player.rt.log(
                                "raid_launch_pause_not_confirmed",
                                reason=str(pause_error),
                            )
                raise
