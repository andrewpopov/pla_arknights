"""Shared native RA roster recognition and bounded journaled actor selection."""

import copy
import re
import time
from pathlib import Path

from maa_sand_config import CheckpointError


def read_roster(runtime, path):
    """One scene-bound native scan, reusable for identity lookup and page progress."""
    gates = ["SandRoster@PageClear", "SandRoster@PageConfirm"]
    closed_task = "SandRoster@RoleMenuClosed"
    observed = runtime.matches(path, [*gates, closed_task])
    if any(observed.get(task, {}).get("score", 0) < 0.85 for task in gates):
        raise CheckpointError(
            "Roster page Clear and Added to Squad controls were not both identified"
        )
    report = runtime.analyze(path, "formation_operators", task_prefix="SandRoster@")
    validate_roster_report(report, path)
    report["closed_role_menu"] = observed.get(closed_task)
    return report


def validate_roster_report(report, path):
    if (
        not isinstance(report.get("image"), str)
        or Path(report["image"]).resolve() != Path(path).resolve()
    ):
        raise CheckpointError("Native roster result belongs to another screenshot")
    if (
        report.get("task_prefix") != "SandRoster@"
        or report.get("mode") != "formation_operators"
        or report.get("inputs_issued") is not False
    ):
        raise CheckpointError(
            "Native RA roster analysis did not confirm its read-only layout"
        )


def find_roster_card(runtime, path, character_id):
    if not isinstance(character_id, str) or not character_id.startswith("char_"):
        raise CheckpointError(
            "Roster lookup requires an exact native BattleData character ID"
        )
    return roster_card(read_roster(runtime, path), path, character_id)


def roster_card(report, path, character_id):
    """Extract one actor from a validated saved-frame native report; no further OCR."""
    validate_roster_report(report, path)
    matches = [
        card
        for card in report.get("operators", [])
        if character_id in card.get("character_ids", [])
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise CheckpointError("Roster character identity is duplicated or ambiguous")
    card = matches[0]
    rect = card.get("flag_rect", [])
    closed = report.get("closed_role_menu") or {}
    right_limit = (
        1280
        if closed.get("task") == "SandRoster@RoleMenuClosed"
        and closed.get("score", 0) >= 0.90
        and closed.get("text") == "Vanguard"
        else 1150
    )
    if (
        card.get("character_ids") != [character_id]
        or card.get("name_score", 0) < 0.90
        or card.get("flag_score", 0) < 0.85
        or type(card.get("selected")) is not bool
        or len(rect) != 4
        or any(type(value) is not int for value in rect)
        or not (
            380 <= rect[0]
            and 70 <= rect[1]
            and rect[0] + 300 <= right_limit
            and rect[1] + 120 <= 640
        )
        or not (0 < rect[2] <= 40 and 0 < rect[3] <= 40)
    ):
        raise CheckpointError(
            "Roster actor lacks a unique confident identity and complete reviewed card"
        )
    return {
        "character_id": character_id,
        "native_name": card["name"],
        "selected": card["selected"],
        "flag_rect": rect,
        "image": str(path),
        "inputs_issued": False,
        "elite_candidate": card.get("elite"),
        "level_candidate": card.get("level"),
        "elite_verified": False,
        "level_verified": False,
    }


def confirm_unselected(runtime, path, card):
    """A missing yellow marker alone cannot authorize a selection toggle."""
    x, y, _w, _h = card["flag_rect"]
    report = runtime.analyze(
        path,
        "templ",
        templates=["SandRosterUnselectedStrip.png"],
        task="SandRoster@Unselected",
        roi=[x + 205, y + 23, 25, 10],
    )
    if (
        not isinstance(report.get("image"), str)
        or Path(report["image"]).resolve() != Path(path).resolve()
    ):
        raise CheckpointError("Unselected-card proof belongs to another screenshot")
    hits = [
        item
        for item in report.get("results", [])
        if item.get("template") == "SandRosterUnselectedStrip.png"
        and item.get("hit") is True
        and item.get("score", 0) >= 0.95
    ]
    if len(hits) != 1:
        raise CheckpointError(
            "Actor is not positively unselected; no selection toggle submitted"
        )
    return hits[0]


ROSTER_ROLES = (
    "Pioneer",
    "Warrior",
    "Tank",
    "Sniper",
    "Caster",
    "Medic",
    "Support",
    "Special",
)


def find_roster_role(runtime, path, role):
    """Read a class control only inside the positively identified open RA Job menu."""
    if role not in ROSTER_ROLES:
        raise CheckpointError("Unsupported native roster class")
    gates = [
        "SandRoster@PageClear",
        "SandRoster@PageConfirm",
        "SandRoster@RoleMenuOpen",
    ]
    selected_tasks = ["SandRoster@RoleSelected" + name for name in ROSTER_ROLES]
    target = "SandRoster@Role" + role
    hits = runtime.matches(path, [*gates, target, *selected_tasks])
    if (
        any(hits.get(task, {}).get("score", 0) < 0.85 for task in gates[:2])
        or hits.get(gates[2], {}).get("score", 0) < 0.95
    ):
        raise CheckpointError(
            "Class filtering requires the identified roster and already-open Job menu"
        )
    selected = [
        name
        for name in ROSTER_ROLES
        if hits.get("SandRoster@RoleSelected" + name, {}).get("score", 0) >= 0.99
    ]
    if len(selected) > 1:
        raise CheckpointError(
            "Multiple class highlights are ambiguous; no class toggle submitted"
        )
    active = selected == [role]
    proof = hits.get("SandRoster@RoleSelected" + role if active else target, {})
    rect = proof.get("rect", [])
    row = 160 + 60 * ROSTER_ROLES.index(role)
    if (
        proof.get("score", 0) < (0.99 if active else 0.95)
        or len(rect) != 4
        or any(type(value) is not int for value in rect)
        or not (
            1170 <= rect[0]
            and rect[0] + rect[2] <= 1245
            and row - 30 <= rect[1]
            and rect[1] + rect[3] <= row + 30
        )
        or min(rect[2:]) <= 0
    ):
        raise CheckpointError("Requested class lacks a confident complete menu control")
    return {
        "role": role,
        "selected": active,
        "flag_rect": rect,
        "image": str(path),
        "unselected_evidence": None if active else proof,
        "inputs_issued": False,
    }


class RosterSelector:
    """Prepare one visible actor before DayRunner; no formation confirmation or battle launch."""

    selection_namespace = "roster_selections"
    target_field = "character_id"
    control_kind = "portrait"
    verified_event = "roster_actor_selection_verified"

    def __init__(self, runtime, journal, *, allow_experimental=False, pack=None):
        from maa_sand_navigation import CampaignNavigator

        self.rt, self.journal = runtime, journal
        self.allow_experimental = allow_experimental
        self.nav = CampaignNavigator(runtime, pack)

    def observe(self, character_id):
        path, _states = self.nav.frame("roster-actor-selection")
        card = find_roster_card(self.rt, path, character_id)
        if card is None:
            raise CheckpointError(
                "Requested actor is not identified on this visible roster page"
            )
        return card

    def selection_point(self, card):
        x, y, _w, _h = card["flag_rect"]
        return [
            x + 60,
            y + 50,
        ]  # Portrait body, outside class/name/skill/provision controls.

    def unselected_proof(self, card):
        return confirm_unselected(self.rt, card["image"], card)

    def verification_fields(self, card):
        return {
            "squad_verified": False,
            "skills_verified": False,
            "formation_committed": False,
            "expedition_started": False,
        }

    def select_visible(self, character_id, selection_id):
        if self.allow_experimental is not True:
            raise CheckpointError(
                "Live roster selection requires explicit experimental execution"
            )
        if (
            not isinstance(selection_id, str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", selection_id) is None
        ):
            raise CheckpointError(
                "Roster selection needs a stable explicit selection ID"
            )
        with self.journal.locked() as journal:
            if any(
                item.get("status") != "verified"
                for item in journal.data.get("acts", {}).values()
            ):
                raise CheckpointError(
                    "Resolve the pending paid Act before roster preparation"
                )
            selections = journal.data.setdefault(self.selection_namespace, {})
            entry = selections.get(selection_id)
            if entry is not None and (
                entry.get(self.target_field) != character_id
                or entry.get("status") not in ("pending", "verified")
            ):
                raise CheckpointError(
                    "Selection ID belongs to another target or unknown journal state"
                )
            if any(
                key != selection_id and item.get("status") != "verified"
                for key, item in selections.items()
            ):
                raise CheckpointError(
                    "Another roster selection is unresolved; do not start another toggle"
                )
            card = self.observe(character_id)
            if (
                entry is not None
                and entry["status"] == "verified"
                and not card["selected"]
            ):
                raise CheckpointError(
                    "Previously verified actor is no longer selected; review before a new selection ID"
                )
            if entry is None and not card["selected"]:
                previous = card
                # Reordering/scroll animation must settle before a portrait click.
                for _ in range(4):
                    time.sleep(0.25)
                    card = self.observe(character_id)
                    if card["selected"] or card["flag_rect"] == previous["flag_rect"]:
                        break
                    previous = card
                else:
                    raise CheckpointError(
                        "Roster actor did not remain on a stable card; no selection submitted"
                    )
                if not card["selected"]:
                    unselected = self.unselected_proof(card)
                    point = self.selection_point(card)
                    entry = {
                        "status": "pending",
                        self.target_field: character_id,
                        "before": card,
                        "input_intent_saved": True,
                        "click_returned": False,
                        "input_point": point,
                        "input_control": self.control_kind,
                        "unselected_evidence": unselected,
                    }
                    selections[selection_id] = entry
                    journal.save()  # Durable before the single toggle, including a lost response.
                    self.rt.click(tuple(point))
                    entry["click_returned"] = True
                    journal.save()
            if (
                entry is not None
                and entry["status"] == "pending"
                and not card["selected"]
            ):
                if entry.get("input_intent_saved") is not True:
                    raise CheckpointError(
                        "Pending roster selection has no recognized input ownership"
                    )
                for _ in range(4):
                    time.sleep(0.25)
                    card = self.observe(character_id)
                    entry["last_observation"] = card
                    journal.save()
                    if card["selected"]:
                        break
                else:
                    entry["error"] = (
                        "Selection remains unconfirmed; toggle not repeated"
                    )
                    journal.save()
                    raise CheckpointError(
                        "Selection remains unconfirmed; pending intent preserved and toggle not repeated"
                    )
            result = {
                **(entry or {}),
                "status": "verified",
                self.target_field: character_id,
                "selection_current": True,
                "observation": card,
                **self.verification_fields(card),
            }
            selections[selection_id] = result
            journal.save()
            self.rt.log(
                self.verified_event,
                **{
                    "selection_id": selection_id,
                    self.target_field: character_id,
                    "image": card["image"],
                    "input_intent_saved": result.get("input_intent_saved", False),
                },
            )
            return copy.deepcopy(result)


class RosterEntrySelector(RosterSelector):
    """Open Quick Select once, reusing the durable single-input selection protocol."""

    selection_namespace = "roster_entries"
    target_field = "menu"
    control_kind = "quick_select"
    verified_event = "roster_entry_verified"

    def observe(self, menu):
        if menu != "operator_roster":
            raise CheckpointError("Only the operator roster entry is supported")
        path, _states = self.nav.frame("roster-entry")
        gates = ["SandAuto@Squad", "SandRoster@PageClear", "SandRoster@PageConfirm"]
        hits = self.rt.matches(path, gates)
        roster = all(hits.get(task, {}).get("score", 0) >= 0.85 for task in gates[1:])
        formation = hits.get(gates[0], {}).get("score", 0) >= 0.9
        if roster and formation:
            raise CheckpointError(
                "Conflicting formation and roster controls; no entry submitted"
            )
        if roster:
            return {
                "menu": menu,
                "selected": True,
                "flag_rect": None,
                "image": str(path),
                "inputs_issued": False,
            }
        button = hits.get(gates[0], {})
        rect = button.get("rect", [])
        if (
            not formation
            or len(rect) != 4
            or any(type(v) is not int for v in rect)
            or not (
                790 <= rect[0]
                and 10 <= rect[1]
                and rect[0] + rect[2] <= 930
                and rect[1] + rect[3] <= 70
                and min(rect[2:]) > 0
            )
        ):
            raise CheckpointError(
                "Quick Select is not identified on the formation screen"
            )
        return {
            "menu": menu,
            "selected": False,
            "flag_rect": rect,
            "image": str(path),
            "unselected_evidence": button,
            "inputs_issued": False,
        }

    def selection_point(self, card):
        x, y, w, h = card["flag_rect"]
        return [x + w // 2, y + h // 2]

    def unselected_proof(self, card):
        return card["unselected_evidence"]

    def open(self, entry_id):
        return self.select_visible("operator_roster", entry_id)


class RosterConfirmationSelector(RosterEntrySelector):
    """Confirm roster once, then require the exact requested final formation."""

    selection_namespace = "roster_confirmations"
    control_kind = "added_to_squad"
    verified_event = "roster_confirmation_verified"

    def __init__(
        self,
        runtime,
        journal,
        names,
        battle_data_path,
        *,
        allow_experimental=False,
        pack=None,
    ):
        super().__init__(
            runtime, journal, allow_experimental=allow_experimental, pack=pack
        )
        from maa_sand_squad import resolve_squad

        resolved = resolve_squad(names, battle_data_path)
        self.names, self.battle_data_path = list(names), Path(battle_data_path)
        self.target = "formation:" + ",".join(
            actor["character_id"] for actor in resolved["actors"]
        )

    def observe(self, menu):
        if menu != self.target:
            raise CheckpointError(
                "Formation confirmation target differs from requested actors"
            )
        path, _states = self.nav.frame("roster-confirmation")
        gates = ["SandAuto@Squad", "SandRoster@PageClear", "SandRoster@PageConfirm"]
        hits = self.rt.matches(path, gates)
        roster = all(hits.get(task, {}).get("score", 0) >= 0.85 for task in gates[1:])
        formation = hits.get(gates[0], {}).get("score", 0) >= 0.9
        if roster and formation:
            raise CheckpointError(
                "Conflicting roster and formation controls; confirmation stopped"
            )
        if formation:
            from maa_sand_squad import verify_exact_squad

            proof = verify_exact_squad(self.rt, path, self.names, self.battle_data_path)
            return {
                "menu": menu,
                "selected": True,
                "flag_rect": None,
                "image": str(path),
                "squad_proof": proof,
                "inputs_issued": False,
            }
        button = hits.get(gates[2], {})
        rect = button.get("rect", [])
        if (
            not roster
            or len(rect) != 4
            or any(type(v) is not int for v in rect)
            or not (
                990 <= rect[0]
                and 645 <= rect[1]
                and rect[0] + rect[2] <= 1250
                and rect[1] + rect[3] <= 710
                and min(rect[2:]) > 0
            )
        ):
            raise CheckpointError(
                "Added to Squad control is not identified on the roster screen"
            )
        return {
            "menu": menu,
            "selected": False,
            "flag_rect": rect,
            "image": str(path),
            "unselected_evidence": button,
            "inputs_issued": False,
        }

    def verification_fields(self, card):
        return {
            "squad_verified": True,
            "squad_proof": card["squad_proof"],
            "skills_verified": False,
            "formation_committed": True,
            "expedition_started": False,
        }

    def confirm(self, confirmation_id):
        return self.select_visible(self.target, confirmation_id)


class RosterRoleSelector(RosterSelector):
    """Reuse the same durable one-toggle protocol for an already-open class menu."""

    selection_namespace = "roster_role_changes"
    target_field = "role"
    control_kind = "class_filter"
    verified_event = "roster_role_filter_verified"

    def observe(self, role):
        path, _states = self.nav.frame("roster-class-selection")
        return find_roster_role(self.rt, path, role)

    def selection_point(self, card):
        x, y, w, h = card["flag_rect"]
        return [x + w // 2, y + h // 2]

    def unselected_proof(self, card):
        return card["unselected_evidence"]

    def select_visible_role(self, role, selection_id):
        return self.select_visible(role, selection_id)


class RosterSearcher:
    """Bounded view navigation inside an already selected class; never selects an actor."""

    def __init__(self, runtime, *, allow_experimental=False, pack=None):
        from maa_sand_navigation import CampaignNavigator

        self.rt = runtime
        self.allow_experimental = allow_experimental
        self.nav = CampaignNavigator(runtime, pack)

    def page(self, character_id, role):
        path, _states = self.nav.frame("roster-page-search")
        current = find_roster_role(self.rt, path, role)
        if not current["selected"]:
            raise CheckpointError("Select the requested class before paging its roster")
        report = read_roster(self.rt, path)
        target = roster_card(report, path, character_id)
        signature = []
        for observed in report.get("operators", []):
            ids = observed.get("character_ids", [])
            if (
                len(ids) != 1
                or observed.get("name_score", 0) < 0.9
                or observed.get("flag_score", 0) < 0.85
            ):
                continue
            try:
                card = roster_card(report, path, ids[0])
            except CheckpointError:
                continue
            if card:
                signature.append((ids[0], *card["flag_rect"]))
        if target is None and not signature:
            raise CheckpointError(
                "Roster page has no confident identities; do not swipe an unreadable page"
            )
        return {
            "image": str(path),
            "card": target,
            "signature": tuple(sorted(signature)),
        }

    def seek(self, character_id, role, *, maximum_pages=12, maximum_rewinds=12):
        if self.allow_experimental is not True:
            raise CheckpointError(
                "Roster page gestures require explicit experimental execution"
            )
        if (
            not isinstance(character_id, str)
            or not character_id.startswith("char_")
            or role not in ROSTER_ROLES
            or type(maximum_pages) is not int
            or not 1 <= maximum_pages <= 20
            or type(maximum_rewinds) is not int
            or not 0 <= maximum_rewinds <= 20
        ):
            raise CheckpointError(
                "Roster search needs an exact character/class and bounded page limits"
            )
        page = self.page(character_id, role)
        gestures = []

        def found():
            result = {
                "status": "roster_actor_located",
                "character_id": character_id,
                "role": role,
                "observation": page["card"],
                "image": page["image"],
                "gestures": list(gestures),
                "selection_submitted": False,
                "formation_committed": False,
                "expedition_started": False,
            }
            self.rt.log("roster_actor_located", **result)
            return result

        if page["card"] is not None:
            return found()
        # A bounded rewind avoids treating an arbitrary starting page as the beginning.
        for _ in range(maximum_rewinds):
            self.rt.task("SandRoster@PageBackward")
            gestures.append("backward")
            after = self.page(character_id, role)
            if after["card"] is not None:
                page = after
                return found()
            if after["signature"] == page["signature"]:
                page = after
                break  # Boundary or ignored input; this never proves complete inventory coverage.
            page = after
        else:
            if maximum_rewinds:
                raise CheckpointError(
                    "Roster rewind limit reached without a stable boundary; no actor selected"
                )
        for _ in range(maximum_pages):
            self.rt.task("SandRoster@PageForward")
            gestures.append("forward")
            after = self.page(character_id, role)
            if after["card"] is not None:
                page = after
                return found()
            if after["signature"] == page["signature"]:
                raise CheckpointError(
                    "Roster page stopped changing or swipe was ignored; ownership is not inferred"
                )
            page = after
        raise CheckpointError(
            "Actor not found within bounded observed pages; ownership is not inferred"
        )
