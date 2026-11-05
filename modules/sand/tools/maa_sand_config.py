"""Validated Sand route data; no emulator or native runtime imports."""

import hashlib
import json
from pathlib import Path

# Exact selected-skill identities from the local max-level guide references.
REPEAT_SKILLS = {
    "Młynar": ("Unbrilliant Glory", 42),
    "Saileach": ("Support γ", 26),
    "Executor the Ex Foedere": ("Damnatus Ex Foedere", 24),
    "Nian": ("Iron Defense", 85),
    "Eyjafjalla": ("Volcano", 80),
    "Gavial the Invincible": ("Soul of the Jungle", 35),
}


WATER_STAGES = {
    "sandbox_1_56": "Straight Into the Abyss",
    "sandbox_1_40": "Within Range",
}


REVIEWED_FIELD_TOOLS = {
    "sandbox_1_tactical_15": ("Crabbie Pumpie", "trap_403_wfactory"),
    "sandbox_1_tactical_16": ("Sawing Harvester Hub", "trap_401_xbfato"),
}


class CheckpointError(RuntimeError):
    pass


class LoadReadError(CheckpointError):
    pass


def validate_harvest_skill(name, enabled):
    if type(enabled) is not bool:
        raise CheckpointError("Harvest skill activation must be an explicit boolean")
    # The supported Mountain setup selects S2. Its reduced own-tile range cannot
    # chop adjacent trees; raid stance activation has a separate policy.
    if name == "Mountain" and enabled:
        raise CheckpointError(
            "Keep Mountain Sweeping Stance off when harvesting adjacent trees"
        )


def validate_formation_skills(requirements, squad, minimum_ranks=None):
    """Check selected-skill requirements separately from rank and ownership."""
    if not isinstance(requirements, dict) or any(
        not isinstance(name, str) or type(skill) is not int or skill not in (1, 2, 3)
        for name, skill in requirements.items()
    ):
        raise CheckpointError(
            "Unsupported formation skill requirement; native evidence is needed"
        )
    if any(name not in squad for name in requirements):
        raise CheckpointError(
            "Formation skill actor must belong to the requested squad"
        )
    ranks = {} if minimum_ranks is None else minimum_ranks
    if not isinstance(ranks, dict) or any(
        name not in requirements or type(rank) is not int or rank not in (7, 10)
        for name, rank in ranks.items()
    ):
        raise CheckpointError(
            "Formation rank requirements need supported rank 7 or mastery 3 on a required skill"
        )


def validate_formation_power(levels, elites, squad):
    if (
        not isinstance(levels, dict)
        or any(
            name not in squad or type(level) is not int or not 1 <= level <= 90
            for name, level in levels.items()
        )
        or not isinstance(elites, dict)
        or any(
            name not in levels or type(elite) is not int or elite not in (0, 1, 2)
            for name, elite in elites.items()
        )
    ):
        raise CheckpointError(
            "Formation power requirements need exact squad actors, levels1-90 and supported promotions"
        )


def default_pack():
    root = Path(__file__).resolve().parents[1]
    bundled = root / "pack"
    return bundled if bundled.is_dir() else root / "patches/maa-sand-player"


def validate_skill_specs(specs, squad, slots, deployed=None):
    if not isinstance(specs, list) or not specs:
        raise CheckpointError("Repeated skills need explicit actor specifications")
    actors = set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != {
            "name",
            "slot",
            "sp_cost",
            "maximum",
        }:
            raise CheckpointError("Invalid repeated-skill specification")
        name, slot = spec["name"], spec["slot"]
        if (
            not isinstance(name, str)
            or not isinstance(slot, str)
            or name in actors
            or name not in squad
            or slot not in slots
            or type(spec["sp_cost"]) is not int
            or not 1 <= spec["sp_cost"] <= 100
            or type(spec["maximum"]) is not int
            or not 1 <= spec["maximum"] <= 5
        ):
            raise CheckpointError(
                "Repeated skill requires unique known actors/slots and bounded cycles"
            )
        if deployed is not None and deployed.get(slot) != name:
            raise CheckpointError("Repeated skill actor has not been deployed")
        if name not in REPEAT_SKILLS or spec["sp_cost"] != REPEAT_SKILLS[name][1]:
            raise CheckpointError(
                "Repeated skill actor/cost is outside the reviewed guide roster"
            )
        actors.add(name)


def camera_slots(spec):
    slots = set(spec.get("normal_points", {}))
    if not slots or slots != set(spec.get("side_points", {})):
        raise CheckpointError("Both camera poses need the same named slots")
    for camera in ("normal_points", "side_points"):
        for point in spec[camera].values():
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(type(x) is not int for x in point)
                or not 430 < point[0] < 1000
                or not 80 < point[1] < 580
            ):
                raise CheckpointError("Route tile is outside the calibrated viewport")
    return slots


def load_profile(pack, route=None, *, phase=None):
    pack = Path(pack)
    profile = json.loads((pack / "player.json").read_text(encoding="utf8"))
    name = route or profile["default_route"]
    if (
        not isinstance(name, str)
        or not name
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name)
    ):
        raise CheckpointError("Invalid route identifier")
    plan = json.loads((pack / "routes" / (name + ".json")).read_text(encoding="utf8"))
    phases = plan.get("calibration_phases", {})
    if not isinstance(phases, dict):
        raise CheckpointError("Calibration phases must be named geometry records")
    for phase_name, spec in phases.items():
        if (
            not isinstance(phase_name, str)
            or not phase_name
            or any(
                c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in phase_name
            )
            or not isinstance(spec, dict)
            or set(spec) != {"normal_points", "side_points", "anchor_manifest"}
        ):
            raise CheckpointError(
                "Camera phases may change only pinned geometry and anchors"
            )
        camera_slots(spec)
        anchor_spec(pack, {**plan, **spec})
    if phase is not None:
        if not isinstance(phase, str) or phase not in phases:
            raise CheckpointError("Unknown calibration phase")
        plan.update(phases[phase])
        plan["active_phase"] = phase
    if plan.get("schema_version") != 1 or plan.get("id") != name:
        raise CheckpointError("Unsupported route schema or mismatched identifier")
    if plan.get("theme") != "Tales":
        raise CheckpointError("No calibrated navigator for this theme/stage")
    if plan.get("stage") != "Shrubbery Galore" or "stage_id" in plan:
        if not plan.get("stage_id"):
            raise CheckpointError("Route stage requires its canonical campaign ID")
        catalog = json.loads((pack / "campaign/stages.json").read_text(encoding="utf8"))
        stage = catalog["stages"].get(plan.get("stage_id"))
        if not stage or stage["english"] != plan.get("stage"):
            raise CheckpointError(
                "Route stage name/ID does not match the campaign catalog"
            )
        if plan["stage_id"] != "sandbox_1_01" and not plan.get("anchor_manifest"):
            raise CheckpointError(
                "Other campaign stages require their own camera anchor manifest"
            )

    if plan.get("registration_mask") not in (None, "jungle") or (
        plan.get("registration_mask") == "jungle"
        and plan.get("stage_id") != "sandbox_1_38"
    ):
        raise CheckpointError(
            "Extended terrain registration is calibrated only for Jagged Jungle"
        )
    if type(plan.get("autoplay_enabled")) is not bool:
        raise CheckpointError("Route must explicitly declare autoplay eligibility")
    if plan.get("coordinate_system") != "registered-1280x720":
        raise CheckpointError("Source-image guide coordinates cannot be executed")
    slots = camera_slots(plan)
    for flag in ("verify_facing_center", "reuse_operator_panel", "keep_operator_panel"):
        if flag in plan and (
            type(plan[flag]) is not bool
            or (plan[flag] and plan.get("stage_id") != "sandbox_1_40")
        ):
            raise CheckpointError(
                "Observed operator-panel policy is scoped to Within Range"
            )
    squad = plan.get("required_squad", [])
    empty_water = plan.get("squad_mode") == "empty-pumps"
    if empty_water and (
        squad != []
        or plan.get("stage_id") != "sandbox_1_56"
        or plan["autoplay_enabled"]
    ):
        raise CheckpointError(
            "Empty-pump squad requires experimental Abyss route with no operators"
        )
    if (
        not isinstance(squad, list)
        or (not squad and not empty_water)
        or any(not isinstance(x, str) or not x for x in squad)
        or len(set(squad)) != len(squad)
    ):
        raise CheckpointError("Required squad must contain unique operator names")
    validate_formation_skills(
        plan.get("required_formation_skills", {}),
        squad,
        plan.get("required_formation_ranks", {}),
    )
    validate_formation_power(
        plan.get("required_formation_levels", {}),
        plan.get("required_formation_elites", {}),
        squad,
    )
    zero_capacity = plan.get("zero_capacity_actors", [])
    if not isinstance(zero_capacity, list) or any(
        name not in squad for name in zero_capacity
    ):
        raise CheckpointError("Zero-capacity actors must belong to the required squad")
    background = plan.get("background_skills", [])
    if not isinstance(background, list):
        raise CheckpointError("Background skills must be an explicit list")
    if background:
        validate_skill_specs(background, squad, slots)
    floor = plan.get("background_skill_remaining_floor", 25)
    if type(floor) is not int or not 25 <= floor <= 240:
        raise CheckpointError(
            "Background skill checks must preserve at least25 seconds"
        )
    wood_target = plan.get("banked_wood_target")
    if wood_target is not None and (
        type(wood_target) is not int
        or not 1 <= wood_target <= 100
        or plan.get("stage_id") not in ("sandbox_1_01", "sandbox_1_38", "sandbox_1_40")
        or plan["autoplay_enabled"]
    ):
        raise CheckpointError(
            "Targeted wood rotation requires an experimental wood route and bounded target"
        )
    rotation_minimum = rotation_trips = 0
    steps = plan.get("steps", [])
    if not steps or steps[-1] != {"action": "finish"}:
        raise CheckpointError("Route must end with a settlement step")
    deployed, carrying = {}, set()
    tool_slots, tool_counts, tool_budgets = {}, {}, {}
    allowed = {
        "phase": {"action", "name"},
        "wait_dp": {"action", "minimum", "remaining_floor"},
        "wait_operator": {"action", "name", "maximum_game_seconds", "remaining_floor"},
        "carrier_trip": {"action", "name", "slot", "direction", "minimum", "timeout"},
        "wait_until_remaining": {"action", "remaining", "maximum_game_seconds"},
        "deploy": {"action", "name", "slot", "direction"},
        "deploy_tool": {"action", "item_id", "slot", "direction", "maximum"},
        "collect": {"action", "name", "slot", "minimum", "timeout", "skill_once"},
        "bank": {"action", "name", "slot"},
        "recall": {"action", "name", "slot"},
        "finish": {"action"},
        "wait_water": {"action", "pumps", "maximum_game_seconds", "remaining_floor"},
        "wait_hunting": {
            "action",
            "pumps",
            "minimum_base_energy",
            "maximum_game_seconds",
            "remaining_floor",
        },
        "maintain_skills": {"action", "skills", "duration", "remaining_floor"},
    }
    for i, step in enumerate(steps):
        action = step.get("action")
        if action not in allowed or set(step) != allowed[action]:
            raise CheckpointError(f"Unknown or incomplete route step {i}")
        if action == "phase":
            if step["name"] not in phases:
                raise CheckpointError(
                    "Route step requires a declared calibration phase"
                )
            slots = camera_slots(phases[step["name"]])
            if carrying or not (set(deployed) | set(tool_slots)).issubset(slots):
                raise CheckpointError(
                    "Camera phase must preserve active slots and bank collected cargo first"
                )
        elif action == "wait_dp":
            if (
                any(type(step[k]) is not int for k in ("minimum", "remaining_floor"))
                or not 1 <= step["minimum"] <= 99
                or not 0 <= step["remaining_floor"] <= 240
            ):
                raise CheckpointError("Invalid DP wait bounds")
        elif action == "carrier_trip":
            if (
                wood_target is None
                or step["name"] not in squad
                or step["name"] in zero_capacity
                or step["name"] in deployed.values()
                or step["slot"] not in slots
                or step["slot"] in deployed
                or step["slot"] in tool_slots
                or carrying
                or step["direction"] not in ("Left", "Right", "Up", "Down")
                or type(step["minimum"]) is not int
                or not 1 <= step["minimum"] <= 6
                or type(step["timeout"]) is not int
                or not 1 <= step["timeout"] <= 120
            ):
                raise CheckpointError(
                    "Carrier trip needs an inactive carrier, vacant tile, target and bounded load wait"
                )
            rotation_trips += 1
            rotation_minimum += step["minimum"]
        elif action == "wait_operator":
            if (
                step["name"] not in squad
                or step["name"] in deployed.values()
                or type(step["maximum_game_seconds"]) is not int
                or not 1 <= step["maximum_game_seconds"] <= 120
                or type(step["remaining_floor"]) is not int
                or not 25 <= step["remaining_floor"] <= 240
            ):
                raise CheckpointError("Invalid named carrier readiness wait")
        elif action == "wait_until_remaining":
            if (
                type(step["remaining"]) is not int
                or not 25 <= step["remaining"] <= 180
                or type(step["maximum_game_seconds"]) is not int
                or not 1 <= step["maximum_game_seconds"] <= 180
            ):
                raise CheckpointError(
                    "Passive harvesting needs bounded observed-clock wait and exit reserve"
                )
        elif action == "deploy_tool":
            item_id, slot, maximum = step["item_id"], step["slot"], step["maximum"]
            if (
                not isinstance(item_id, str)
                or item_id not in REVIEWED_FIELD_TOOLS
                or not isinstance(slot, str)
                or slot not in slots
                or slot in deployed
                or slot in tool_slots
                or step["direction"] not in (None, "Left", "Right", "Up", "Down")
                or type(maximum) is not int
                or not 1 <= maximum <= 2
            ):
                raise CheckpointError(
                    "Tool step requires a reviewed item, vacant calibrated slot and bounded budget"
                )
            if plan["autoplay_enabled"]:
                raise CheckpointError(
                    "Tool routes still require bounded experimental validation"
                )
            if item_id in tool_budgets and tool_budgets[item_id] != maximum:
                raise CheckpointError(
                    "Tool deployment budget cannot change within an operation"
                )
            tool_counts[item_id] = tool_counts.get(item_id, 0) + 1
            if tool_counts[item_id] > maximum:
                raise CheckpointError("Tool route exceeds its operation budget")
            tool_budgets[item_id] = maximum
            tool_slots[slot] = item_id
        elif action in ("wait_water", "wait_hunting"):
            if (
                plan.get("stage_id") not in WATER_STAGES
                or i != len(steps) - 2
                or carrying
                or (plan.get("stage_id") == "sandbox_1_40" and step["pumps"] != 1)
                or type(step["pumps"]) is not int
                or step["pumps"] not in (1, 2)
                or type(step["maximum_game_seconds"]) is not int
                or not 1 <= step["maximum_game_seconds"] <= 180
                or type(step["remaining_floor"]) is not int
                or not 25 <= step["remaining_floor"] <= 240
            ):
                raise CheckpointError(
                    "Water completion needs the reviewed water stage, final harvest step and bounded reserve"
                )
            if action == "wait_hunting" and (
                plan.get("stage_id") != "sandbox_1_56"
                or step["pumps"] != 1
                or type(step["minimum_base_energy"]) is not int
                or not 1 <= step["minimum_base_energy"] <= 1000
            ):
                raise CheckpointError(
                    "Hunting completion requires the source one-pump map and bounded food target"
                )
            if tool_counts.get("sandbox_1_tactical_15", 0) != step["pumps"]:
                raise CheckpointError(
                    "Water route must explicitly deploy its planned pumps before waiting"
                )
        elif action == "maintain_skills":
            if (
                type(step["duration"]) is not int
                or not 1 <= step["duration"] <= 120
                or type(step["remaining_floor"]) is not int
                or not 25 <= step["remaining_floor"] <= 240
            ):
                raise CheckpointError("Invalid repeated-skill time budget")
            validate_skill_specs(step["skills"], squad, slots, deployed)
        elif action in ("deploy", "collect", "bank", "recall"):
            name, slot = step["name"], step["slot"]
            if name not in squad or slot not in slots:
                raise CheckpointError("Step refers to an unknown operator or tile")
            if action == "deploy":
                if (
                    slot in deployed
                    or slot in tool_slots
                    or step["direction"] not in ("Left", "Right", "Up", "Down")
                ):
                    raise CheckpointError("Invalid facing or occupied route tile")
                deployed[slot] = name
            elif deployed.get(slot) != name:
                raise CheckpointError(
                    "Collection/banking requires the matching deployment"
                )
            elif action == "collect":
                if (
                    type(step["minimum"]) is not int
                    or not 1 <= step["minimum"] <= 36
                    or type(step["timeout"]) is not int
                    or not 1 <= step["timeout"] <= 240
                    or type(step["skill_once"]) is not bool
                ):
                    raise CheckpointError("Invalid collection limits")
                validate_harvest_skill(name, step["skill_once"])
                carrying.add((name, slot))
            elif action == "recall":
                if (name, slot) in carrying:
                    raise CheckpointError(
                        "Bank the explicitly collected load before recalling"
                    )
                del deployed[slot]
            else:
                if (name, slot) not in carrying:
                    raise CheckpointError(
                        "Banking requires an observed collection step"
                    )
                carrying.remove((name, slot))
                del deployed[slot]
        elif i != len(steps) - 1:
            raise CheckpointError("Settlement must be the final step")
    if wood_target is not None and (
        not 1 <= rotation_trips <= 10
        or rotation_minimum < wood_target
        or carrying
        or tool_counts
    ):
        raise CheckpointError(
            "Wood rotation needs up to ten trips sufficient for its target, without tools or unbanked cargo"
        )
    if empty_water and (
        tool_counts != {"sandbox_1_tactical_15": 2}
        or not any(
            step.get("action") == "wait_water" and step.get("pumps") == 2
            for step in steps
        )
    ):
        raise CheckpointError(
            "Empty water route requires exactly two pumps and observed water20 completion"
        )
    if "anchor_manifest" in plan:
        anchor_spec(pack, plan)
    return {**profile, **plan}


def require_executable(profile, allow_experimental=False):
    if not profile["autoplay_enabled"] and not allow_experimental:
        raise CheckpointError(
            "Route is experimental: "
            + profile["validation_status"]
            + ". Use --allow-experimental only for a bounded validation run."
        )


def anchor_spec(pack, profile=None):
    """Resolve pinned camera assets for this route, with legacy default support."""
    pack = Path(pack).resolve()
    profile = profile or {}
    reference = profile.get("anchor_manifest", "anchors.json")
    if not isinstance(reference, str) or not reference:
        raise CheckpointError("Camera anchor manifest must be a pack-relative path")
    target = (pack / reference).resolve()
    if not target.is_relative_to(pack):
        raise CheckpointError("Camera anchor manifest cannot escape the route pack")
    spec = json.loads(target.read_text(encoding="utf8"))
    if "anchor_manifest" in profile and (
        spec.get("schema_version") != 1
        or not profile.get("stage_id")
        or spec.get("stage_id") != profile["stage_id"]
    ):
        raise CheckpointError("Route camera anchors must bind the exact stage ID")
    if not isinstance(spec.get("location"), str) or not spec["location"]:
        raise CheckpointError("Camera anchor location is missing")
    required = profile.get("anchors", {"idle": "idle.png", "side": "side.png"})
    if not isinstance(required, dict) or set(required) != {"idle", "side"}:
        raise CheckpointError("Route needs idle and selected-camera anchor filenames")
    digests = spec.get("sha256")
    if not isinstance(digests, dict) or not digests:
        raise CheckpointError("Camera anchors require pinned hashes")
    for name, digest in digests.items():
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or Path(name).name != name
            or name in (".", "..")
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise CheckpointError("Invalid camera anchor filename or hash")
    if any(
        not isinstance(name, str) or name not in digests for name in required.values()
    ):
        raise CheckpointError("Every route camera anchor must have a pinned hash")
    return spec


def verify_anchors(pack, assets, profile=None):
    spec = anchor_spec(pack, profile)
    result = {}
    for name, expected in spec["sha256"].items():
        path = Path(assets) / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise CheckpointError(f"Missing or changed calibration anchor: {name}")
        result[name] = expected
    return result
