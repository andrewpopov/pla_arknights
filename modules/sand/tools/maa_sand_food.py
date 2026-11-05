"""Exact raw-ingredient energy budgets; no cooking or inventory mutation."""

import json
from pathlib import Path

from maa_sand_config import CheckpointError, default_pack


def load_food_catalog(pack=None):
    data = json.loads(
        ((Path(pack) if pack else default_pack()) / "campaign/food.json").read_text(
            encoding="utf8"
        )
    )
    if (
        data.get("schema_version") != 1
        or data.get("energy_per_drink") != 60
        or data.get("cooked_food_included") is not False
        or data.get("selection_inputs_enabled") is not False
    ):
        raise CheckpointError("Unsupported raw-food energy catalog")
    items = data["items"]
    if not items or any(
        r.get("id") != key
        or not r.get("name")
        or type(r.get("energy")) is not int
        or not 1 <= r["energy"] <= 300
        for key, r in items.items()
    ):
        raise CheckpointError("Invalid raw-food energy record")
    return items


def validate_inventory(inventory, catalog):
    if not isinstance(inventory, dict) or any(
        key not in catalog or type(n) is not int or not 0 <= n <= 999
        for key, n in inventory.items()
    ):
        raise CheckpointError(
            "Raw-food inventory needs exact exported IDs and observed counts"
        )


def observed_energy(inventory, catalog=None, *, multiplier):
    catalog = catalog or load_food_catalog()
    validate_inventory(inventory, catalog)
    if type(multiplier) is not int or multiplier not in (1, 2):
        raise CheckpointError(
            "Food conversion requires an explicitly verified multiplier1 or2"
        )
    return multiplier * sum(catalog[key]["energy"] * n for key, n in inventory.items())


def validate_stored_energy(energy, verified):
    if (
        type(energy) is not int
        or not 0 <= energy < 60
        or type(verified) is not bool
        or (energy > 0 and not verified)
    ):
        raise CheckpointError(
            "Stored drink energy needs an explicitly verified partial bottle from0 through59"
        )


def plan_drinks(
    inventory,
    stock,
    required,
    *,
    spendable_ids,
    multiplier,
    reserves=None,
    catalog=None,
    complete=False,
    stored_energy=0,
    stored_energy_verified=False,
):
    catalog = catalog or load_food_catalog()
    validate_inventory(inventory, catalog)
    if type(multiplier) is not int or multiplier not in (1, 2):
        raise CheckpointError(
            "Food conversion requires an explicitly verified multiplier1 or2"
        )
    validate_stored_energy(stored_energy, stored_energy_verified)
    values = {key: r["energy"] * multiplier for key, r in catalog.items()}
    if (
        type(stock) is not int
        or not 0 <= stock <= 99
        or type(required) is not int
        or not 0 <= required <= 3
        or type(complete) is not bool
    ):
        raise CheckpointError(
            "Drink planning requires explicit observed stock and a bounded trip target"
        )
    if (
        not isinstance(spendable_ids, list)
        or any(not isinstance(key, str) for key in spendable_ids)
        or len(set(spendable_ids)) != len(spendable_ids)
        or any(key not in inventory for key in spendable_ids)
    ):
        raise CheckpointError("Every spendable ingredient must be explicitly observed")
    reserves = {} if reserves is None else reserves
    if not isinstance(reserves, dict) or any(
        key not in inventory or type(n) is not int or not 0 <= n <= inventory[key]
        for key, n in reserves.items()
    ):
        raise CheckpointError("Ingredient reserves require observed quantities")
    available = {
        key: inventory[key] - reserves.get(key, 0) for key in sorted(spendable_ids)
    }
    drink_energy_needed = max(0, required - stock) * 60
    applied = min(stored_energy, drink_energy_needed)
    needed = drink_energy_needed - applied
    total = sum(values[key] * n for key, n in available.items())
    result = {
        "required_drinks": required,
        "stock_drinks": stock,
        "energy_needed": needed,
        "drink_energy_needed": drink_energy_needed,
        "stored_energy_observed": stored_energy,
        "stored_energy_verified": stored_energy_verified,
        "stored_energy_applied": applied,
        "observed_inventory_energy": observed_energy(
            inventory, catalog, multiplier=multiplier
        ),
        "spendable_energy": total,
        "additional_verified_energy_needed": max(0, needed - total),
        "inventory_complete": complete,
        "conversion_multiplier": multiplier,
        "selected_items": {},
        "selected_energy": 0,
        "inventory_updated": False,
        "cooking_preview_required": True,
    }
    if needed == 0:
        return {
            **result,
            "status": "existing_drinks_sufficient",
            "cooking_preview_required": False,
        }
    if total < needed:
        return {**result, "status": "insufficient_observed_spendable_food"}
    # A minimal-overage solution cannot exceed target + largest unit -1.
    bound = needed + max(values[key] for key, n in available.items() if n) - 1
    states = {0: (0, {})}
    for key, owned in available.items():
        unit = values[key]
        for _ in range(min(owned, bound // unit)):
            for energy, (count, chosen) in sorted(states.items(), reverse=True):
                after = energy + unit
                if after > bound:
                    continue
                candidate = (count + 1, {**chosen, key: chosen.get(key, 0) + 1})
                if after not in states or candidate[0] < states[after][0]:
                    states[after] = candidate
    selected = min(energy for energy in states if energy >= needed)
    _count, chosen = states[selected]
    return {
        **result,
        "status": "candidate_ingredients",
        "selected_items": chosen,
        "selected_energy": selected,
        "excess_energy": selected - needed,
        "overflow_retention_verified": False,
    }


# Settlement identities must be exact exported items; generic wild plants remain unresolved.
SETTLEMENT_FOOD_IDS = {
    "fowlbeast_wing": "sandbox_1_poultry",
    "puffball_tenderloin": "sandbox_1_venison",
}


def verify_hunting_food(
    settlement,
    minimum_base_energy=80,
    *,
    expected_stage="Straight Into the Abyss",
    catalog=None,
):
    """Verify delivered food from icon-linked reward evidence; never credit warehouse/drinks."""
    from maa_sand_settlement import count_roi, quantity

    catalog = catalog or load_food_catalog()
    if type(minimum_base_energy) is not int or not 1 <= minimum_base_energy <= 1000:
        raise CheckpointError(
            "Hunting food requires a bounded positive base-energy target"
        )
    report = {
        "food_reward_verified": False,
        "minimum_base_energy": minimum_base_energy,
        "base_energy_observed": None,
        "raw_food_counts": {},
        "evidence": {},
        "inventory_updated": False,
        "drinks_prepared": False,
        "conversion_multiplier_applied": False,
        "image": settlement.get("image"),
        "issues": [],
    }
    if not settlement.get("image") or settlement.get("stage") != expected_stage:
        report["issues"].append(
            "Food evidence requires the named expedition settlement"
        )
        return report
    occupied = set()
    for resource, item_id in SETTLEMENT_FOOD_IDS.items():
        value = settlement.get("verified_counts", {}).get(resource)
        if value is None:
            continue
        evidence = settlement.get("evidence", {}).get(resource, {})
        icon = evidence.get("icon", {})
        try:
            if type(value) is not int or value <= 0 or icon.get("score", 0) < 0.9:
                raise CheckpointError(
                    "Confident positive food count and exact item icon required"
                )
            slot, _ = count_roi(icon)
            if slot in occupied:
                raise CheckpointError("Two food identities occupy one reward slot")
            if quantity(evidence.get("quantity_reads", [])) != value:
                raise CheckpointError(
                    "Food quantity does not agree with the explicit +N reward evidence"
                )
            occupied.add(slot)
            report["raw_food_counts"][item_id] = value
            report["evidence"][item_id] = evidence
        except CheckpointError as exc:
            report["issues"].append(str(exc))
    energy = sum(
        catalog[key]["energy"] * n for key, n in report["raw_food_counts"].items()
    )
    report["base_energy_observed"] = energy if report["raw_food_counts"] else None
    report["food_reward_verified"] = (
        not report["issues"] and energy >= minimum_base_energy
    )
    if energy < minimum_base_energy:
        report["issues"].append(
            "Observed delivered food does not yet meet the base-energy target; missing items remain unknown"
        )
    return report
