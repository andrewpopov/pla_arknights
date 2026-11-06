"""Compose existing Sand formation helpers into a durable, non-launching preparation flow."""

from maa_runtime import data_path

import copy
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from maa_sand_config import (
    CheckpointError,
    validate_formation_power,
    validate_formation_skills,
)
from maa_sand_navigation import CampaignNavigator
from maa_sand_squad import resolve_squad, verify_exact_squad, verify_launch_squad


def load_team_plan(path, pack):
    """Formation-only plans reuse roster helpers and cannot launch an expedition."""
    data = json.loads(Path(path).read_text(encoding="utf8"))
    if (
        data.get("schema_version") != 1
        or data.get("kind") != "formation-preparation"
        or data.get("autoplay_enabled") is not False
        or data.get("combat_calibrated") is not False
        or not isinstance(data.get("id"), str)
        or re.fullmatch(r"[a-z0-9_-]+", data["id"]) is None
    ):
        raise CheckpointError(
            "Require an explicit non-combat formation-preparation plan"
        )
    names = data.get("required_squad")
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 6
        or any(not isinstance(name, str) or not name for name in names)
        or len(set(names)) != len(names)
        or "steps" in data
        or "anchor_manifest" in data
    ):
        raise CheckpointError(
            "Team plans need one to six unique names and no combat or map steps"
        )
    validate_formation_skills(
        data.get("required_formation_skills", {}),
        names,
        data.get("required_formation_ranks", {}),
    )
    validate_formation_power(
        data.get("required_formation_levels", {}),
        data.get("required_formation_elites", {}),
        names,
    )
    if "stage_id" in data:
        stages = json.loads((Path(pack) / "campaign/stages.json").read_text("utf8"))[
            "stages"
        ]
        if stages.get(data["stage_id"], {}).get("english") != data.get("stage"):
            raise CheckpointError("Team stage name and ID disagree")
    return data


class CampaignTeamPreparer:
    def __init__(self, player, journal, *, allow_experimental=False):
        self.player, self.journal = player, journal
        self.enabled = allow_experimental
        self.nav = CampaignNavigator(player.rt, player.rt.pack)
        self.battle_data = player.rt.session.install / "resource/battle_data.json"
        self.names = list(player.profile["required_squad"])
        resolve_squad(self.names, self.battle_data)
        validate_formation_skills(
            player.profile.get("required_formation_skills", {}),
            self.names,
            player.profile.get("required_formation_ranks", {}),
        )
        self.target = {
            "route": player.profile["id"],
            "names": self.names,
            "skills": copy.deepcopy(
                player.profile.get("required_formation_skills", {})
            ),
            "ranks": copy.deepcopy(player.profile.get("required_formation_ranks", {})),
            "levels": copy.deepcopy(
                player.profile.get("required_formation_levels", {})
            ),
            "elites": copy.deepcopy(
                player.profile.get("required_formation_elites", {})
            ),
        }
        validate_formation_power(
            self.target["levels"], self.target["elites"], self.names
        )

    def advance(self, scope, phase, next_phase, proof):
        with self.journal.locked() as journal:
            entry = journal.data["team_preparations"][scope]
            if entry["target"] != self.target or entry["phase"] != phase:
                raise CheckpointError(
                    "Team preparation journal changed during a child operation"
                )
            entry["proofs"][phase] = proof
            entry["phase"] = next_phase
            journal.save()
        return next_phase

    def current_proof(self):
        path, _hits = self.nav.frame("campaign-team-current")
        return verify_launch_squad(self.player, path, self.names)

    def prepare(self, scope):
        if (
            self.enabled is not True
            or not isinstance(scope, str)
            or re.fullmatch(r"[A-Za-z0-9_.:-]{1,24}", scope) is None
        ):
            raise CheckpointError(
                "Team preparation needs explicit experimental execution and a stable scope ID"
            )
        fresh = False
        with self.journal.locked() as journal:
            entries = journal.data.setdefault("team_preparations", {})
            entry = entries.get(scope)
            if entry is not None and entry.get("target") != self.target:
                raise CheckpointError(
                    "Team preparation scope belongs to another route or requirements"
                )
            if any(
                key != scope and item.get("phase") != "prepared"
                for key, item in entries.items()
            ):
                raise CheckpointError("Another team preparation is unresolved")
            if any(
                item.get("status") != "verified"
                for item in journal.data.get("acts", {}).values()
            ):
                raise CheckpointError(
                    "Resolve the pending paid Act before team preparation"
                )
            if entry is None:
                path, hits = self.nav.frame(
                    "campaign-team-before", ["SandAuto@ClearSquadConfirm"]
                )
                if not self.nav.hit(hits, "SandAuto@Squad") or self.nav.hit(
                    hits, "SandAuto@ClearSquadConfirm"
                ):
                    raise CheckpointError(
                        "Team preparation starts from an identified formation without a pending clear dialog"
                    )
                try:
                    existing = verify_exact_squad(
                        self.player.rt, path, self.names, self.battle_data
                    )
                except CheckpointError:
                    existing = None
                entry = {
                    "phase": "skills_pending" if existing else "clear_pending",
                    "target": self.target,
                    "before_image": str(path),
                    "proofs": {},
                    "tools_verified": False,
                    "rested_operators_verified": False,
                    "energy_verified": False,
                    "expedition_started": False,
                }
                if existing:
                    entry["proofs"]["existing_team"] = existing
                entries[scope] = entry
                journal.save()  # A loadout reset is owned before the existing navigator can click.
                fresh = True
            phase = entry["phase"]
        if phase == "prepared":
            proof = (
                self.current_proof()
            )  # Historical preparation is never current-state proof.
            return {
                "status": "team_prepared",
                "already_prepared": True,
                "verification": proof,
                "tools_verified": False,
                "energy_verified": False,
                "rested_operators_verified": False,
                "expedition_started": False,
            }
        if phase == "clear_pending":
            if fresh:
                proof = self.nav.clear_squad()
                if (
                    proof.get("status") != "empty_squad_verified"
                    or proof.get("operator_count") != 0
                ):
                    raise CheckpointError(
                        "Existing loadout reset did not verify the empty team"
                    )
            else:
                empty = [f"SandAuto@EmptySquadSlot{i}" for i in range(1, 8)]
                path, hits = self.nav.frame(
                    "campaign-team-clear-resume", [*empty, "SandAuto@ClearSquadConfirm"]
                )
                if (
                    not self.nav.hit(hits, "SandAuto@Squad")
                    or self.nav.hit(hits, "SandAuto@ClearSquadConfirm")
                    or not all(self.nav.hit(hits, task) for task in empty)
                ):
                    raise CheckpointError(
                        "Prior loadout reset is unresolved; reset and confirmation are not repeated"
                    )
                proof = {
                    "status": "empty_squad_verified",
                    "image": str(path),
                    "operator_count": 0,
                    "recovered_without_input": True,
                }
            phase = self.advance(
                scope, phase, "entry_pending" if self.names else "skills_pending", proof
            )
        if phase == "entry_pending":
            proof = self.player.open_campaign_roster(
                scope + ":entry", self.journal, allow_experimental=True
            )
            if (
                proof.get("status") != "verified"
                or proof.get("selection_current") is not True
            ):
                raise CheckpointError("Operator roster entry was not verified")
            phase = self.advance(scope, phase, "actors_pending", proof)
        if phase == "actors_pending":
            proof = self.player.prepare_requested_campaign_actors(
                scope + ":actors",
                self.journal,
                names=self.names,
                allow_experimental=True,
            )
            if proof.get("status") != "prepared":
                raise CheckpointError("Requested actor preparation was not completed")
            phase = self.advance(scope, phase, "confirmation_pending", proof)
        if phase == "confirmation_pending":
            proof = self.player.confirm_campaign_roster(
                scope + ":confirm",
                self.journal,
                names=self.names,
                allow_experimental=True,
            )
            if (
                proof.get("status") != "verified"
                or proof.get("squad_verified") is not True
                or proof.get("formation_committed") is not True
            ):
                raise CheckpointError("Exact requested formation was not confirmed")
            phase = self.advance(scope, phase, "skills_pending", proof)
        if phase == "skills_pending":
            proof = self.player.prepare_required_campaign_skills(
                scope + ":skills", self.journal, allow_experimental=True
            )
            if proof.get("status") != "required_skills_prepared":
                raise CheckpointError("Route skill preparation was not completed")
            final = self.current_proof()
            phase = self.advance(
                scope, phase, "prepared", {"skills": proof, "final": final}
            )
            self.player.rt.log(
                "campaign_team_prepared",
                scope=scope,
                route=self.target["route"],
                tools_verified=False,
                energy_verified=False,
                expedition_started=False,
            )
            return {
                "status": "team_prepared",
                "verification": final,
                "tools_verified": False,
                "energy_verified": False,
                "rested_operators_verified": False,
                "expedition_started": False,
            }
        raise CheckpointError("Unknown team preparation phase; no operation submitted")


def run_team_cli(args, parser, runtime_factory):
    """Use the existing player entry point for bounded team preparation or offline review."""
    from maa_sand_config import load_profile
    from maa_sand_days import ActJournal
    from maa_sand_player import SandPlayer

    if any(
        (
            args.advance_day,
            args.camp_intro,
            args.base_npc,
            args.prepare_planter,
            args.upgrade_hq2,
            args.campaign_act,
            args.visit_liaison,
            args.raid_run_id is not None,
            args.campaign_state is not None,
            args.intro_run_id is not None,
        )
    ):
        parser.error(
            "--prepare-team cannot combine other campaign operations or battle takeover"
        )
    team_plan = getattr(args, "team_plan", None)
    if (
        sum(value is not None for value in (args.route, args.raid_profile, team_plan))
        != 1
    ):
        parser.error(
            "--prepare-team requires exactly one --route, --raid-profile, or --team-plan"
        )
    if (
        args.team_scope is not None
        and re.fullmatch(r"[A-Za-z0-9_.:-]{1,24}", args.team_scope) is None
    ):
        parser.error(
            "--team-scope must contain up to24 ASCII letters, numbers, dots, dashes, colons or underscores"
        )
    if args.team_run_id is not None and not args.team_run_id.strip():
        parser.error("--team-run-id must identify the campaign owning the journal")
    execute = args.execute and not args.check
    if execute and (
        not args.allow_experimental
        or args.journal is None
        or not args.team_scope
        or not args.team_run_id
    ):
        parser.error(
            "Team execution requires --allow-experimental, --journal, --team-scope and --team-run-id"
        )
    try:
        if team_plan is not None:
            profile = load_team_plan(team_plan, args.pack)
        elif args.raid_profile is not None:
            from maa_sand_raid import load_raid_profile

            profile = load_raid_profile(args.raid_profile, args.pack)
        else:
            profile = load_profile(args.pack, args.route)
        identities = resolve_squad(
            profile["required_squad"], args.runtime / "resource/battle_data.json"
        )
    except (CheckpointError, OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    summary = {
        "activity": "team-preparation",
        "route": profile["id"],
        "operators": identities["actors"],
        "required_skills": profile.get("required_formation_skills", {}),
        "required_ranks": profile.get("required_formation_ranks", {}),
        "required_levels": profile.get("required_formation_levels", {}),
        "required_elites": profile.get("required_formation_elites", {}),
        "formation_required": True,
        "launch_enabled": False,
        "tools_verified": False,
        "rested_operators_verified": False,
        "energy_verified": False,
        "game_connected": False,
    }
    if not execute:
        summary["status"] = "offline_team_preparation_checked"
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary
    output = args.output or data_path("sand-player", "team-preparation") / datetime.now(
        UTC
    ).strftime("%Y%m%dT%H%M%SZ")
    report = {
        **summary,
        "status": "started",
        "scope": args.team_scope,
        "journal": str(args.journal),
    }
    with runtime_factory(
        args.runtime,
        output,
        args.pack,
        capture_backend=getattr(args, "capture_backend", "adb"),
    ) as runtime:
        report["game_connected"] = True
        # Formation preparation needs no map anchors or live battle coordinate initialization.
        player = SandPlayer.__new__(SandPlayer)
        player.rt, player.profile = runtime, profile
        player.in_battle, player.raid_mode = False, False
        try:
            journal = ActJournal(args.journal, args.team_run_id)
            report["result"] = player.prepare_campaign_team(
                args.team_scope, journal, allow_experimental=True
            )
            if (
                not isinstance(report["result"], dict)
                or report["result"].get("status") != "team_prepared"
            ):
                raise CheckpointError("Team coordinator did not verify preparation")
            report["status"] = "team_prepared"
            runtime.log("team_preparation_result", **report["result"])
        except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 - save the checkpoint for every interrupted preparation
            report.update(status="checkpoint_stop", reason=str(error))
            runtime.log("team_preparation_stop", reason=str(error))
            try:
                path, _hits = CampaignNavigator(runtime, args.pack).frame(
                    "team-preparation-stop"
                )
                report["checkpoint_image"] = str(path)
            except Exception as checkpoint_error:  # noqa: BLE001 - retain original failure and pause uncertainty
                report["checkpoint_error"] = str(checkpoint_error)
        finally:
            (output / "team-preparation.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
            )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(output / "team-preparation.json"),
            },
            ensure_ascii=False,
        )
    )
    if report["status"] != "team_prepared":
        raise SystemExit(2)
    return report
