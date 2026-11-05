"""Experimental paused-raid combat using the existing registered Sand controls."""

import argparse
import copy
import json
import tempfile
import time
from pathlib import Path

from maa_sand_config import (
    CheckpointError,
    anchor_spec,
    default_pack,
    validate_formation_power,
    validate_formation_skills,
)
from maa_sand_days import ActJournal

DAY5_DEPLOYMENT_ORDER = ["Fang", "Midnight", "Popukar", "Ansel", "Lava", "Beagle"]


def load_raid_skills(pack=None):
    pack = Path(pack) if pack else default_pack()
    data = json.loads((pack / "campaign/raid-skills.json").read_text(encoding="utf8"))
    if data.get("schema_version") != 1 or data.get("game_connected") is not False:
        raise CheckpointError("Unsupported raid skill catalog")
    for name, skill in data["operators"].items():
        if (
            not name
            or not skill.get("title")
            or skill.get("activation") not in ("AUTO", "MANUAL")
            or type(skill.get("skill")) is not int
            or skill["skill"] not in (1, 2, 3)
            or type(skill.get("sp_cost")) is not int
            or not 1 <= skill["sp_cost"] <= 100
            or skill.get("rank") != 7
            or skill.get("actual_owned_skill_verified") is not False
        ):
            raise CheckpointError(
                "Raid skill must identify the exact unverified source rank and SP cost"
            )
        policy = skill.get(
            "activation_policy",
            "automatic" if skill["activation"] == "AUTO" else "repeat",
        )
        allowed = (
            ("automatic",)
            if skill["activation"] == "AUTO"
            else ("repeat", "once_per_deployment")
        )
        if policy not in allowed:
            raise CheckpointError(
                "Raid skill activation policy conflicts with its automatic/manual type"
            )
        if (
            skill.get("skill_id") == "skchr_f12yin_2"
            and policy != "once_per_deployment"
        ):
            raise CheckpointError("Sweeping Stance must never be repeatedly toggled")
        skill["activation_policy"] = policy
    return data["operators"]


def load_raid_profile(path, pack=None):
    pack = Path(pack) if pack else default_pack()
    data = json.loads(Path(path).read_text(encoding="utf8"))
    catalog = json.loads((pack / "campaign/stages.json").read_text(encoding="utf8"))[
        "stages"
    ]
    stage = catalog.get(data.get("stage_id"))
    if (
        data.get("schema_version") != 1
        or data.get("kind") != "raid-combat"
        or data.get("theme") != "Tales"
        or data.get("autoplay_enabled") is not False
        or stage is None
        or stage["english"] != data.get("stage")
        or not data.get("validation_status")
    ):
        raise CheckpointError("Raid needs an experimental stage-bound combat profile")
    if (
        not isinstance(data.get("id"), str)
        or not data["id"]
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in data["id"])
    ):
        raise CheckpointError("Invalid raid profile identifier")
    if data.get("coordinate_system") != "registered-1280x720" or not data.get(
        "placement_evidence"
    ):
        raise CheckpointError(
            "Raid deployment requires reviewed registered camera slots"
        )
    anchor_spec(pack, data)
    squad = data.get("required_squad")
    skills = load_raid_skills(pack)
    if (
        not isinstance(squad, list)
        or not 1 <= len(squad) <= 6
        or any(not isinstance(name, str) or name not in skills for name in squad)
        or len(set(squad)) != len(squad)
    ):
        raise CheckpointError(
            "Raid requires a unique reviewed source squad of at most six operators"
        )
    required_skills = {name: skills[name]["skill"] for name in squad}
    declared = data.get("required_formation_skills", required_skills)
    validate_formation_skills(declared, squad)
    if declared != required_skills:
        raise CheckpointError(
            "Raid formation skills must match the exact combat skill catalog"
        )
    data["required_formation_skills"] = required_skills
    ranks = {name: skills[name]["rank"] for name in squad}
    declared_ranks = data.get("required_formation_ranks", ranks)
    validate_formation_skills(required_skills, squad, declared_ranks)
    if declared_ranks != ranks:
        raise CheckpointError(
            "Raid formation ranks must match the combat timing catalog"
        )
    data["required_formation_ranks"] = ranks
    levels = data.get(
        "required_formation_levels",
        dict.fromkeys(squad, 55) if data.get("source_day") == 5 else {},
    )
    elites = data.get(
        "required_formation_elites",
        dict.fromkeys(squad, 1) if data.get("source_day") == 5 else {},
    )
    validate_formation_power(levels, elites, squad)
    if data.get("source_day") == 5 and any(
        levels.get(name, 0) < 55 or elites.get(name, -1) < 1 for name in squad
    ):
        raise CheckpointError(
            "Day5 guide combat requires the source E1 level55 minimum team"
        )
    data["required_formation_levels"], data["required_formation_elites"] = (
        levels,
        elites,
    )
    normal, side = data.get("normal_points"), data.get("side_points")
    if (
        not isinstance(normal, dict)
        or not normal
        or not isinstance(side, dict)
        or set(normal) != set(side)
    ):
        raise CheckpointError("Raid needs both camera poses for each slot")
    for points in (normal, side):
        for point in points.values():
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(type(v) is not int for v in point)
                or not 430 < point[0] < 1000
                or not 80 < point[1] < 580
            ):
                raise CheckpointError("Raid point is outside the calibrated viewport")
    if type(data.get("manual_skills_enabled", True)) is not bool:
        raise CheckpointError("Raid manual-skill policy must be an explicit boolean")
    if type(data.get("result_collection_enabled", False)) is not bool:
        raise CheckpointError("Raid result collection must be an explicit boolean")
    skill_limit = data.get("maximum_skill_uses", 5)
    if type(skill_limit) is not int or not 1 <= skill_limit <= 10:
        raise CheckpointError("Manual raid skills need a bounded use limit")
    for key, low, high in (
        ("enemy_count", 1, 999),
        ("max_lives_lost", 0, 2),
        ("maximum_wall_seconds", 30, 900),
    ):
        if type(data.get(key)) is not int or not low <= data[key] <= high:
            raise CheckpointError(
                "Raid needs bounded enemy, damage and wall-time policies"
            )
    steps = data.get("steps")
    if not isinstance(steps, list) or len(steps) != len(squad):
        raise CheckpointError(
            "Raid must explicitly deploy each source squad member once"
        )
    actors, occupants = set(), {}
    base_fields = {
        "name",
        "slot",
        "direction",
        "minimum_dp",
        "minimum_kills",
        "timeout_seconds",
    }
    for step in steps:
        if (
            not isinstance(step, dict)
            or set(step) not in (base_fields, base_fields | {"replace"})
            or not isinstance(step["name"], str)
            or not isinstance(step["slot"], str)
            or step["name"] not in squad
            or step["name"] in actors
            or step["slot"] not in normal
            or step["direction"] not in ("Left", "Right", "Up", "Down")
            or type(step["minimum_dp"]) is not int
            or not 1 <= step["minimum_dp"] <= 99
            or type(step["minimum_kills"]) is not int
            or not 0 <= step["minimum_kills"] < data["enemy_count"]
            or type(step["timeout_seconds"]) is not int
            or not 1 <= step["timeout_seconds"] <= 60
        ):
            raise CheckpointError("Invalid or duplicate raid deployment step")
        previous = occupants.get(step["slot"])
        if "replace" in step:
            if (
                data.get("replacement_mode") != "retreat_when_funded"
                or not isinstance(step["replace"], str)
                or previous != step["replace"]
                or step["replace"] == step["name"]
            ):
                raise CheckpointError(
                    "Raid replacement must retire the actual prior actor on the same slot"
                )
        elif previous is not None:
            raise CheckpointError(
                "Duplicate raid slot requires an explicit verified replacement"
            )
        actors.add(step["name"])
        occupants[step["slot"]] = step["name"]
    if data.get("source_day") == 5 and (
        [step["name"] for step in steps] != DAY5_DEPLOYMENT_ORDER
        or steps[-1].get("replace") != "Fang"
        or steps[-1]["slot"] != steps[0]["slot"]
    ):
        raise CheckpointError(
            "Day5 source routine requires Lava before the Beagle-for-Fang tile replacement"
        )
    return {**data, "background_skills": [], "_skills": skills}


class RaidExecutor:
    """Take over a fresh paused raid; preserve its result for separate campaign review."""

    def __init__(self, player, profile, journal, run_id):
        if not isinstance(run_id, str) or not run_id.strip():
            raise CheckpointError("Raid takeover requires an explicit unique run ID")
        self.player, self.profile = player, copy.deepcopy(profile)
        self.journal = ActJournal(journal, "raid:" + run_id)
        self.skill_uses = {}
        self.started = None

    def secure(self):
        if not self.player.in_battle and getattr(self, "entry", {}).get("result_image"):
            return  # An owned result/world checkpoint has no active battle clock.
        try:
            self.player.pause(True)
        except Exception as exc:  # noqa: BLE001 - preserve original failure and checkpoint uncertainty
            self.player.rt.log("raid_pause_not_confirmed", reason=str(exc))

    def observe(self):
        path, image, states = self.player.frame("raid-progress")
        if "SandAuto@Result" in states:
            self.player.in_battle = False
            return path, image, None
        if "SandAuto@RaidBattle" not in states:
            raise CheckpointError(
                "Fresh raid HUD unavailable; do not reuse a stale kill/life reading"
            )
        progress = self.player.raid_progress
        hud = {
            "image": str(path),
            "kills": progress.kills,
            "total": progress.total,
            "lives": progress.lives,
        }
        self.entry["latest_hud"] = hud
        history = self.entry["hud_history"]
        if not history or any(
            history[-1][key] != hud[key] for key in ("kills", "total", "lives")
        ):
            history.append(hud)
        self.journal.save()
        if (
            progress.lives is None
            or progress.lives <= 0
            or progress.total != self.profile["enemy_count"]
        ):
            raise CheckpointError(
                "Raid lives or wave size are missing, exhausted or mismatched"
            )
        progress.delta(self.previous)
        self.previous = progress
        if self.initial.lives - progress.lives > self.profile["max_lives_lost"]:
            raise CheckpointError(
                "Raid damage budget exceeded; preserved paused for review"
            )
        if time.monotonic() - self.started >= self.profile["maximum_wall_seconds"]:
            raise CheckpointError("Raid exceeded its bounded wall-time budget")
        return path, image, progress

    def service_skills(self, entry):
        if not self.profile.get("manual_skills_enabled", True):
            return
        for step in self.profile["steps"]:
            name, slot = step["name"], step["slot"]
            spec = self.profile["_skills"][name]
            limit = (
                1
                if spec.get("activation_policy") == "once_per_deployment"
                else self.profile.get("maximum_skill_uses", 5)
            )
            if (
                spec["activation"] != "MANUAL"
                or self.player.deployed.get(slot) != name
                or self.skill_uses.get(name, 0) >= limit
            ):
                continue
            entry["pending_skill"] = {"name": name, "slot": slot}
            self.journal.save()
            result = self.player.raid_skill(name, slot, spec["title"], spec["sp_cost"])
            if result is not None:
                self.skill_uses[name] = self.skill_uses.get(name, 0) + 1
                entry["skills"].append({"name": name, "slot": slot, **result})
            entry.pop("pending_skill")
            self.journal.save()

    def run(self):
        with self.journal.locked() as journal:
            if journal.data["acts"]:
                self.secure()
                raise CheckpointError(
                    "Raid already has a pending or reviewed execution; do not replay it"
                )
            if self.player.deployed or getattr(self.player, "deployed_tools", {}):
                raise CheckpointError(
                    "Raid takeover requires an empty local deployment ledger"
                )
            path, image, states = self.player.frame("raid-entry")
            if "SandAuto@RaidBattle" not in states:
                raise CheckpointError(
                    "Start from an actual raid battle, not a harvesting map or world node"
                )
            self.player.in_battle = True
            self.player.pause(True)
            initial = self.player.raid_progress
            if (
                initial.kills != 0
                or initial.total != self.profile["enemy_count"]
                or initial.lives is None
                or initial.lives <= 0
            ):
                raise CheckpointError(
                    "Fresh source raid wave and initial lives must be observed"
                )
            self.initial = self.previous = initial
            self.started = time.monotonic()
            entry = {
                "status": "pending",
                "profile": self.profile["id"],
                "entry_image": str(path),
                "initial": {
                    "kills": initial.kills,
                    "total": initial.total,
                    "lives": initial.lives,
                },
                "profile_snapshot": {
                    k: v for k, v in self.profile.items() if not k.startswith("_")
                },
                "deployments": [],
                "skills": [],
                "hud_history": [],
                "skill_reference": {
                    step["name"]: self.profile["_skills"][step["name"]]
                    for step in self.profile["steps"]
                },
                "raid_victory_verified": False,
                "lives_preserved_verified": False,
                "inventory_updated": False,
            }
            self.entry = entry
            journal.data["acts"]["battle"] = entry
            journal.save()
            self.player.in_battle = True
            try:
                self.player.pause(True)
                _path, image, _states = self.player.stable_frame("raid-camera")
                self.player.idle_map.transform(
                    image
                )  # Refuse an unrelated stage/camera before deploying.
                for index, step in enumerate(self.profile["steps"]):
                    deadline = time.monotonic() + step["timeout_seconds"]
                    while True:
                        path, _image, progress = self.observe()
                        if progress is None:
                            return self.result(entry, path)
                        hand = self.player.rt.analyze(path, "battle_deployment")
                        dp = hand.get("dp")
                        entry["latest_hand_dp"] = dp if type(dp) is int else None
                        journal.save()
                        if (
                            type(dp) is int
                            and dp >= step["minimum_dp"]
                            and progress.kills >= step["minimum_kills"]
                        ):
                            break
                        if time.monotonic() >= deadline:
                            raise CheckpointError(
                                "Raid deployment conditions exceeded their action deadline"
                            )
                        self.service_skills(entry)
                        self.player.advance(2)
                    if "replace" in step:
                        if (
                            self.profile.get("replacement_mode")
                            != "retreat_when_funded"
                        ):
                            raise CheckpointError(
                                "Raid replacement needs an explicit funded-retreat policy"
                            )
                        entry["pending_replacement"] = {
                            "index": index,
                            "retiring": step["replace"],
                            "slot": step["slot"],
                            "replacement": step["name"],
                        }
                        journal.save()
                        retired = self.player.retreat_raid(
                            step["replace"], step["slot"]
                        )
                        if (
                            not isinstance(retired, dict)
                            or retired.get("name") != step["replace"]
                            or retired.get("slot") != step["slot"]
                            or retired.get("cooling_transition_verified") is not True
                            or self.player.deployed.get(step["slot"]) is not None
                        ):
                            raise CheckpointError(
                                "Raid replacement slot was not confirmed vacated"
                            )
                        entry.setdefault("replacements", []).append(
                            {**entry["pending_replacement"], "proof": retired}
                        )
                        entry.pop("pending_replacement")
                        journal.save()
                        path, _image, progress = self.observe()
                        if progress is None:
                            return self.result(entry, path)
                    entry["pending_deployment"] = {"index": index, **step}
                    journal.save()
                    proof = self.player.deploy_raid(
                        step["name"], step["slot"], step["direction"]
                    )
                    if self.player.deployed.get(step["slot"]) != step["name"]:
                        raise CheckpointError(
                            "Native controls did not confirm the requested deployment"
                        )
                    entry["deployments"].append(
                        {"index": index, **step, "proof": proof}
                    )
                    entry.pop("pending_deployment")
                    journal.save()
                while True:
                    path, _image, progress = self.observe()
                    if progress is None:
                        return self.result(entry, path)
                    self.service_skills(entry)
                    self.player.advance(
                        0.5 if progress.total - progress.kills <= 3 else 2
                    )
            except BaseException as exc:
                entry["error"] = str(exc)
                try:
                    journal.save()
                finally:
                    self.secure()
                raise

    def result(self, entry, path):
        # Never equate the result screen or a completed action list with a won raid.
        entry.update(
            status="result_pending_review",
            result_image=str(path),
            settlement_collected=False,
            world_return_verified=False,
        )
        self.journal.save()
        if self.profile.get("result_collection_enabled", False):
            from maa_sand_raid_result import collect_raid_result

            collect_raid_result(self.player, path, self.profile, entry, self.journal)
        return copy.deepcopy(entry)


def compile_raid_profile(day, calibration, pack=None):
    """Compile guide order only; source screenshots do not supply executable coordinates."""
    pack = Path(pack) if pack else default_pack()
    if day == 3:
        reference = json.loads(
            (pack / "guides/kuniya-days2-3-deployments.json").read_text(encoding="utf8")
        )
        source = next(
            row for row in reference["routes"] if row["day"] == 3 and row["act"] == 1
        )
        stage_id, total = "sandbox_1_56", 44
        squad = source["source_squad"]
    elif day == 5:
        source = json.loads(
            (pack / "guides/kuniya-day5-raid.json").read_text(encoding="utf8")
        )
        stage_id, total = source["reference_stage_id"], 42
        squad = source["source_squad"]
    else:
        raise CheckpointError("Only reviewed Day3/Day5 raid examples are supported")
    if calibration.get("stage_id") != stage_id or not calibration.get(
        "placement_evidence"
    ):
        raise CheckpointError(
            "Raid calibration must identify the source map and reviewed tile/facing evidence"
        )
    order = calibration.get("deployment_order")
    if (
        not isinstance(order, list)
        or len(order) != len(squad)
        or set(order) != set(squad)
    ):
        raise CheckpointError(
            "Review the complete deployment order; formation order is not deployment order"
        )
    if day == 5 and (
        order != DAY5_DEPLOYMENT_ORDER
        or not calibration.get("replacement_evidence")
        or calibration.get("replacement_mode") != "retreat_when_funded"
    ):
        raise CheckpointError(
            "Day5 requires reviewed Lava-before-Beagle order and an explicit funded replacement policy"
        )
    catalog = json.loads((pack / "campaign/stages.json").read_text(encoding="utf8"))[
        "stages"
    ]
    skill_catalog = load_raid_skills(pack)
    slots, directions, costs = (
        calibration.get(key, {}) for key in ("slots", "directions", "dp_costs")
    )
    steps = []
    for name in order:
        slot = slots.get(name)
        if not isinstance(slot, str) or slot not in directions or name not in costs:
            raise CheckpointError(
                "Every raid operator needs a reviewed slot, direction and actual DP cost"
            )
        steps.append(
            {
                "name": name,
                "slot": slot,
                "direction": directions[slot],
                "minimum_dp": costs[name],
                "minimum_kills": 0,
                "timeout_seconds": 60,
            }
        )
        if day == 5 and name == "Beagle":
            if slot != slots.get("Fang"):
                raise CheckpointError(
                    "Beagle must replace Fang on the same reviewed Day5 tile"
                )
            steps[-1]["replace"] = "Fang"
    return {
        "schema_version": 1,
        "kind": "raid-combat",
        "id": f"day{day}-raid",
        "theme": "Tales",
        "stage_id": stage_id,
        "stage": catalog[stage_id]["english"],
        "enemy_count": total,
        "autoplay_enabled": False,
        "validation_status": "Source raid example compiled; live deployment/skill/result validation pending",
        "coordinate_system": "registered-1280x720",
        "placement_evidence": calibration["placement_evidence"],
        "anchor_manifest": calibration.get("anchor_manifest"),
        "anchors": copy.deepcopy(
            calibration.get("anchors", {"idle": "idle.png", "side": "side.png"})
        ),
        "normal_points": copy.deepcopy(calibration.get("normal_points", {})),
        "side_points": copy.deepcopy(calibration.get("side_points", {})),
        "required_squad": squad,
        "required_formation_skills": {
            name: skill_catalog[name]["skill"] for name in squad
        },
        "required_formation_ranks": {
            name: skill_catalog[name]["rank"] for name in squad
        },
        "required_formation_levels": dict.fromkeys(squad, 55) if day == 5 else {},
        "required_formation_elites": dict.fromkeys(squad, 1) if day == 5 else {},
        "steps": steps,
        "max_lives_lost": calibration.get("max_lives_lost", 0),
        "maximum_wall_seconds": 600,
        "maximum_skill_uses": 5,
        "source_day": day,
        "manual_skills_enabled": calibration.get("manual_skills_enabled", day != 3),
        "replacement_mode": calibration.get("replacement_mode") if day == 5 else None,
        "replacement_evidence": calibration.get("replacement_evidence")
        if day == 5
        else None,
        "source_date_is_wave_identity": False,
        "result_collection_enabled": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Compile a reviewed raid example without game connection"
    )
    parser.add_argument("--day", type=int, choices=(3, 5), required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        profile = compile_raid_profile(
            args.day,
            json.loads(args.calibration.read_text(encoding="utf-8-sig")),
            args.pack,
        )
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "raid.json"
            candidate.write_text(json.dumps(profile), encoding="utf8")
            load_raid_profile(candidate, args.pack)
    except (CheckpointError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + chr(10), encoding="utf8"
    )
    print(
        json.dumps(
            {
                "profile": str(args.output),
                "autoplay_enabled": False,
                "game_connected": False,
            }
        )
    )


if __name__ == "__main__":
    main()
