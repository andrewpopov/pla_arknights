"""Reviewed encounter policies share exact recognition and one-Act reconciliation."""

import json
import time
from pathlib import Path

from maa_sand_campaign import advise, load_campaign
from maa_sand_config import CheckpointError, default_pack
from maa_sand_dialogue import choice_point, fingerprint, ordered_text
from maa_sand_navigation import CampaignNavigator
from maa_sand_world import read_world, reconcile_world

BODY = [50, 365, 720, 135]
CHOICES = [820, 270, 450, 270]


class CampaignEncounter:
    def __init__(self, runtime, pack=None):
        self.rt = runtime
        self.pack = Path(pack) if pack else default_pack()
        registry = json.loads(
            (self.pack / "campaign/encounters.json").read_text(encoding="utf8")
        )
        if (
            registry.get("schema_version") != 1
            or registry.get("autoplay_enabled") is not False
        ):
            raise CheckpointError("Unreviewed encounter registry")
        reviewed = {
            "choice_business_2_3": (
                "scene_business_2_enter",
                "scene_business_2_3",
                "choice_business_2_leave_1",
            ),
            "choice_gold_1_1": (
                "scene_gold_1_enter",
                "scene_gold_1_1",
                "choice_gold_1_leave_2",
            ),
        }
        self.plans = []
        for reference in registry["policies"]:
            if reference not in (
                "guides/slightest-effort.json",
                "guides/exchange-troubles.json",
            ):
                raise CheckpointError("Unreviewed encounter reference")
            plan = json.loads((self.pack / reference).read_text(encoding="utf8"))
            selected = [
                c for c in plan["choices"] if c["choiceId"] == plan["selected_choice"]
            ]
            expected = reviewed.get(plan["selected_choice"])
            if (
                plan.get("schema_version") != 1
                or plan.get("autoplay_enabled") is not False
                or expected is None
                or (
                    plan["entry_scene_id"],
                    plan["result_scene_id"],
                    plan["leave"]["choice_id"],
                )
                != expected
                or plan.get("act_cost") != 1
                or plan.get("food_cost") != {}
                or plan["leave"].get("act_cost") != 0
                or len(selected) != 1
                or selected[0]["costAction"] != 1
                or selected[0]["type"] != "NEXT"
            ):
                raise CheckpointError(
                    "Encounter identity/costs changed; review required"
                )
            self.plans.append(plan)
        if not self.plans or len({p["entry_scene_id"] for p in self.plans}) != len(
            self.plans
        ):
            raise CheckpointError(
                "Encounter registry must contain distinct reviewed scenes"
            )
        self.plan = self.plans[0]
        self.pending = False
        self.navigator = CampaignNavigator(runtime, self.pack)

    def recognize(self, path, result=False):
        choices = [self.plan["leave"]] if result else self.plan["choices"]
        tasks = [self.plan["title_observer"], *[c["observer"] for c in choices]]
        hits = self.rt.matches(path, tasks)
        if any(hits.get(key, {}).get("score", 0) < 0.85 for key in tasks):
            return None
        body = ordered_text(self.rt.ocr(path, BODY))
        digest = self.plan["result_digest" if result else "entry_digest"]
        if body is None or fingerprint(body) != digest:
            return None
        selected = (
            self.plan["leave"]
            if result
            else next(
                c for c in choices if c["choiceId"] == self.plan["selected_choice"]
            )
        )
        return choice_point([hits[selected["observer"]]], CHOICES)

    def select_entry(self, path):
        if self.pending:
            raise CheckpointError(
                "Preserve the active policy while its Act submission is pending"
            )
        original = self.plan
        for plan in [original, *[p for p in self.plans if p is not original]]:
            self.plan = plan
            point = self.recognize(path)
            if point is not None:
                return point
        self.plan = original
        return None

    def resolve(self, state):
        if self.pending:
            raise CheckpointError(
                "Unresolved encounter submission; do not spend another Act"
            )
        advice = advise(state, load_campaign(self.pack))
        step = advice["next"]
        if (
            not state["snapshot_current"]
            or not state["settled"]
            or state["threat"] not in ("clear", "later")
            or step is None
            or step["objective"] != "encounter"
        ):
            raise CheckpointError(
                "Encounter handling requires the current reviewed encounter Act"
            )
        path, _ = self.navigator.frame("encounter-entry")
        point = self.select_entry(path)
        if point is None:
            raise CheckpointError(
                "Exact reviewed encounter entry and every choice must be recognized"
            )
        before = read_world(self.rt, path)
        if (
            before["day"] != state["day"]
            or before["acts_remaining"] != 2 - state["acts_used"]
        ):
            raise CheckpointError(
                "Encounter HUD disagrees with the current campaign Act"
            )
        if before["acts_remaining"] < self.plan["act_cost"]:
            raise CheckpointError("Encounter choice exceeds observed remaining Acts")
        self.pending = True
        self.rt.log(
            "encounter_submitting",
            choice=self.plan["selected_choice"],
            act_cost=1,
            food_cost={},
            image=str(path),
        )
        self.rt.click(point)
        for _ in range(8):
            result, _ = self.navigator.frame("encounter-result")
            leave = self.recognize(result, result=True)
            if leave is not None:
                break
            time.sleep(0.25)
        else:
            raise CheckpointError(
                "Known encounter result unconfirmed; preserve pending Act"
            )
        # This reviewed acknowledgement has costAction0, not another paid choice.
        self.rt.click(leave)
        for _ in range(8):
            after_image, _ = self.navigator.frame("encounter-world")
            if self.rt.matches(after_image, [self.plan["title_observer"]]):
                time.sleep(0.25)
                continue
            try:
                after = read_world(self.rt, after_image)
            except CheckpointError:
                time.sleep(0.25)
                continue
            break
        else:
            raise CheckpointError(
                "Encounter world return unconfirmed; do not repeat choice"
            )
        facts = reconcile_world(before, after)
        if facts["observed_act_difference"] != 1:
            raise CheckpointError(
                "Encounter did not confirm the expected one-Act difference"
            )
        self.pending = False
        report = {
            "status": "reviewed_encounter_world_return",
            "choice": self.plan["selected_choice"],
            "before": before,
            "after": after,
            "reconciliation": facts,
            "result_image": str(result),
            "world_image": str(after_image),
            "expected_gold_range": self.plan["expected_gold_range"],
            "inventory_updated": False,
            "route_unlock_verified": False,
            "expected_drinks_cost": 0,
        }
        self.rt.log("encounter_world_observed", **report)
        return report
