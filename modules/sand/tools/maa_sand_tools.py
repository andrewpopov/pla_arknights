"""Bounded tool preparation using existing MAA workbench tasks and observations."""

import json
import re
import time
from pathlib import Path

from maa_sand_config import REVIEWED_FIELD_TOOLS, CheckpointError, default_pack
from maa_sand_settlement import enlarged_count


def load_tool_catalog(pack=None):
    data = json.loads(
        ((Path(pack) if pack else default_pack()) / "campaign/tools.json").read_text(
            encoding="utf8"
        )
    )
    if (
        data.get("schema_version") != 1
        or data.get("live_recipe_confirmation_required") is not True
    ):
        raise CheckpointError("Unsupported tool catalog")
    return data["items"]


def tool_mechanics_advice(required, pack=None):
    """Data-backed planning context; never replace live cost, terrain or yield checks."""
    data = json.loads(
        (
            (Path(pack) if pack else default_pack()) / "campaign/tool-mechanics.json"
        ).read_text(encoding="utf8")
    )
    if (
        data.get("schema_version") != 1
        or data.get("client_version_verified") is not False
        or data.get("runtime_placement_verified") is not False
        or data.get("automatic_inventory_credit") is not False
    ):
        raise CheckpointError(
            "Tool mechanics must remain an unverified advisory source"
        )
    by_name = {
        name: (item_id, trap_id)
        for item_id, (name, trap_id) in REVIEWED_FIELD_TOOLS.items()
    }
    if not isinstance(required, dict) or any(
        name not in by_name or type(qty) is not int or not 1 <= qty <= 2
        for name, qty in required.items()
    ):
        raise CheckpointError(
            "Tool mechanics advice requires reviewed guide quantities"
        )
    result = {
        "advisory_only": True,
        "client_version_verified": False,
        "source_commit": data["commit"],
        "live_cost_and_placement_required": True,
        "delivered_yield_verified": False,
        "tools": {},
    }
    for name, qty in required.items():
        item_id, trap_id = by_name[name]
        item = data["items"][item_id]
        if item["name"] != name or item["trap_id"] != trap_id:
            raise CheckpointError(
                "Tool mechanics identity differs from the reviewed catalog"
            )
        attrs, skill = item["base_attributes"], item["skill"]
        board = skill["blackboard"]
        cost = attrs["cost"]
        if type(cost) is not int or cost < 0:
            raise CheckpointError("Tool base DP is not an exported nonnegative integer")
        entry = {
            "quantity": qty,
            "base_dp_each": cost,
            "total_base_dp": qty * cost,
            "base_hp": attrs["maxHp"],
            "base_defense": attrs["def"],
            "placement_description": item["placement_description"],
            "excluded_from_raid_battles": item["excluded_from_raid_battles"],
            "initial_auto_skill_sp_gap": max(
                0, skill["sp"]["spCost"] - skill["sp"]["initSp"]
            ),
        }
        if item_id == "sandbox_1_tactical_15":
            lifetime = board["live_duration"]["value"]
            entry.update(
                exported_lifetime_seconds=lifetime,
                full_lifetime_and_25s_exit_reserve=lifetime + 25,
                lifetime_does_not_prove_yield=True,
            )
        else:
            entry["gatherer_limit"] = board["max_cnt"]["value"]
            entry["resource_hp_ratio_parameters"] = {
                material: board[f"sandbox_res_collector.hp_ratio[{material}]"]["value"]
                for material in ("wood", "stone", "iron")
            }
            entry["resource_parameters_are_not_item_yields"] = True
        result["tools"][name] = entry
    return result


def count(matches, key):
    read = matches.get(key, {})
    text = read.get("text", "").strip()
    if read.get("score", 0) < 0.85 or not re.fullmatch(r"\d{1,3}", text):
        raise CheckpointError("Tool counter not confidently observed: " + key)
    return int(text)


def material_pairs(reads, expected):
    """Bind ordered cost labels to the exact identified recipe's material order."""
    pairs = []
    for read in reads:
        pair = re.fullmatch(r"\s*(\d{1,6})\s*/\s*(\d{1,3})\s*", read.get("text", ""))
        if pair:
            rect = read.get("rect", [])
            if (
                read.get("score", 0) < 0.85
                or len(rect) != 4
                or any(type(v) is not int for v in rect)
                or rect[2] <= 0
                or rect[3] <= 0
            ):
                raise CheckpointError("Material cost has no confident native position")
            x, y, w, h = rect
            if not (175 <= x and x + w <= 445 and 475 <= y and y + h <= 580):
                raise CheckpointError(
                    "Material cost lies outside the recipe material area"
                )
            pairs.append((x, int(pair[1]), int(pair[2])))
        elif read.get("text", "").strip():
            raise CheckpointError("Unresolved text in the recipe material area")
    pairs.sort()
    if len(pairs) != len(expected) or len({p[0] for p in pairs}) != len(pairs):
        raise CheckpointError("Complete distinct material cost labels are required")
    available = {}
    for (material, cost), (_x, owned, price) in zip(
        expected.items(), pairs, strict=True
    ):
        if price != cost:
            raise CheckpointError(
                "Visible material cost differs from the reviewed recipe"
            )
        available[material] = owned
    return available


def read_hub_materials(runtime, path, expected):
    roi = [175, 475, 270, 105]
    try:
        return material_pairs(runtime.ocr(path, roi), expected)
    except CheckpointError:
        # One native OCR retry, preserving the original material identity and confidence rules.
        prepared, enlarged_roi = enlarged_count(path, roi)
        reads = runtime.ocr(prepared, enlarged_roi)
        mapped = []
        for read in reads:
            rect = read.get("rect", [])
            if len(rect) != 4 or any(type(v) is not int for v in rect):
                raise CheckpointError("Magnified material cost has no native rectangle")
            mapped.append(
                {
                    **read,
                    "rect": [
                        round(rect[0] / 4) + roi[0],
                        round(rect[1] / 4) + roi[1],
                        round(rect[2] / 4),
                        round(rect[3] / 4),
                    ],
                }
            )
        return material_pairs(mapped, expected)


def read_pump_wood(runtime, path, read):
    """Retry a small pump counter with the shared saved-image magnifier."""

    def parse(value):
        if value.get("score", 0) < 0.85:
            return None
        pair = re.fullmatch(r"\s*(\d{1,6})\s*/\s*(\d{1,3})\s*", value.get("text", ""))
        if pair is None:
            return None
        if int(pair[2]) != 10:
            raise CheckpointError("Visible pump cost differs from the reviewed recipe")
        return int(pair[1])

    available = parse(read)
    if available is not None:
        return available
    prepared, roi = enlarged_count(path, [228, 540, 55, 30])
    reads = [
        value
        for value in runtime.ocr(prepared, roi)
        if value.get("score", 0) >= 0.85 and value.get("text", "").strip()
    ]
    if len(reads) != 1:
        raise CheckpointError(
            "Pump wood counter is not uniquely observed after magnification"
        )
    available = parse(reads[0])
    if available is None:
        raise CheckpointError("Pump wood counter is unreadable after magnification")
    return available


class ToolCrafter:
    def __init__(self, runtime, pack=None):
        self.rt = runtime
        self.catalog = load_tool_catalog(pack)
        self.pending = False
        self.select_recipe("sandbox_1_tactical_15")

    def select_recipe(self, item_id):
        if self.pending:
            raise CheckpointError(
                "Unresolved prior craft: do not change recipe or submit another"
            )
        reviewed = {
            "sandbox_1_tactical_15": ("Pump", "Crabbie Pumpie", {"wood": 10}, 1),
            "sandbox_1_tactical_16": (
                "Hub",
                "Sawing Harvester Hub",
                {"wood": 7, "stone": 1},
                2,
            ),
        }
        if item_id not in reviewed:
            raise CheckpointError("Unreviewed tool recipe")
        kind, name, materials, hq = reviewed[item_id]
        recipe = self.catalog[item_id]
        if (
            recipe["name"] != name
            or recipe["materials"] != materials
            or recipe["output_ratio"] != 1
            or recipe["min_hq"] != hq
        ):
            raise CheckpointError(
                "Tool identity, price, quantity or unlock changed; review required"
            )
        self.kind, self.recipe = kind, {**recipe, "materials": materials}

    @staticmethod
    def hit(matches, key):
        return matches.get(key, {}).get("score", 0) >= 0.85

    def recipe_frame(self):
        kind = self.kind
        screen = f"SandAuto@{kind}RecipeScreen"
        path, _ = self.rt.capture(kind.lower() + "-recipe-check")
        identity = self.rt.matches(path, [screen, "SandAuto@WorkbenchScreen"])
        if not self.hit(identity, screen):
            if not self.hit(identity, "SandAuto@WorkbenchScreen"):
                raise CheckpointError(
                    "Tool preparation requires the workbench or exact recipe"
                )
            self.rt.task(f"SandPilot@{kind}Recipe")
            path, _ = self.rt.capture(kind.lower() + "-recipe-opened")
            if not self.hit(self.rt.matches(path, [screen]), screen):
                raise CheckpointError("Exact tool recipe was not confirmed")
        tasks = ["SandAuto@ToolRecipeStock", "SandAuto@ToolCraftQuantity"]
        if kind == "Pump":
            tasks.append("SandAuto@ToolCost0")
        fields = self.rt.matches(path, tasks)
        stock = count(fields, "SandAuto@ToolRecipeStock")
        if count(fields, "SandAuto@ToolCraftQuantity") != 1:
            raise CheckpointError(
                "Preserve existing craft quantity; bounded crafting requires one"
            )
        if kind in ("Hub", "Planter"):
            available = read_hub_materials(self.rt, path, self.recipe["materials"])
        else:
            available = read_pump_wood(
                self.rt, path, fields.get("SandAuto@ToolCost0", {})
            )
        return path, stock, available

    def stock_frame(self):
        kind = self.kind
        screen = f"SandAuto@{kind}RecipeScreen"
        path, _ = self.rt.capture(kind.lower() + "-stock-confirm")
        tasks = [
            screen,
            "SandAuto@WorkbenchScreen",
            "SandAuto@WorkbenchPumpName",
            "SandAuto@CraftReceiptTitle",
            "SandAuto@CraftReceiptContinue",
        ]
        identity = self.rt.matches(path, tasks)
        if self.hit(identity, "SandAuto@CraftReceiptTitle"):
            if not self.pending or not self.hit(
                identity, "SandAuto@CraftReceiptContinue"
            ):
                raise CheckpointError(
                    "Unowned or incomplete craft receipt; preserve it for review"
                )
            self.rt.task("SandPilot@DismissCraftReceipt")
            path, _ = self.rt.capture(kind.lower() + "-after-receipt")
            identity = self.rt.matches(path, tasks)
            if self.hit(identity, "SandAuto@CraftReceiptTitle"):
                raise CheckpointError(
                    "Craft receipt dismissal unconfirmed; no new craft submitted"
                )
        if self.hit(identity, screen):
            key = "SandAuto@ToolRecipeStock"
        elif self.hit(identity, "SandAuto@WorkbenchScreen"):
            if kind in ("Hub", "Planter"):
                # Reopen the identified recipe; never borrow stock from a neighboring card.
                path, stock, _available = self.recipe_frame()
                return path, stock
            if not self.hit(identity, "SandAuto@WorkbenchPumpName"):
                raise CheckpointError("No identified pump stock screen after crafting")
            key = "SandAuto@WorkbenchPumpStock"
        else:
            raise CheckpointError("No identified tool stock screen after crafting")
        return path, count(self.rt.matches(path, [key]), key)

    def confirm_pending_craft(self, submission):
        """Resolve one owned pending craft from stock; never submit another craft."""
        before = (
            submission.get("stock_before") if isinstance(submission, dict) else None
        )
        if (
            not self.pending
            or type(before) is not int
            or not 0 <= before < 100000
            or submission.get("item_id") != self.recipe["id"]
            or submission.get("quantity") != 1
            or submission.get("expected_material_costs") != self.recipe["materials"]
        ):
            raise CheckpointError(
                "Pending craft confirmation requires its exact owned submission"
            )
        path, stock = self.stock_frame()
        if stock != before + 1:
            raise CheckpointError("Pending craft has no exact one-item stock increase")
        self.pending = False
        self.rt.log(
            "tool_stock_verified",
            item=self.recipe["id"],
            stock=stock,
            image=str(path),
            resumed=True,
        )
        return {
            "stock": stock,
            "crafted": 1,
            "expected_wood_cost": self.recipe["materials"]["wood"],
            "expected_material_costs": dict(self.recipe["materials"]),
            "inventory_updated": False,
        }

    def prepare_pumps(self, target=1, reserve_wood=0):
        self.select_recipe("sandbox_1_tactical_15")
        return self._prepare(target, {"wood": reserve_wood})

    def prepare_hubs(self, target=1, *, observed_hq, reserve_wood=0, reserve_stone=0):
        if type(observed_hq) is not int or not 2 <= observed_hq <= 10:
            raise CheckpointError(
                "Hub preparation requires an observed HQ level of at least2"
            )
        self.select_recipe("sandbox_1_tactical_16")
        return self._prepare(target, {"wood": reserve_wood, "stone": reserve_stone})

    def _prepare(self, target, reserves, expected_stock=None):
        if (
            type(target) is not int
            or not 1 <= target <= 2
            or set(reserves) != set(self.recipe["materials"])
            or any(
                type(v) is not int or not 0 <= v <= 100000 for v in reserves.values()
            )
        ):
            raise CheckpointError(
                "Tool preparation permits at most two with explicit material reserves"
            )
        if self.pending:
            raise CheckpointError("Unresolved prior craft: do not submit another")
        path, stock, available = self.recipe_frame()
        if expected_stock is not None and stock != expected_stock:
            raise CheckpointError(
                "Tool stock changed after the combined batch inspection"
            )
        costs = self.recipe["materials"]

        def affordable(owned, missing):
            if type(owned) is int and self.kind == "Pump":
                owned = {"wood": owned}
            if not isinstance(owned, dict) or set(owned) != set(costs):
                raise CheckpointError("Complete observed tool materials are required")
            if any(type(v) is not int or v < 0 for v in owned.values()):
                raise CheckpointError("Invalid observed material quantity")
            return all(
                owned[m] >= missing * price + reserves[m] for m, price in costs.items()
            )

        missing = max(0, target - stock)
        if missing and not affordable(available, missing):
            raise CheckpointError(
                "Cannot afford the full tool target and reserves; nothing crafted"
            )
        initial = stock
        for index in range(missing):
            if index:
                path, observed, available = self.recipe_frame()
                if observed != stock or not affordable(available, target - stock):
                    raise CheckpointError(
                        "Tool stock/materials changed between verified crafts"
                    )
            self.pending = True
            self.rt.log(
                "tool_craft_submitting",
                item=self.recipe["id"],
                stock_before=stock,
                quantity=1,
                expected_material_costs=costs,
                image=str(path),
            )
            before_submit = getattr(self, "before_submit", None)
            if before_submit is not None:
                before_submit(
                    {
                        "item_id": self.recipe["id"],
                        "stock_before": stock,
                        "quantity": 1,
                        "expected_material_costs": dict(costs),
                        "image": str(path),
                    }
                )
            self.rt.task(f"SandPilot@CraftOne{self.kind}")
            for _ in range(4):
                try:
                    confirmed, after = self.stock_frame()
                except CheckpointError:
                    time.sleep(0.25)
                    continue
                if after == stock + 1:
                    break
                if after != stock:
                    raise CheckpointError(
                        "Unexpected tool stock change; preserve pending craft"
                    )
                time.sleep(0.25)
            else:
                raise CheckpointError(
                    "Craft submitted but stock increase unconfirmed; do not retry"
                )
            self.pending = False
            stock = after
            self.rt.log(
                "tool_stock_verified",
                item=self.recipe["id"],
                stock=stock,
                image=str(confirmed),
            )
        return {
            "stock": stock,
            "crafted": stock - initial,
            "expected_wood_cost": (stock - initial) * costs["wood"],
            "expected_material_costs": {
                m: (stock - initial) * price for m, price in costs.items()
            },
            "inventory_updated": False,
        }

    def close_recipe(self):
        if self.pending:
            raise CheckpointError("Preserve the unresolved craft screen")
        path, _ = self.rt.capture("tool-recipe-return-check")
        screens = ["SandAuto@PumpRecipeScreen", "SandAuto@HubRecipeScreen"]
        if self.kind == "Planter":
            screens.append("SandAuto@PlanterRecipeScreen")
        tasks = [*screens, "SandAuto@WorkbenchScreen", "SandAuto@ToolRecipeClosable"]
        hits = self.rt.matches(path, tasks)
        if any(self.hit(hits, key) for key in screens):
            if not self.hit(hits, "SandAuto@ToolRecipeClosable"):
                raise CheckpointError("Native cancel-craft control was not verified")
            self.rt.task("SandPilot@CloseToolRecipe")
            path, _ = self.rt.capture("tool-workbench-returned")
            hits = self.rt.matches(path, [*screens, "SandAuto@WorkbenchScreen"])
        if not self.hit(hits, "SandAuto@WorkbenchScreen") or any(
            self.hit(hits, key) for key in screens
        ):
            raise CheckpointError("Recipe close did not confirm the workbench")

    def prepare_batch(self, targets, *, observed_hq, reserve_wood=0, reserve_stone=0):
        """Inspect every recipe before any spending, then reserve the unfinished batch."""
        if self.pending:
            raise CheckpointError(
                "Unresolved prior craft: do not begin a combined batch"
            )
        by_name = {r["name"]: r for r in self.catalog.values()}
        if (
            not isinstance(targets, dict)
            or not targets
            or len(targets) > 2
            or any(
                name not in by_name or type(n) is not int or not 1 <= n <= 2
                for name, n in targets.items()
            )
            or type(observed_hq) is not int
            or not 1 <= observed_hq <= 10
            or any(
                type(v) is not int or not 0 <= v <= 100000
                for v in (reserve_wood, reserve_stone)
            )
        ):
            raise CheckpointError(
                "Combined tool preparation requires reviewed targets, HQ and reserves"
            )
        recipes = sorted((by_name[name] for name in targets), key=lambda r: r["id"])
        if any(observed_hq < r["min_hq"] for r in recipes):
            raise CheckpointError(
                "Combined tool batch requires its full HQ prerequisites"
            )
        reserves = {"wood": reserve_wood, "stone": reserve_stone}
        observed, inspected, required = {}, {}, {"wood": 0, "stone": 0}
        for recipe in recipes:
            self.select_recipe(recipe["id"])
            path, stock, available = self.recipe_frame()
            if type(available) is int and self.kind == "Pump":
                available = {"wood": available}
            if (
                not isinstance(available, dict)
                or set(available) != set(self.recipe["materials"])
                or any(type(v) is not int or v < 0 for v in available.values())
            ):
                raise CheckpointError(
                    "Complete material observations required before the first craft"
                )
            for material, value in available.items():
                if material in observed and observed[material] != value:
                    raise CheckpointError(
                        "Materials changed during combined batch inspection"
                    )
                observed[material] = value
            missing = max(0, targets[recipe["name"]] - stock)
            inspected[recipe["id"]] = {
                "stock": stock,
                "missing": missing,
                "image": str(path),
            }
            for material, cost in self.recipe["materials"].items():
                required[material] += missing * cost
            self.close_recipe()
        if any(
            cost and observed.get(m, -1) < cost + reserves[m]
            for m, cost in required.items()
        ):
            raise CheckpointError(
                "Cannot afford the complete combined tool batch and reserves; nothing crafted"
            )
        remaining, completed = dict(required), {}
        for recipe in recipes:
            before = inspected[recipe["id"]]
            for material, cost in recipe["materials"].items():
                remaining[material] -= before["missing"] * cost
            self.select_recipe(recipe["id"])
            protected = {
                m: reserves[m] + remaining[m] for m in self.recipe["materials"]
            }
            result = self._prepare(
                targets[recipe["name"]], protected, expected_stock=before["stock"]
            )
            completed[recipe["name"]] = result
            self.rt.log(
                "combined_tool_target_verified", item=recipe["id"], result=result
            )
            self.close_recipe()
        return {
            "status": "combined_tool_targets_verified",
            "tools": completed,
            "inspected": inspected,
            "expected_material_costs": required,
            "inventory_updated": False,
            "expedition_started": False,
        }
