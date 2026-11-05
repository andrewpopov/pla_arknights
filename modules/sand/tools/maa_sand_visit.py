"""One reviewed empty-squad Liaison visit, using shared MAA navigation and dialogue."""

import re
import time

from maa_sand_campaign import advise, load_campaign
from maa_sand_config import CheckpointError
from maa_sand_dialogue import LiaisonDialogue
from maa_sand_navigation import CampaignNavigator
from maa_sand_settlement import enlarged_count
from maa_sand_world import read_world, reconcile_world


def trip_energy(read):
    match = re.fullmatch(r"\s*[+−-]?\s*([23])\s*/\s*(\d{1,3})\s*", read.get("text", ""))
    if read.get("score", 0) < 0.9 or match is None:
        raise CheckpointError(
            "Complete trip drink cost/stock was not confidently observed"
        )
    cost, stock = map(int, match.groups())
    return {"cost": cost, "stock": stock, "funded": stock >= cost}


def read_trip_energy(runtime, path, read):
    try:
        result = trip_energy(read)
        result["evidence"] = {"image": str(path), "read": read, "magnified": False}
        return result
    except CheckpointError:
        prepared, roi = enlarged_count(path, [930, 668, 77, 22])
        reads = runtime.ocr(prepared, roi)
        if len(reads) != 1:
            raise CheckpointError(
                "Trip drink badge did not produce one complete magnified ratio"
            )
        result = trip_energy(reads[0])
        result["evidence"] = {
            "image": str(path),
            "prepared": str(prepared),
            "read": reads[0],
            "magnified": True,
        }
        return result


def review_visit(state, pack=None, *, check_only=False):
    advice = advise(state, load_campaign(pack))
    step = advice["next"]
    if (
        state["threat"] not in ("clear", "later")
        or step is None
        or (step["day"], step["act"], step["stage_id"]) != (4, 2, "sandbox_1_55")
        or not step["empty_squad_supported"]
        or step["required_tools"]
    ):
        raise CheckpointError(
            "Liaison visit requires the reviewed Day4 Act2 plan and known nonurgent threat"
        )
    if state.get("liaison_intro_pending") is not True:
        advice["blockers"].append(
            "Observe that the first Liaison intro is pending on this target before spending drinks."
        )
    if not check_only and (
        not state["snapshot_current"]
        or not state["settled"]
        or state["drinks"] < 2
        or state.get("liaison_intro_pending") is not True
    ):
        raise CheckpointError(
            "Liaison launch requires current settled observations, a pending first intro and two prepared drinks"
        )
    return step, advice


class LiaisonVisit:
    def __init__(self, player):
        self.player = player
        self.rt = player.rt
        self.nav = CampaignNavigator(self.rt, self.rt.pack)
        self.dialogue = LiaisonDialogue(self.rt, self.rt.pack)
        self.pending = False
        self.completed = False

    @staticmethod
    def hit(hits, task):
        return hits.get(task, {}).get("score", 0) >= 0.85

    def run(self, state):
        if self.pending or self.completed:
            raise CheckpointError(
                "Previous Liaison launch is pending or already returned; do not repeat it"
            )
        if (
            self.player.in_battle
            or getattr(self.player, "water_target", None) is not None
        ):
            raise CheckpointError(
                "Begin the Liaison visit from a settled world session"
            )
        step, _ = review_visit(state, self.rt.pack)
        path, hits = self.nav.frame("liaison-visit-world")
        if not self.hit(hits, "SandAuto@World"):
            raise CheckpointError(
                "Liaison visit needs a verified world-map starting point"
            )
        before = read_world(self.rt, path)
        if (before["day"], before["acts_remaining"], before["hq"]) != (
            state["day"],
            2 - state["acts_used"],
            state["hq"],
        ):
            raise CheckpointError(
                "Fresh world HUD does not match the supplied campaign state"
            )
        self.nav.prepare_empty_next(state)
        empty = [f"SandAuto@EmptySquadSlot{i}" for i in range(1, 8)]
        path, hits = self.nav.frame(
            "liaison-visit-ready",
            [
                *empty,
                "SandAuto@NoEquippedTools",
                "SandAuto@FormationTripEnergy",
                "SandAuto@VisitStartConfirm",
            ],
        )
        if (
            not self.hit(hits, "SandAuto@Squad")
            or not all(self.hit(hits, task) for task in empty)
            or not self.hit(hits, "SandAuto@NoEquippedTools")
            or self.hit(hits, "SandAuto@VisitStartConfirm")
        ):
            raise CheckpointError(
                "Fresh empty formation was not verified before launch"
            )
        energy = read_trip_energy(
            self.rt, path, hits.get("SandAuto@FormationTripEnergy", {})
        )
        if (
            energy["cost"] != 2
            or not energy["funded"]
            or energy["stock"] != state["drinks"]
        ):
            raise CheckpointError(
                "Displayed drink cost/stock is unfunded or differs from the observed state"
            )
        self.pending = True
        self.rt.task("SandPilot@SquadStart")
        confirmed = False
        for _ in range(12):
            path, _ = self.rt.capture("liaison-visit-launch")
            hits = self.rt.matches(
                path,
                [
                    "SandAuto@DialogueLog",
                    "SandAuto@VisitStartConfirm",
                    "SandAuto@NoEnergy",
                    "SandAuto@Battle",
                    "SandAuto@Paused",
                ],
            )
            if self.hit(hits, "SandAuto@NoEnergy"):
                raise CheckpointError(
                    "Visit launch reports insufficient drinks; do not repeat Start"
                )
            if self.hit(hits, "SandAuto@DialogueLog"):
                break
            if self.hit(hits, "SandAuto@VisitStartConfirm"):
                if confirmed:
                    raise CheckpointError(
                        "Another launch confirmation appeared; stop without repeating it"
                    )
                confirmed = True
                self.rt.task("SandPilot@VisitStartConfirm")
            elif self.hit(hits, "SandAuto@Battle"):
                self.nav.frame("liaison-unexpected-battle")
                raise CheckpointError(
                    "Battle appeared before the known Liaison intro; visit remains pending"
                )
            time.sleep(0.25)
        else:
            raise CheckpointError(
                "Liaison intro was not observed after the single launch"
            )
        conversation = self.dialogue.run(step["stage_id"])
        if conversation.get("status") != "dialogue_sequence_observed_paused":
            raise CheckpointError(
                "Liaison dialogue completion and battle pause were not verified"
            )
        self.player.in_battle = True
        self.player.pause(True)
        self.player.finish(stage=step["stage"])
        after = getattr(self.player, "world_observation", None)
        if after is None:
            raise CheckpointError(
                "Liaison return has no observed world HUD; launch remains pending"
            )
        reconciliation = reconcile_world(before, after)
        if reconciliation["observed_act_difference"] != 1:
            raise CheckpointError("Liaison return did not show one Act consumed")
        self.pending = False
        self.completed = True
        result = {
            "status": "liaison_visit_returned",
            "stage_id": step["stage_id"],
            "conversation": conversation,
            "world": after,
            "reconciliation": reconciliation,
            "displayed_drink_cost": energy["cost"],
            "energy_evidence": energy["evidence"],
            "drink_debit_verified": False,
            "quest_save_verified": False,
            "route_unlock_verified": False,
            "inventory_updated": False,
            "day_advanced": False,
        }
        self.rt.log("liaison_visit_returned", **result)
        return result
