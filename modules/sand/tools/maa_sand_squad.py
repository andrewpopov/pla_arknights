"""Prepare requested RA actors by composing existing native-backed roster steps."""

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from maa_sand_config import (
    CheckpointError,
    validate_formation_power,
    validate_formation_skills,
)
from maa_sand_formation import (
    ROSTER_ROLES,
    RosterRoleSelector,
    RosterSearcher,
    RosterSelector,
    find_roster_role,
    read_roster,
    roster_card,
)
from maa_sand_navigation import CampaignNavigator


def resolve_squad(names, battle_data_path):
    """Resolve exact English guide names through MAA BattleData, without an alias table."""
    if (
        not isinstance(names, list)
        or len(names) > 6
        or any(not isinstance(name, str) or not name for name in names)
        or len(set(names)) != len(names)
    ):
        raise CheckpointError(
            "Requested actors must be up to six unique exact English names"
        )
    raw = Path(battle_data_path).read_bytes()
    data = json.loads(raw)
    actors = []
    for name in names:
        candidates = [
            (key, value)
            for key, value in data["chars"].items()
            if key.startswith("char_")
            and value.get("name_en") == name
            and value.get("profession", "").title() in ROSTER_ROLES
        ]
        if len(candidates) != 1:
            raise CheckpointError(
                f"Guide actor must resolve to one exact native character identity: {name}"
            )
        character_id, entry = candidates[0]
        actors.append(
            {
                "name": name,
                "character_id": character_id,
                "native_name": entry["name"],
                "role": entry["profession"].title(),
            }
        )
    return {
        "actors": actors,
        "battle_data_sha256": hashlib.sha256(raw).hexdigest(),
        "ownership_verified": False,
        "skills_verified": False,
        "elite_verified": False,
    }


def verify_exact_squad(runtime, path, names, battle_data_path):
    """Read every visible RA formation slot; certify names only, without issuing input."""
    resolved = resolve_squad(names, battle_data_path)

    def normalized(text):
        return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", text)).casefold()

    wanted = {normalized(actor["name"]): actor for actor in resolved["actors"]}
    tasks = ["SandAuto@Squad", "SandAuto@SquadMlynarSelectedS3"]
    tasks += [f"SandAuto@SquadName{i}" for i in range(1, 8)]
    tasks += [f"SandAuto@EmptySquadSlot{i}" for i in range(1, 8)]
    hits = runtime.matches(path, tasks)
    if hits.get("SandAuto@Squad", {}).get("score", 0) < 0.9:
        raise CheckpointError(
            "Exact squad verification requires the English formation screen"
        )
    observed, slots = [], []
    for index in range(1, 8):
        card = hits.get(f"SandAuto@SquadName{index}", {})
        empty = hits.get(f"SandAuto@EmptySquadSlot{index}", {}).get("score", 0) >= 0.9
        key = normalized(card.get("text", "")) if card.get("score", 0) >= 0.85 else None
        # Existing Mlynar fallback requires the S3 icon on this same card.
        if key in {"mlynar", "mtynar", "miynar"} and normalized("Młynar") in wanted:
            skill = hits.get("SandAuto@SquadMlynarSelectedS3", {})
            rect, icon = card.get("rect", []), skill.get("rect", [])
            if (
                skill.get("score", 0) >= 0.95
                and len(rect) == len(icon) == 4
                and abs(icon[0] - (rect[0] + 193)) <= 3
                and abs(icon[1] - (rect[1] + 36)) <= 3
            ):
                key = normalized("Młynar")
        actor = wanted.get(key)
        if empty:
            if actor is not None:
                raise CheckpointError(
                    "Formation slot has conflicting actor and empty evidence"
                )
            slots.append({"slot": index, "empty": True})
            continue
        if actor is None:
            raise CheckpointError(
                f"Formation slot {index} has an extra or unreadable operator"
            )
        if actor["character_id"] in observed:
            raise CheckpointError("Formation has duplicate operator evidence")
        observed.append(actor["character_id"])
        slots.append(
            {
                "slot": index,
                "character_id": actor["character_id"],
                "name": actor["name"],
            }
        )
    expected = {actor["character_id"] for actor in resolved["actors"]}
    if set(observed) != expected:
        raise CheckpointError("Exact formation is missing a requested operator")
    return {
        "image": str(path),
        "status": "exact_squad_verified",
        "squad_verified": True,
        "operator_count": len(observed),
        "slots": slots,
        "battle_data_sha256": resolved["battle_data_sha256"],
        "skills_verified": False,
        "tools_verified": False,
        "elite_verified": False,
        "inputs_issued": False,
        "expedition_started": False,
    }


def read_formation_rank(runtime, path, slot, skill):
    """Reuse native formation rank templates at the saved-image validated RA scale."""
    roi = [
        355 + 510 * (slot > 4) + 69 * (skill - 1),
        132 + 140 * ((slot - 1) % 4),
        22,
        22,
    ]
    roi = [round(value * 1.2) for value in roi]
    templates = [
        f"BattleQuickFormationSkillLevel-{rank:02d}.png" for rank in (7, 8, 9, 10)
    ]
    report = runtime.analyze(
        path,
        "templ",
        templates=templates,
        threshold=0.75,
        roi=roi,
        resize=[1536, 864],
        task="BattleQuickFormationSkillLevel-Check",
    )
    if (
        report.get("mode") != "templ"
        or not isinstance(report.get("image"), str)
        or Path(report["image"]).resolve() != Path(path).resolve()
    ):
        raise CheckpointError(
            "Native formation rank report belongs to another image or mode"
        )
    results = report.get("results", [])
    if (
        len(results) != 4
        or {r.get("template") for r in results} != set(templates)
        or any(
            "error" in r
            or type(r.get("score")) not in (int, float)
            or not 0 <= r["score"] <= 1
            for r in results
        )
    ):
        raise CheckpointError("Native formation rank results are incomplete or invalid")
    best, second = sorted(results, key=lambda r: r["score"], reverse=True)[:2]
    rank = int(best["template"].split("-")[-1].split(".")[0])
    score_floor, gap_floor = (0.9, 0.15) if rank == 10 else (0.75, 0.2)
    rect = best.get("rect", [])
    if (
        rank not in (7, 10)
        or best["score"] < score_floor
        or best["score"] - second["score"] < gap_floor
        or len(rect) != 4
        or any(type(v) is not int for v in rect)
        or not (
            roi[0] <= rect[0]
            and roi[1] <= rect[1]
            and min(rect[2:]) > 0
            and rect[0] + rect[2] <= roi[0] + roi[2]
            and rect[1] + rect[3] <= roi[1] + roi[3]
        )
    ):
        raise CheckpointError(
            "Formation skill rank is ambiguous or lacks validated positive evidence"
        )
    return {
        "rank": rank,
        "score": best["score"],
        "runner_up_score": second["score"],
        "image": str(path),
        "roi": roi,
        "scale": 1.2,
        "template": best["template"],
    }


def selected_formation_skill(hits, slot):
    """Require both native border probes and exactly one selected skill index."""
    complete, partial = [], []
    for skill in range(1, 4):
        parts = [
            hits.get(f"SandFormation@Slot{slot}Skill{skill}{part}", {}).get("score", 0)
            >= 0.99
            for part in ("Corner", "Bottom")
        ]
        if all(parts):
            complete.append(skill)
        elif any(parts):
            partial.append(skill)
    if len(complete) != 1 or partial:
        raise CheckpointError(
            "Formation skill is not uniquely selected on the identified actor card"
        )
    return complete[0]


def verify_formation_skills(
    runtime, path, names, requirements, battle_data_path, *, minimum_ranks=None
):
    """Verify explicitly supported selected skill icons on their exact actor cards."""
    minimum_ranks = {} if minimum_ranks is None else minimum_ranks
    validate_formation_skills(requirements, names, minimum_ranks)
    squad = verify_exact_squad(runtime, path, names, battle_data_path)
    proofs = []
    slots = {row["name"]: row["slot"] for row in squad["slots"] if "name" in row}
    tasks = [
        f"SandFormation@Slot{slots[name]}Skill{skill}{part}"
        for name in requirements
        for skill in range(1, 4)
        for part in ("Corner", "Bottom")
    ]
    hits = runtime.matches(path, tasks) if tasks else {}
    for name, expected in requirements.items():
        slot = slots[name]
        if selected_formation_skill(hits, slot) != expected:
            raise CheckpointError(
                f"Required skill {expected} is not uniquely selected on the {name} formation card"
            )
        proofs.append(
            {
                "name": name,
                "skill": expected,
                "slot": slot,
                "border_parts": ["Corner", "Bottom"],
            }
        )
    if requirements.get("Młynar") == 3:
        skill = runtime.matches(path, ["SandAuto@SquadMlynarSelectedS3"]).get(
            "SandAuto@SquadMlynarSelectedS3", {}
        )
        slot = slots["Młynar"]
        x, y = (300 if slot <= 4 else 810), 96 + 140 * ((slot - 1) % 4)
        rect = skill.get("rect", [])
        if (
            skill.get("score", 0) < 0.95
            or len(rect) != 4
            or abs(rect[0] - (x + 193)) > 3
            or abs(rect[1] - (y + 36)) > 3
        ):
            raise CheckpointError(
                "Required Mlynar S3 is not selected on his actual formation card"
            )
    rank_proofs = {}
    for name, minimum in minimum_ranks.items():
        rank = read_formation_rank(runtime, path, slots[name], requirements[name])
        if rank["rank"] < minimum:
            raise CheckpointError(
                f"{name} selected skill rank is below the route requirement"
            )
        rank_proofs[name] = rank
    return {
        "image": str(path),
        "status": "required_formation_skills_verified",
        "required_skills_verified": True,
        "requirements": requirements,
        "proofs": proofs,
        "all_squad_skills_verified": False,
        "rank_verified": bool(minimum_ranks),
        "minimum_ranks": minimum_ranks,
        "rank_proofs": rank_proofs,
        "inputs_issued": False,
    }


def read_formation_level(runtime, path, slot, maximum):
    roi = [258 + 510 * (slot > 4), 167 + 140 * ((slot - 1) % 4), 41, 28]
    reads = runtime.ocr(path, roi)
    if len(reads) != 1:
        raise CheckpointError("Formation level needs one complete native numeric read")
    read = reads[0]
    text, rect = read.get("text"), read.get("rect", [])
    if not isinstance(text, str):
        raise CheckpointError("Formation level did not return numeric text")
    text = text.strip()
    if (
        read.get("score", 0) < 0.95
        or re.fullmatch(r"[0-9]{1,2}", text) is None
        or not 1 <= int(text) <= maximum
        or len(rect) != 4
        or any(type(v) is not int for v in rect)
        or not (
            roi[0] <= rect[0]
            and roi[1] <= rect[1]
            and min(rect[2:]) > 0
            and rect[0] + rect[2] <= roi[0] + roi[2]
            and rect[1] + rect[3] <= roi[1] + roi[3]
        )
    ):
        raise CheckpointError(
            "Formation level is uncertain, outside its actor card, or impossible for that operator"
        )
    return {"image": str(path), "level": int(text), "read": read, "roi": roi}


def verify_formation_power(
    runtime, path, names, levels, elites, required_skills, battle_data_path, pack
):
    """Verify level and a conservative promotion lower bound from game-data caps/unlocks."""
    validate_formation_power(levels, elites, names)
    validate_formation_skills(required_skills, names)
    squad = verify_exact_squad(runtime, path, names, battle_data_path)
    actors = {
        row["name"]: row for row in resolve_squad(names, battle_data_path)["actors"]
    }
    slots = {row["name"]: row["slot"] for row in squad["slots"] if "name" in row}
    catalog = json.loads(
        (Path(pack) / "campaign/formation-power.json").read_text(encoding="utf8")
    )
    if catalog.get("schema_version") != 1:
        raise CheckpointError("Unsupported formation power catalog")
    tasks = [
        f"SandFormation@Slot{slots[name]}Skill{skill}{part}"
        for name in levels
        if name in required_skills
        for skill in range(1, 4)
        for part in ("Corner", "Bottom")
    ]
    hits = runtime.matches(path, tasks) if tasks else {}
    proofs = {}
    for name, minimum in levels.items():
        entry = catalog["operators"].get(actors[name]["character_id"], {})
        caps, unlocks = entry.get("phase_level_caps"), entry.get("skill_unlock_phases")
        if (
            entry.get("name") != name
            or not isinstance(caps, list)
            or not 1 <= len(caps) <= 3
            or any(type(cap) is not int or not 1 <= cap <= 90 for cap in caps)
            or caps != sorted(set(caps))
            or not isinstance(unlocks, list)
            or any(
                type(elite) is not int or not 0 <= elite < len(caps)
                for elite in unlocks
            )
        ):
            raise CheckpointError(
                "Missing or invalid native actor promotion-cap metadata"
            )
        proof = read_formation_level(runtime, path, slots[name], max(caps))
        lower_bound = max(
            [0]
            + [index + 1 for index, cap in enumerate(caps[:-1]) if proof["level"] > cap]
        )
        if name in required_skills:
            skill = selected_formation_skill(hits, slots[name])
            if skill != required_skills[name] or skill > len(unlocks):
                raise CheckpointError(
                    "Selected skill does not match the required native unlock metadata"
                )
            lower_bound = max(lower_bound, unlocks[skill - 1])
            proof["selected_skill"] = skill
        if proof["level"] < minimum or lower_bound < elites.get(name, 0):
            raise CheckpointError(
                f"{name} does not meet the guide level/promotion requirement"
            )
        proofs[name] = {
            **proof,
            "minimum_elite_proven": lower_bound,
            "phase_level_caps": caps,
        }
    return {
        "status": "required_formation_power_verified",
        "image": str(path),
        "power_verified": bool(levels),
        "minimum_levels": levels,
        "minimum_elites": elites,
        "operators": proofs,
        "exact_elite_verified": False,
        "source_sha256": catalog["source_sha256"],
        "inputs_issued": False,
    }


def verify_launch_squad(player, path, names, *, requirements=None):
    """Bind the exact-team observer to the same frame used for paid launch checks."""
    proof = player.verify_requested_campaign_squad(path, names=names)
    if (
        not isinstance(proof, dict)
        or proof.get("status") != "exact_squad_verified"
        or proof.get("squad_verified") is not True
        or proof.get("image") != str(path)
        or type(proof.get("operator_count")) is not int
        or proof["operator_count"] != len(names)
    ):
        raise CheckpointError("Exact squad not verified on actual launch frame")
    if requirements is None:
        requirements = player.profile.get("required_formation_skills", {})
    if requirements:
        skills = player.verify_required_campaign_skills(path, names=names)
        if (
            not isinstance(skills, dict)
            or skills.get("required_skills_verified") is not True
            or skills.get("image") != str(path)
            or skills.get("requirements") != requirements
        ):
            raise CheckpointError("Required skills not verified on actual launch frame")
        ranks = player.profile.get("required_formation_ranks", {})
        if ranks and (
            skills.get("rank_verified") is not True
            or skills.get("minimum_ranks") != ranks
        ):
            raise CheckpointError(
                "Required skill ranks not verified on actual launch frame"
            )
        proof = {**proof, "required_skills": skills}
    levels = player.profile.get("required_formation_levels", {})
    elites = player.profile.get("required_formation_elites", {})
    if levels or elites:
        power = player.verify_campaign_power(path, names=names)
        if (
            not isinstance(power, dict)
            or power.get("power_verified") is not True
            or power.get("image") != str(path)
            or power.get("minimum_levels") != levels
            or power.get("minimum_elites") != elites
        ):
            raise CheckpointError(
                "Required operator power not verified on actual launch frame"
            )
        proof = {**proof, "required_power": power}
    return proof


class FormationSkillSelector(RosterSelector):
    """Set one unlocked formation skill through the existing one-click journal protocol."""

    selection_namespace = "formation_skill_selections"
    target_field = "skill_target"
    control_kind = "formation_skill_icon"
    verified_event = "formation_skill_selection_verified"

    def __init__(
        self,
        runtime,
        journal,
        names,
        name,
        skill,
        battle_data_path,
        *,
        minimum_rank=None,
        allow_experimental=False,
        pack=None,
    ):
        super().__init__(
            runtime, journal, allow_experimental=allow_experimental, pack=pack
        )
        validate_formation_skills(
            {name: skill}, names, {} if minimum_rank is None else {name: minimum_rank}
        )
        self.minimum_rank = minimum_rank
        resolved = resolve_squad(names, battle_data_path)
        self.names, self.name, self.skill = list(names), name, skill
        self.battle_data_path = Path(battle_data_path)
        identity = [
            [actor["character_id"] for actor in resolved["actors"]],
            name,
            skill,
            minimum_rank,
        ]
        self.target = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False).encode("utf8")
        ).hexdigest()

    def observe(self, target):
        if target != self.target:
            raise CheckpointError("Formation skill selection target changed")
        path, _states = self.nav.frame("formation-skill-selection")
        squad = verify_exact_squad(self.rt, path, self.names, self.battle_data_path)
        slot = next(
            row["slot"] for row in squad["slots"] if row.get("name") == self.name
        )
        tasks = [
            f"SandFormation@Slot{slot}Skill{skill}{part}"
            for skill in range(1, 4)
            for part in ("Corner", "Bottom")
        ]
        selected = selected_formation_skill(self.rt.matches(path, tasks), slot)
        rank = (
            None
            if selected == self.skill and self.minimum_rank is None
            else read_formation_rank(self.rt, path, slot, self.skill)
        )
        if self.minimum_rank is not None and rank["rank"] < self.minimum_rank:
            raise CheckpointError(
                "Requested skill is unlocked but below the route rank requirement"
            )
        rect = [
            355 + 510 * (slot > 4) + 69 * (self.skill - 1),
            132 + 140 * ((slot - 1) % 4),
            65,
            65,
        ]
        return {
            "name": self.name,
            "skill": self.skill,
            "selected_skill": selected,
            "selected": selected == self.skill,
            "flag_rect": rect,
            "image": str(path),
            "squad_proof": squad,
            "unlocked_target_rank": rank,
            "inputs_issued": False,
        }

    def selection_point(self, card):
        x, y, w, h = card["flag_rect"]
        return [x + w // 2, y + h // 2]

    def unselected_proof(self, card):
        if card["unlocked_target_rank"] is None or card["selected_skill"] == self.skill:
            raise CheckpointError(
                "Skill correction requires a different selected skill and unlocked target proof"
            )
        return {
            "selected_skill": card["selected_skill"],
            "target_rank": card["unlocked_target_rank"],
        }

    def verification_fields(self, card):
        return {
            "squad_verified": True,
            "squad_proof": card["squad_proof"],
            "skill_selection_verified": True,
            "selected_skill": self.skill,
            "name": self.name,
            "skills_verified": False,
            "formation_committed": False,
            "expedition_started": False,
        }

    def select_skill(self, selection_id):
        return self.select_visible(self.target, selection_id)


class RequestedActorsPreparer:
    """Add requested actors in an open roster; never clear or confirm a formation."""

    def __init__(
        self, runtime, journal, battle_data_path, *, allow_experimental=False, pack=None
    ):
        self.rt, self.journal = runtime, journal
        self.battle_data_path = Path(battle_data_path)
        self.enabled = allow_experimental
        self.nav = CampaignNavigator(runtime, pack)
        self.roles = RosterRoleSelector(
            runtime, journal, allow_experimental=allow_experimental, pack=pack
        )
        self.search = RosterSearcher(
            runtime, allow_experimental=allow_experimental, pack=pack
        )
        self.select = RosterSelector(
            runtime, journal, allow_experimental=allow_experimental, pack=pack
        )

    def prepare(self, names, scope):
        if self.enabled is not True:
            raise CheckpointError(
                "Actor preparation requires explicit experimental execution"
            )
        if (
            not isinstance(scope, str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,40}", scope) is None
        ):
            raise CheckpointError(
                "Actor preparation requires a stable explicit scope ID"
            )
        resolved = resolve_squad(names, self.battle_data_path)
        actors = resolved["actors"]
        if not actors:
            raise CheckpointError(
                "Use the existing empty-squad routine for a zero-operator trip"
            )
        with self.journal.locked() as journal:
            preparations = journal.data.setdefault("roster_preparations", {})
            entry = preparations.get(scope)
            if entry is not None and entry.get("actors") != actors:
                raise CheckpointError(
                    "Preparation scope belongs to a different requested roster"
                )
            if entry is not None and entry.get("status") == "prepared":
                return {
                    **copy.deepcopy(entry),
                    "already_prepared": True,
                    "current_squad_verified": False,
                }
            if entry is not None and entry.get("status") != "pending":
                raise CheckpointError("Unknown roster preparation journal state")
            if any(
                key != scope and item.get("status") != "prepared"
                for key, item in preparations.items()
            ):
                raise CheckpointError("Another roster preparation is unresolved")
            if any(
                item.get("status") != "verified"
                for item in journal.data.get("acts", {}).values()
            ):
                raise CheckpointError(
                    "Resolve the pending paid Act before actor preparation"
                )
            if entry is None:
                # Read-only initial review before recording a preparation intent.
                path, _states = self.nav.frame("requested-actors-before")
                find_roster_role(
                    self.rt, path, actors[0]["role"]
                )  # Requires the open, identified Job menu.
                report = read_roster(self.rt, path)
                wanted = {actor["character_id"] for actor in actors}
                for card in report.get("operators", []):
                    if card.get("selected") is True:
                        ids = card.get("character_ids", [])
                        if (
                            len(ids) != 1
                            or ids[0] not in wanted
                            or card.get("name_score", 0) < 0.9
                        ):
                            raise CheckpointError(
                                "Clear or review visible unwanted/uncertain selected actors before preparation"
                            )
                entry = {
                    "status": "pending",
                    "actors": actors,
                    "next_actor": 0,
                    "selections": [],
                    "battle_data_sha256": resolved["battle_data_sha256"],
                    "before_image": str(path),
                    "squad_verified": False,
                    "skills_verified": False,
                    "tools_verified": False,
                    "formation_committed": False,
                    "expedition_started": False,
                }
                preparations[scope] = entry
                journal.save()
            cursor = entry.get("next_actor")
            if (
                type(cursor) is not int
                or not 0 <= cursor <= len(actors)
                or not isinstance(entry.get("selections"), list)
                or len(entry["selections"]) != cursor
            ):
                raise CheckpointError(
                    "Preparation cursor does not match confirmed actor selections"
                )
        # Child selectors acquire the same journal individually; never hold a nested lock.
        for index in range(cursor, len(actors)):
            actor = actors[index]
            path, _states = self.nav.frame("requested-actor-current")
            visible = roster_card(
                read_roster(self.rt, path), path, actor["character_id"]
            )
            if visible is None:
                self.roles.select_visible_role(actor["role"], f"{scope}:role:{index}")
                self.search.seek(actor["character_id"], actor["role"])
            proof = self.select.select_visible(
                actor["character_id"], f"{scope}:actor:{index}"
            )
            if (
                proof.get("status") != "verified"
                or proof.get("character_id") != actor["character_id"]
                or proof.get("selection_current") is not True
            ):
                raise CheckpointError(
                    "Actor selector did not verify the requested current selection"
                )
            with self.journal.locked() as journal:
                entry = journal.data["roster_preparations"][scope]
                if entry["next_actor"] != index or entry["actors"] != actors:
                    raise CheckpointError(
                        "Preparation journal changed during a child selection"
                    )
                entry["selections"].append(proof)
                entry["next_actor"] = index + 1
                journal.save()
        with self.journal.locked() as journal:
            entry = journal.data["roster_preparations"][scope]
            if entry["next_actor"] != len(actors):
                raise CheckpointError(
                    "Not all requested actor selections were confirmed"
                )
            entry["status"] = "prepared"
            journal.save()
            result = copy.deepcopy(entry)
        self.rt.log(
            "requested_actors_prepared",
            scope=scope,
            names=names,
            squad_verified=False,
            formation_committed=False,
            expedition_started=False,
        )
        return result
