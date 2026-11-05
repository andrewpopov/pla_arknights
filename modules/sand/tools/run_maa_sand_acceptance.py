"""Bounded acceptance run of the installed Sand module, using its native controller."""

import argparse
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path


def energy_status(text):
    """Compatibility parser; use the same complete drink ratio as campaign visits."""
    from maa_sand_config import CheckpointError
    from maa_sand_visit import trip_energy

    try:
        energy = trip_energy({"text": text, "score": 1})
    except CheckpointError:
        return None
    return energy["cost"], energy["stock"]


def read_acceptance_energy(runtime, path):
    """Use the native badge and one shared magnification retry before any launch."""
    from maa_sand_config import CheckpointError
    from maa_sand_visit import read_trip_energy

    hits = runtime.matches(path, ["SandAuto@FormationTripEnergy"])
    energy = read_trip_energy(
        runtime, path, hits.get("SandAuto@FormationTripEnergy", {})
    )
    if energy["cost"] != 2 or not energy["funded"]:
        raise CheckpointError(
            f"Acceptance budget: need {energy['cost']} existing drinks; have {energy['stock']}; limit2"
        )
    return {
        "required": energy["cost"],
        "available": energy["stock"],
        "evidence": energy["evidence"],
    }


def run_test(module, output, execute=False, prepare=False, restore_energy=False):
    module, output = Path(module), Path(output)
    sys.path.insert(0, str(module / "tools"))
    from maa_sand_config import CheckpointError, load_profile, verify_anchors
    from maa_sand_player import MaaRuntime, SandPlayer
    from maa_sand_world import read_world, reconcile_world

    pack = module / "pack"
    anchors = Path(json.loads((pack / "anchors.json").read_text())["location"])
    profile = load_profile(pack)
    verify_anchors(pack, anchors)
    report = {
        "started": datetime.now(UTC).isoformat(),
        "module": str(module),
        "route": profile["id"],
        "mode": "one-expedition"
        if execute
        else ("prepare" if prepare else "inspection"),
        "limits": {
            "expeditions": 1,
            "ingredient_batches": 1 if restore_energy else 0,
            "energy_drinks": 2,
            "recovery_drinks": 2 if restore_energy else 0,
            "day_advances": 0,
            "campaign_resets": 0,
        },
        "status": "started",
        "checks": {},
    }

    class BudgetedPlayer(SandPlayer):
        def validate_squad(self, path):
            super().validate_squad(path)
            report["squad_image"] = str(path)
            report["energy"] = read_acceptance_energy(self.rt, path)
            report["checks"]["energy_budget_confirmed"] = True

        def prepare_energy(self):
            raise CheckpointError(
                "Acceptance budget: no brewing or ingredient spending"
            )

    with MaaRuntime(module / "runtime", output, pack) as runtime:
        player = BudgetedPlayer(runtime, anchors, profile)
        try:
            before, _, states = player.frame("acceptance-entry")
            report["before"] = str(before)
            report["entry_states"] = sorted(states)
            if "SandAuto@World" in states:
                try:
                    report["before_world"] = read_world(runtime, before)
                except CheckpointError as error:
                    report["world_observation_unavailable"] = str(error)
            if "SandAuto@RaidBattle" in states:
                report["raid_observation"] = states["SandAuto@RaidBattle"]
            if "SandAuto@Battle" in states:
                player.in_battle = True
                player.pause(True)
                report["checks"]["active_battle_paused"] = True
                raise CheckpointError(
                    "Existing battle preserved; acceptance does not resume unknown deployments"
                )
            report["entry_text"] = runtime.ocr(before, [0, 0, 1280, 720])
            report["checks"]["native_capture_and_ocr"] = True
            if prepare:
                player.prepare_squad()
                prepared, _, _ = player.frame("acceptance-squad")
                player.validate_squad(prepared)
                report["squad_image"] = str(prepared)
                report["squad_text"] = runtime.ocr(prepared, [0, 0, 1280, 720])
                report["status"] = "squad_prepared_without_start"
            elif execute:
                # User-authorized experimental validation, never enable autoplay.
                if restore_energy:
                    if runtime.matches(before, ["SandPilot@StartToday"]):
                        runtime.task("SandPilot@StartToday")
                        before, _, states = player.wait_for_state(
                            "SandAuto@World", "accepted-day-payout"
                        )
                        report["checks"]["pending_payout_collected"] = True
                        try:
                            report["before_world"] = read_world(runtime, before)
                            report["world_baseline"] = (
                                "after explicitly collected day payout"
                            )
                        except CheckpointError:
                            report.pop("before_world", None)
                    if not runtime.matches(before, ["SandAuto@EnergyScreen"]):
                        player.prepare_squad()
                    player.restore_energy(2)
                    report["checks"]["energy_recovered"] = True
                player.play()
                report["settlement"] = player.settlement
                report["world_return_image"] = player.world_return_image
                report["after_world"] = player.world_observation
                if report.get("before_world") and player.world_observation:
                    report["world_reconciliation"] = reconcile_world(
                        report["before_world"],
                        player.world_observation,
                        player.settlement["verified_counts"],
                    )
                wood = player.settlement["verified_counts"].get("wood")
                report["checks"]["settlement_wood_confirmed"] = wood is not None
                report["checks"]["settlement_wood_target_met"] = (
                    wood is not None and wood >= 8
                )
                report["banked_by_controller"] = player.policy.banked
                report["checks"]["route_completed"] = True
                report["checks"]["expected_carried_wood"] = player.policy.banked >= 8
                report["status"] = "needs_settlement_yield_review"
            else:
                report["status"] = "inspection_complete"
        except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 - always secure the final checkpoint
            report["status"] = "checkpoint_stop"
            report["reason"] = str(error)
            runtime.log("acceptance_stop", reason=str(error))
        finally:
            try:
                path, _, states = player.frame("stopped")
                if "SandAuto@Battle" in states:
                    player.in_battle = True
                    player.pause(True)
                    path, _, states = player.frame("stopped")
                    report["checks"]["final_battle_paused"] = (
                        "SandAuto@Paused" in states
                    )
                report["after"] = str(path)
                report["final_states"] = sorted(states)
            except Exception as error:  # noqa: BLE001 - retain any failure securing final state
                report["pause_error"] = str(error)
            report["finished"] = datetime.now(UTC).isoformat()
            (output / "acceptance.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
    print(
        json.dumps(
            {
                "status": report["status"],
                "reason": report.get("reason"),
                "report": str(output / "acceptance.json"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return report


def run_saved_formation(module, image, output, route, expected_drinks):
    """Replay the real campaign launch checks using a runtime with no input methods."""
    module, image, output = map(Path, (module, image, output))
    if output.drive.upper() == "C:":
        raise ValueError("Saved-frame images and logs must remain off C:")
    if type(expected_drinks) is not int or expected_drinks < 0:
        raise ValueError("Provide the independent expected drink stock")
    sys.path.insert(0, str(module / "tools"))
    from types import SimpleNamespace

    from maa_core_eval import CoreEval
    from maa_sand_config import REVIEWED_FIELD_TOOLS, load_profile
    from maa_sand_days import NativeDayBackend
    from maa_sand_equipment import ToolLoadoutVerifier
    from maa_sand_player import SandPlayer
    from replay_maa_sand_settlement import SavedFrameRuntime

    output.mkdir(parents=True, exist_ok=False)
    source_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    copied = output / image.name
    shutil.copy2(image, copied)
    pack = module / "pack"
    profile = load_profile(pack, route)
    tools = {}
    for step in profile["steps"]:
        if step["action"] == "deploy_tool":
            name = REVIEWED_FIELD_TOOLS[step["item_id"]][0]
            tools[name] = tools.get(name, 0) + 1
    report = {
        "mode": "saved-formation",
        "game_connected": False,
        "inputs_issued": False,
        "live_validation": False,
        "source_image": str(image),
        "source_sha256": source_hash,
        "image": str(copied),
        "route": profile["id"],
        "expected_drinks": expected_drinks,
        "required_tools": tools,
        "status": "started",
        "events": [],
        "native_core_sha256": hashlib.sha256(
            (module / "runtime/MaaCore.dll").read_bytes()
        ).hexdigest(),
    }
    evaluator = None
    try:
        evaluator = CoreEval(
            dll_dir=module / "runtime",
            resource=module / "runtime",
            global_client="YoStarEN",
            user_dir=output / "native",
            overlays=[pack],
        )
        runtime = SavedFrameRuntime(evaluator)
        runtime.pack = pack
        runtime.session = SimpleNamespace(install=module / "runtime")
        runtime.log = lambda event, **data: report["events"].append(
            {"event": event, **data}
        )
        player = SandPlayer.__new__(SandPlayer)
        player.rt, player.profile = runtime, profile
        backend = NativeDayBackend(
            player,
            allow_experimental=True,
            verify_equipment=ToolLoadoutVerifier(runtime) if tools else None,
        )
        state = {
            "squad": profile["required_squad"],
            "squad_size": len(profile["required_squad"]),
            "drinks": expected_drinks,
        }
        report["checks"] = backend.before_launch(
            copied, state, {"required_tools": tools}
        )
        report["status"] = "saved_formation_verified"
    except Exception as error:  # noqa: BLE001 - retain native replay failure evidence
        report.update(status="checkpoint_stop", reason=str(error))
    finally:
        if evaluator is not None:
            evaluator.close()
        (output / "acceptance.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf8"
        )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--execute", action="store_true")
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument(
        "--saved-formation",
        type=Path,
        help="Read-only native replay of campaign launch checks",
    )
    parser.add_argument("--route", help="Explicit route for saved-formation replay")
    parser.add_argument(
        "--expected-drinks",
        type=int,
        help="Independent expected stock for saved-formation replay",
    )
    parser.add_argument(
        "--restore-energy",
        action="store_true",
        help="Prepare up to two drinks only if the full requirement is affordable",
    )
    args = parser.parse_args()
    if args.restore_energy and not args.execute:
        parser.error("--restore-energy requires --execute")
    if args.saved_formation:
        if args.restore_energy or not args.route or args.expected_drinks is None:
            parser.error(
                "--saved-formation needs --route and --expected-drinks and cannot restore energy"
            )
        report = run_saved_formation(
            args.module,
            args.saved_formation,
            args.output,
            args.route,
            args.expected_drinks,
        )
    else:
        report = run_test(
            args.module, args.output, args.execute, args.prepare, args.restore_energy
        )
    return 2 if report["status"] == "checkpoint_stop" else 0


if __name__ == "__main__":
    raise SystemExit(main())
