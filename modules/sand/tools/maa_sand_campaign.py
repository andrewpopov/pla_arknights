"""Offline campaign advice from observed state; never imports or connects to MaaCore."""

import argparse
import json
from pathlib import Path

from maa_sand_config import CheckpointError, default_pack
from maa_sand_food import (
    load_food_catalog,
    observed_energy,
    plan_drinks,
    validate_stored_energy,
)
from maa_sand_levels import level_advice
from maa_sand_tools import load_tool_catalog, tool_mechanics_advice


def load_campaign(pack=None):
    plan = json.loads(
        (
            (Path(pack) if pack else default_pack()) / "campaign/early-days-1-6.json"
        ).read_text(encoding="utf8")
    )
    if plan.get("schema_version") != 1 or plan.get("autoplay_enabled") is not False:
        raise CheckpointError("Campaign must remain an offline version-1 plan")
    expected = [(d, a) for d in range(1, 7) for a in (1, 2)]
    if [(s["day"], s["act"]) for s in plan["steps"]] != expected:
        raise CheckpointError(
            "Campaign needs exactly two ordered Acts for each Day 1–6"
        )
    catalog = json.loads(
        ((Path(pack) if pack else default_pack()) / "campaign/stages.json").read_text(
            encoding="utf8"
        )
    )
    if catalog.get("schema_version") != 1 or catalog.get("theme") != "Tales":
        raise CheckpointError("Unsupported canonical stage catalog")
    plan["_pack"] = str(Path(pack) if pack else default_pack())
    plan["tool_catalog"] = load_tool_catalog(pack)
    plan["food_catalog"] = load_food_catalog(pack)
    known_tools = {item["name"] for item in plan["tool_catalog"].values()}
    for step in plan["steps"]:
        if step["source"] not in plan["sources"] or step["min_hq"] not in (1, 2):
            raise CheckpointError("Invalid campaign source or HQ prerequisite")
        if any(name not in known_tools for name in step["required_tools"]):
            raise CheckpointError(
                "Campaign tool name does not match the current game export"
            )
        if (
            type(step.get("expedition_required")) is not bool
            or type(step.get("empty_squad_supported")) is not bool
        ):
            raise CheckpointError(
                "Campaign must declare expedition and empty-squad admission"
            )
        stage_id = step.get("stage_id")
        if stage_id is None:
            if step.get("stage") is not None:
                raise CheckpointError(
                    "Named campaign stage requires its canonical game ID"
                )
        else:
            stage = catalog["stages"].get(stage_id)
            if (
                not stage
                or step.get("stage") != stage["english"]
                or step.get("source_stage") not in (stage["english"], stage["japanese"])
            ):
                raise CheckpointError(
                    "Campaign stage name/ID does not match the game export"
                )
        for key in (
            "deployment_reference",
            "dialogue_reference",
            "completion_reference",
            "encounter_reference",
        ):
            reference = step.get(key)
            if (
                reference
                and not ((Path(pack) if pack else default_pack()) / reference).is_file()
            ):
                raise CheckpointError(f"Campaign {key} is missing")
    return plan


def integer(state, key, minimum=0, maximum=100000):
    value = state.get(key)
    if type(value) is not int or not minimum <= value <= maximum:
        raise CheckpointError(
            f"{key} must be an observed integer in {minimum}..{maximum}"
        )
    return value


def advise(state, plan=None, *, execution=False):
    plan = plan or load_campaign()
    day = integer(state, "day", 1, 6)
    used = integer(state, "acts_used", 0, 2)
    hq = integer(state, "hq", 1, 10)
    wood, water = (integer(state, k) for k in ("wood", "water"))
    stone = integer(state, "stone") if "stone" in state else None
    stock = integer(state, "drinks")
    stored_energy = (
        integer(state, "stored_drink_energy", 0, 59)
        if "stored_drink_energy" in state
        else 0
    )
    stored_verified = state.get("stored_drink_energy_verified", False)
    validate_stored_energy(stored_energy, stored_verified)
    if stored_energy and (
        not isinstance(state.get("stored_drink_energy_image"), str)
        or not state["stored_drink_energy_image"].strip()
    ):
        raise CheckpointError(
            "Positive stored energy needs its observed idle-cooking image"
        )
    food_catalog = plan.get("food_catalog") or load_food_catalog()
    if "raw_food_inventory" in state:
        if type(state.get("raw_food_inventory_complete")) is not bool:
            raise CheckpointError(
                "Declare whether observed raw-food inventory is complete"
            )
        food = observed_energy(
            state["raw_food_inventory"],
            food_catalog,
            multiplier=integer(state, "food_energy_multiplier", 1, 2),
        )
        if (
            state["raw_food_inventory_complete"]
            and "raw_food_energy" in state
            and integer(state, "raw_food_energy") != food
        ):
            raise CheckpointError(
                "Food energy total disagrees with the observed ingredient counts"
            )
    else:
        food = integer(state, "raw_food_energy")
    size = integer(state, "squad_size", 0, 12)
    squad, tired = state.get("squad"), state.get("tired")
    for names in (squad, tired):
        if (
            not isinstance(names, list)
            or any(not isinstance(n, str) or not n for n in names)
            or len(set(names)) != len(names)
        ):
            raise CheckpointError("Squad and tired must contain unique observed names")
    if len(squad) != size:
        raise CheckpointError("Squad size disagrees with observed roster")
    tools = state.get("tools", {})
    if not isinstance(tools, dict) or any(
        not isinstance(k, str) or not k or type(v) is not int or not 0 <= v <= 99
        for k, v in tools.items()
    ):
        raise CheckpointError("Tools must contain observed nonnegative integer counts")
    threat = state.get("threat")
    if threat not in ("unknown", "clear", "urgent", "later"):
        raise CheckpointError("Threat must be unknown, clear, urgent or later")
    for key in ("settled", "snapshot_current"):
        if type(state.get(key)) is not bool:
            raise CheckpointError(f"{key} must be explicitly true or false")
    expedition = used < 2 and (
        threat == "urgent" or plan["steps"][(day - 1) * 2 + used]["expedition_required"]
    )
    need = (2 if size <= 6 else 3) if expedition else 0
    result = {
        "game_connected": False,
        "autoplay_enabled": False,
        "day": day,
        "acts_remaining": 2 - used,
        "status": "review",
        "energy": {
            "raw_energy_observed": food,
            "raw_inventory_complete": state.get("raw_food_inventory_complete"),
            "food_energy_multiplier": state.get("food_energy_multiplier"),
            "stored_energy_observed": stored_energy,
            "stored_energy_verified": stored_verified,
            "stored_energy_image": state.get("stored_drink_energy_image"),
            "drinks_required": need,
            "drinks_to_prepare": max(0, need - stock),
            "raw_energy_shortfall": max(0, (need - stock) * 60 - stored_energy - food),
        },
        "construction": {
            name: {
                "deficit": {
                    k: max(0, cost - {"wood": wood, "water": water}[k])
                    for k, cost in costs.items()
                },
                "costs_require_live_confirmation": True,
            }
            for name, costs in plan["construction"].items()
        },
        "blockers": [],
        "next": None,
        "day_end": "Review remaining Acts, raids, payout and construction; no automatic advance.",
    }
    if "food_spendable_ids" in state:
        if "raw_food_inventory" not in state:
            raise CheckpointError(
                "Ingredient allocation requires an observed raw-food inventory"
            )
        result["ingredient_plan"] = plan_drinks(
            state["raw_food_inventory"],
            stock,
            need,
            spendable_ids=state["food_spendable_ids"],
            multiplier=state["food_energy_multiplier"],
            reserves=state.get("food_reserves"),
            catalog=food_catalog,
            complete=state["raw_food_inventory_complete"],
            stored_energy=stored_energy,
            stored_energy_verified=stored_verified,
        )
        result["energy"]["raw_energy_shortfall"] = result["ingredient_plan"][
            "additional_verified_energy_needed"
        ]
        result["energy"]["raw_energy_source"] = (
            "observed_spendable_ingredients_after_reserves"
        )
        result["energy"]["raw_energy_spendable"] = result["ingredient_plan"][
            "spendable_energy"
        ]
    blockers = result["blockers"]
    if not state["snapshot_current"]:
        blockers.append(
            "Historical snapshot: refresh state when app control is returned."
        )
    if not state["settled"]:
        blockers.append("Await verified settlement; do not credit expected harvests.")
    if used == 2:
        blockers.append("Both daily Acts consumed; review day end separately.")
    if threat == "unknown":
        blockers.append(
            "Inspect raid arrival and node identity; a hostile icon alone is insufficient."
        )
    if used < 2:
        step = dict(plan["steps"][(day - 1) * 2 + used])
        if threat == "urgent":
            step.update(
                objective="raid",
                source_stage=None,
                stage=None,
                stage_id=None,
                deployment_reference=None,
                dialogue_reference=None,
                completion_reference=None,
                encounter_reference=None,
                required_tools={},
                expedition_required=True,
                empty_squad_supported=False,
                tools_only_supported=False,
                notes="Urgent observed raid overrides the calendar. Verify reachable interception map.",
            )
        result["next"] = step
        if step["stage_id"] is not None:
            result["level_reference"] = level_advice(
                step["stage_id"], plan.get("_pack")
            )
        result["tool_mechanics"] = tool_mechanics_advice(
            step["required_tools"], plan.get("_pack")
        )
        result["tool_shortfall"] = {
            name: max(0, count - tools.get(name, 0))
            for name, count in step["required_tools"].items()
        }
        recipes = {item["name"]: item for item in plan["tool_catalog"].values()}
        materials = {}
        for name, missing in result["tool_shortfall"].items():
            if not missing:
                continue
            for material, cost in recipes[name]["materials"].items():
                materials[material] = materials.get(material, 0) + missing * cost
        owned = {"wood": wood, "water": water, "stone": stone}
        result["tool_crafting"] = {
            "materials_required": materials,
            "material_shortfall": {
                name: (max(0, cost - owned[name]) if owned[name] is not None else None)
                for name, cost in materials.items()
            },
            "unverified_tool_inventory": [
                name for name in step["required_tools"] if name not in tools
            ],
            "live_recipe_confirmation_required": True,
        }
        if any(
            value is None or value > 0
            for value in result["tool_crafting"]["material_shortfall"].values()
        ):
            blockers.append(
                "Tool batch materials are insufficient or unobserved; verify before spending."
            )
        if any(result["tool_shortfall"].values()):
            blockers.append(
                "Confirm or craft the required tools; missing inventory is not ownership."
            )
        if expedition and size == 0 and not step["empty_squad_supported"]:
            blockers.append(
                "Empty squad is unsupported for this expedition; use the source visit/water cases only."
            )
        if hq < step["min_hq"] and threat != "urgent":
            blockers.append(
                "Guide infrastructure is unavailable: recover HQ2 prerequisites first."
            )
        if (
            step["objective"] == "raid"
            and threat != "urgent"
            and state.get("raid_reachable") is not True
        ):
            blockers.append(
                "Guide raid timing is illustrative: choose an observed safe alternative."
            )
        unavailable = sorted(set(squad) & set(tired))
        if expedition and unavailable:
            blockers.append("Replace tired operators: " + ", ".join(unavailable))
        if stock < need:
            if result["energy"]["raw_energy_shortfall"]:
                if state.get("raw_food_inventory_complete") is False:
                    blockers.append(
                        "Observed food does not yet fund the complete trip; verify remaining raw ingredients before spending."
                    )
                else:
                    blockers.append(
                        "Insufficient food for the complete trip; do not spend a partial drink preview."
                    )
            else:
                blockers.append(
                    "Confirm one bounded raw-ingredient preparation before expedition."
                )
        if not execution and step["objective"] == "encounter":
            blockers.append(
                "Identify the world event and review its options before spending an Act; this plan issues no inputs."
            )
        elif not execution:
            blockers.append(
                "Map execution requires a separately calibrated, validated route; this plan issues no inputs."
            )
    return result


def prepare_campaign_tools(
    state, crafter, plan=None, *, reserve_wood=0, reserve_stone=0
):
    """Prepare only the next observed campaign Act; never launch it or advance days."""
    advice = advise(state, plan)
    if not state["snapshot_current"] or not state["settled"]:
        raise CheckpointError(
            "Campaign preparation requires current settled observations"
        )
    if state["threat"] == "unknown":
        raise CheckpointError("Resolve raid timing before preparing calendar tools")
    step = advice["next"]
    if step is None or not step["required_tools"]:
        return {
            "status": "no_tools_for_current_act",
            "day": state["day"],
            "inventory_updated": False,
            "expedition_started": False,
        }
    if advice["energy"]["raw_energy_shortfall"]:
        raise CheckpointError(
            "Fund the complete campaign trip before spending its tool materials"
        )
    if state["hq"] < step["min_hq"]:
        raise CheckpointError("Next campaign tool batch requires its HQ prerequisites")
    result = crafter.prepare_batch(
        step["required_tools"],
        observed_hq=state["hq"],
        reserve_wood=reserve_wood,
        reserve_stone=reserve_stone,
    )
    return {
        **result,
        "campaign": {
            "day": step["day"],
            "act": step["act"],
            "stage_id": step["stage_id"],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state", type=Path, required=True, help="Explicit saved observation JSON"
    )
    parser.add_argument("--pack", type=Path, default=default_pack())
    args = parser.parse_args()
    try:
        result = advise(
            json.loads(args.state.read_text(encoding="utf8")), load_campaign(args.pack)
        )
    except (OSError, ValueError, KeyError, TypeError, CheckpointError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
