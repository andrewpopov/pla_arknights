"""Compile source-informed campaign routines against explicitly reviewed calibration."""

import argparse
import copy
import json
import shutil
import tempfile
from pathlib import Path

from maa_sand_campaign import load_campaign
from maa_sand_config import CheckpointError, anchor_spec, default_pack, load_profile
from maa_sand_days import build_day6_water_route

ARTICLE_CHOPPER_DIRECTIONS = {(1, 1): "Left", (2, 1): "Right", (3, 2): "Down"}

WOOD_SQUAD = ["Młynar", "Beagle", "Spot", "Cardigan", "Yato", "Noir Corne"]
HUB_SQUAD = ["Beagle", "Spot", "Hibiscus", "Ansel"]
SUPPORTED = {(1, 1), (1, 2), (2, 1), (3, 2), (4, 1), (6, 1), (6, 2)}


def source_formation_requirements(pack, names):
    """Carry explicit source levels, promotions and skill indices into shared squads."""
    pack = Path(pack)
    day1 = json.loads((pack / "guides/kuniya-day1.json").read_text(encoding="utf8"))
    later = json.loads(
        (pack / "guides/kuniya-days4-6-deployments.json").read_text(encoding="utf8")
    )
    groups = [strategy["squad"] for strategy in day1["strategies"]]
    groups += [
        route["source_squad_details"]
        for route in later["routes"]
        if "source_squad_details" in route
    ]
    known = {}
    for group in groups:
        for actor in group:
            name = actor["name"]
            previous = known.setdefault(name, {})
            for field in ("skill", "elite", "level", "skill_rank"):
                if field in actor:
                    if field in previous and previous[field] != actor[field]:
                        raise CheckpointError(
                            "Source has conflicting formation operator requirements"
                        )
                    previous[field] = actor[field]
    skills = {
        name: known[name]["skill"]
        for name in names
        if name in known and "skill" in known[name]
    }
    ranks = {
        name: known[name].get("skill_rank", 10 if name == "Młynar" else 7)
        for name in skills
    }
    return {
        "required_formation_skills": skills,
        "required_formation_ranks": ranks,
        "required_formation_levels": {
            name: known[name]["level"]
            for name in names
            if name in known and "level" in known[name]
        },
        "required_formation_elites": {
            name: known[name]["elite"]
            for name in names
            if name in known and "elite" in known[name]
        },
    }


def source_formation_skills(pack, names):
    return source_formation_requirements(pack, names)["required_formation_skills"]


def validate_hub_healing(calibration, pack):
    """Check normal medic coverage using existing MAA ranges and native terrain."""
    ranges = json.loads(
        (pack / "campaign/hub-healing-ranges.json").read_text(encoding="utf8")
    )
    projection = json.loads(
        (pack / "tests/native-campaign-tiles.json").read_text(encoding="utf8")
    )
    stage = next(
        row for row in projection["stages"] if row["stage_id"] == "sandbox_1_38"
    )
    terrain = {tuple(tile["tile"]): tile for tile in stage["tiles"]}
    slots = (
        "lower-hub",
        "lower-defender",
        "lower-healer",
        "upper-hub",
        "upper-defender",
        "upper-healer",
    )
    points = calibration.get("logical_tiles")
    if (
        not isinstance(points, dict)
        or any(slot not in points for slot in slots)
        or any(
            not isinstance(points[slot], list)
            or len(points[slot]) != 2
            or any(type(value) is not int for value in points[slot])
            for slot in slots
        )
    ):
        raise CheckpointError(
            "Hub healing requires explicit logical map tiles for both groups"
        )
    if len({tuple(points[slot]) for slot in slots}) != len(slots):
        raise CheckpointError("Hub groups require distinct logical map tiles")
    proof = []
    for prefix, healer in (("lower", "Ansel"), ("upper", "Hibiscus")):
        spec = ranges["operators"][healer]
        if (
            spec["elite"] != 1
            or spec["profession"] != "MEDIC"
            or spec["position"] != "RANGED"
        ):
            raise CheckpointError("Unsupported hub healer range catalog")
        for role in ("hub", "defender", "healer"):
            tile = terrain.get(tuple(points[prefix + "-" + role]))
            allowed = (2, 3) if role == "healer" else (1, 3)
            if tile is None or tile["buildable_type"] not in allowed:
                raise CheckpointError(
                    "Hub healer/defender/tool logical tile has incompatible terrain"
                )
        slot = prefix + "-healer"
        direction = calibration.get("directions", {}).get(slot)
        transforms = {
            "Right": lambda x, y: (x, y),
            "Down": lambda x, y: (-y, x),
            "Left": lambda x, y: (-x, -y),
            "Up": lambda x, y: (y, -x),
        }
        if direction not in transforms:
            raise CheckpointError("Hub healer requires an explicit facing")
        origin = points[slot]
        covered = {
            (origin[0] + dx, origin[1] + dy)
            for dx, dy in (transforms[direction](*offset) for offset in spec["offsets"])
        }
        targets = {role: points[prefix + "-" + role] for role in ("hub", "defender")}
        if any(tuple(point) not in covered for point in targets.values()):
            raise CheckpointError(
                f"{healer} normal healing range misses its hub or defender"
            )
        proof.append(
            {
                "name": healer,
                "elite": 1,
                "slot": slot,
                "tile": origin,
                "direction": direction,
                "range_id": spec["range_id"],
                "targets": targets,
            }
        )
    return {
        "kind": "offline geometric coverage only",
        "groups": proof,
        "live_healing_verified": False,
        "camera_calibration_verified": False,
        "ranges_source_sha256": ranges["source_sha256"],
    }


def compile_route(day, act, calibration, pack=None):
    """No source pixels, timestamps, resource variants or unknown facings are guessed."""
    pack = Path(pack) if pack else default_pack()
    if (day, act) not in SUPPORTED:
        raise CheckpointError(
            "This Act needs a separate hunting, encounter, visit or raid executor"
        )
    wood_target = calibration.get("wood_target")
    if wood_target is not None and (
        (day, act) not in ((1, 1), (2, 1), (3, 2))
        or type(wood_target) is not int
        or not 1 <= wood_target <= 100
    ):
        raise CheckpointError(
            "Wood target is only supported for bounded carrier wood rotations"
        )
    step = load_campaign(pack)["steps"][(day - 1) * 2 + act - 1]
    if calibration.get("stage_id") != step["stage_id"]:
        raise CheckpointError("Calibration must identify this exact campaign stage")
    if not calibration.get("placement_evidence"):
        raise CheckpointError(
            "Reviewed tile, facing and coverage evidence must be supplied"
        )
    if (day, act) == (6, 2):
        return build_day6_water_route(calibration)
    route = {
        "schema_version": 1,
        "id": f"day{day}-act{act}",
        "theme": "Tales",
        "stage": step["stage"],
        "stage_id": step["stage_id"],
        "autoplay_enabled": False,
        "validation_status": "Source-informed routine compiled; live deployment/yield validation pending",
        "coordinate_system": "registered-1280x720",
        "anchor_manifest": calibration.get("anchor_manifest"),
        "anchors": copy.deepcopy(
            calibration.get("anchors", {"idle": "idle.png", "side": "side.png"})
        ),
        "normal_points": copy.deepcopy(calibration.get("normal_points", {})),
        "side_points": copy.deepcopy(calibration.get("side_points", {})),
        "placement_evidence": calibration["placement_evidence"],
        "steps": [],
    }
    actions = route["steps"]
    costs, facing = calibration.get("dp_costs", {}), calibration.get("directions", {})
    deployment_counts = {}

    def deploy(name, slot, *, item_id=None, maximum=None, fixed_direction=None):
        cost = costs.get(name)
        direction = facing.get(slot)
        if (
            type(cost) is not int
            or not 1 <= cost <= 99
            or direction not in ("Left", "Right", "Up", "Down")
            or (fixed_direction is not None and direction != fixed_direction)
        ):
            raise CheckpointError(
                f"Reviewed DP cost and correct explicit facing required: {name}/{slot}"
            )
        if not item_id and deployment_counts.get(name, 0):
            actions.append(
                {
                    "action": "wait_operator",
                    "name": name,
                    "maximum_game_seconds": 120,
                    "remaining_floor": 30,
                }
            )
        else:
            actions.append(
                {"action": "wait_dp", "minimum": cost, "remaining_floor": 30}
            )
        deployment_counts[name] = deployment_counts.get(name, 0) + 1
        action = {
            "action": "deploy",
            "name": name,
            "slot": slot,
            "direction": direction,
        }
        if item_id:
            action = {
                "action": "deploy_tool",
                "item_id": item_id,
                "slot": slot,
                "direction": direction,
                "maximum": maximum,
            }
        actions.append(action)

    if (day, act) == (1, 2):
        for key in (
            "water_tile_evidence",
            "hunting_coverage_evidence",
            "hunting_timing_evidence",
        ):
            if not calibration.get(key):
                raise CheckpointError("Hunting calibration requires " + key)
        recall = calibration.get("gravel_recall_remaining")
        if "hunting_finish_remaining" in calibration:
            raise CheckpointError(
                "Remove hunting_finish_remaining: exit now requires actual food and water, not a clock target"
            )
        if type(recall) is not int or not 25 < recall <= 180:
            raise CheckpointError(
                "Review the bounded Gravel recall clock target; source timestamps are not triggers"
            )
        source = json.loads(
            (pack / "guides/kuniya-day1.json").read_text(encoding="utf8")
        )
        hunt = next(
            strategy
            for strategy in source["strategies"]
            if strategy["stage"] == step["stage"]
        )
        route["required_squad"] = [actor["name"] for actor in hunt["squad"]]
        route["source_reference"] = "guides/kuniya-day1.json"
        for key in (
            "water_tile_evidence",
            "hunting_coverage_evidence",
            "hunting_timing_evidence",
        ):
            route[key] = copy.deepcopy(calibration[key])
        deploy("Crabbie Pumpie", "pump", item_id="sandbox_1_tactical_15", maximum=1)
        deploy("Kroos", "kroos")
        deploy("Adnachiel", "adnachiel")
        deploy("Gravel", "gravel")
        actions.append(
            {
                "action": "wait_until_remaining",
                "remaining": recall,
                "maximum_game_seconds": 180,
            }
        )
        actions.append({"action": "recall", "name": "Gravel", "slot": "gravel"})
        deploy("Steward", "steward")
        actions.append(
            {
                "action": "wait_hunting",
                "pumps": 1,
                "minimum_base_energy": 80,
                "maximum_game_seconds": 180,
                "remaining_floor": 25,
            }
        )
    elif (day, act) in ((1, 1), (2, 1), (3, 2)):
        strategy = calibration.get("strategy", "article")
        if strategy == "video-six-operator" and (day, act) == (1, 1):
            candidate = json.loads(
                (pack / "guides/shrubbery-six-operator-candidate.json").read_text(
                    encoding="utf8"
                )
            )
            route["required_squad"] = [actor["name"] for actor in candidate["squad"]]
            route["zero_capacity_actors"] = candidate["zero_capacity_actors"]
            skills = copy.deepcopy(candidate["background_skills_proposal"])
            slots = {spec["name"]: spec["slot"] for spec in skills}
            for actor in candidate["opening"]:
                deploy(
                    actor["name"], slots[actor["name"]], fixed_direction=actor["facing"]
                )
            carriers = [name for name in route["required_squad"] if name not in slots]
            route["source_strategy"] = (
                "Recorded opener plus offline six-operator proposal; Nian buff timing remains unverified"
            )
        elif strategy == "article":
            route["required_squad"] = list(WOOD_SQUAD)
            route["zero_capacity_actors"] = ["Młynar"]
            deploy(
                "Młynar",
                "chopper",
                fixed_direction=ARTICLE_CHOPPER_DIRECTIONS[(day, act)],
            )
            skills = [
                {"name": "Młynar", "slot": "chopper", "sp_cost": 42, "maximum": 3}
            ]
            carriers = WOOD_SQUAD[1:]
        else:
            raise CheckpointError("Unknown or unsupported source strategy for this Act")
        route["background_skills"] = skills
        route["background_skill_remaining_floor"] = 25
        duration = calibration.get("chop_game_seconds")
        if type(duration) is not int or not 1 <= duration <= 120:
            raise CheckpointError(
                "Supply a bounded, reviewed initial chopping interval in game seconds"
            )
        actions.append(
            {
                "action": "maintain_skills",
                "skills": skills,
                "duration": duration,
                "remaining_floor": 30,
            }
        )
        collection = calibration.get("collection")
        if not isinstance(collection, list) or not 1 <= len(collection) <= 10:
            raise CheckpointError(
                "Explicit observed collection/retreat rotation required; source does not establish it"
            )
        for trip in collection:
            if not isinstance(trip, dict) or set(trip) != {
                "name",
                "slot",
                "minimum",
                "timeout",
            }:
                raise CheckpointError(
                    "Collection trip requires name, slot, minimum and timeout"
                )
            if trip["name"] not in carriers:
                raise CheckpointError(
                    "Source carrier must belong to the reviewed wood squad"
                )
            if wood_target is not None:
                direction = facing.get(trip["slot"])
                if direction not in ("Left", "Right", "Up", "Down"):
                    raise CheckpointError(
                        "Targeted carrier trip requires explicit reviewed facing"
                    )
                actions.append(
                    {"action": "carrier_trip", **trip, "direction": direction}
                )
            else:
                deploy(trip["name"], trip["slot"])
                actions.append({"action": "collect", **trip, "skill_once": False})
                actions.append(
                    {"action": "bank", "name": trip["name"], "slot": trip["slot"]}
                )
        if wood_target is not None:
            route["banked_wood_target"] = wood_target
    elif (day, act) == (4, 1):
        defender = calibration.get("defender")
        if defender not in WOOD_SQUAD[1:4]:
            raise CheckpointError(
                "Review an identified defender for the hub left flank"
            )
        if not calibration.get("ballista_coverage_evidence"):
            raise CheckpointError(
                "Hub below/left ballista protection requires reviewed coverage evidence"
            )
        route["required_squad"] = ["Młynar", defender]
        route["zero_capacity_actors"] = ["Młynar"]
        route["background_skills"] = [
            {"name": "Młynar", "slot": "below-hub", "sp_cost": 42, "maximum": 3}
        ]
        deploy("Crabbie Pumpie", "pump", item_id="sandbox_1_tactical_15", maximum=1)
        deploy(
            "Sawing Harvester Hub",
            "hub",
            item_id="sandbox_1_tactical_16",
            maximum=1,
            fixed_direction="Down",
        )
        deploy("Młynar", "below-hub")
        deploy(defender, "left-hub")
        actions.append(
            {
                "action": "wait_water",
                "pumps": 1,
                "maximum_game_seconds": 180,
                "remaining_floor": 25,
            }
        )
    else:
        if not calibration.get("healing_coverage_evidence"):
            raise CheckpointError(
                "Both hub defender/healer groups require reviewed healing coverage"
            )
        route["hub_healing_coverage"] = validate_hub_healing(calibration, pack)
        route["required_squad"] = list(HUB_SQUAD)
        deploy(
            "Sawing Harvester Hub",
            "lower-hub",
            item_id="sandbox_1_tactical_16",
            maximum=2,
        )
        deploy("Spot", "lower-defender")
        deploy("Ansel", "lower-healer")
        deploy(
            "Sawing Harvester Hub",
            "upper-hub",
            item_id="sandbox_1_tactical_16",
            maximum=2,
        )
        deploy("Beagle", "upper-defender")
        deploy("Hibiscus", "upper-healer")
        actions.append(
            {
                "action": "wait_until_remaining",
                "remaining": 30,
                "maximum_game_seconds": 180,
            }
        )
    route.update(source_formation_requirements(pack, route.get("required_squad", [])))
    actions.append({"action": "finish"})
    return route


def validate_compiled(route, pack=None):
    """Reuse the actual route validator; no parallel action-schema implementation."""
    pack = Path(pack) if pack else default_pack()
    anchor_spec(pack, route)
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        (stage / "routes").mkdir()
        (stage / "campaign").mkdir()
        shutil.copy2(pack / "player.json", stage / "player.json")
        shutil.copy2(pack / "campaign/stages.json", stage / "campaign/stages.json")
        manifest = route["anchor_manifest"]
        target = stage / manifest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pack / manifest, target)
        (stage / "routes" / f"{route['id']}.json").write_text(
            json.dumps(route), encoding="utf8"
        )
        return load_profile(stage, route["id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", type=int, required=True)
    parser.add_argument("--act", type=int, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        calibration = json.loads(args.calibration.read_text(encoding="utf-8-sig"))
        route = compile_route(args.day, args.act, calibration, args.pack)
        validate_compiled(route, args.pack)
    except (CheckpointError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    args.output.write_text(
        json.dumps(route, indent=2, ensure_ascii=False) + chr(10), encoding="utf8"
    )
    print(
        json.dumps(
            {
                "route": str(args.output),
                "autoplay_enabled": False,
                "game_connected": False,
            }
        )
    )


if __name__ == "__main__":
    main()
