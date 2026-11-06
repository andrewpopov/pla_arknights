"""Offline-first native Sand menu scripts, backed by pinned saved screenshots.

--check and --replay never create a live NativeSession or connect to ADB.
Only --execute connects; it runs non-spending navigation and checks both ends.
"""

from maa_runtime import data_path

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from maa_sand_config import CheckpointError, default_pack


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bundle_digest(pack):
    files = sorted((Path(pack) / "resource/tasks").glob("*.json"))
    files += [Path(pack) / "flows/screenflows.json"]
    files += [
        Path(pack) / "resource/template" / name
        for name in ("SandTalesThemeTitle.png", "SandSquad3Selected.png")
    ]
    return hashlib.sha256(
        json.dumps(
            [(str(p.relative_to(pack)), digest(p)) for p in files],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def load_bundle(pack):
    pack = Path(pack)
    spec = json.loads((pack / "flows/screenflows.json").read_text("utf8"))
    tasks = json.loads((pack / "resource/tasks/SandFlow.json").read_text("utf8"))
    if spec.get("schema_version") != 1 or spec.get("kind") != "native-screenflows":
        raise CheckpointError("Unsupported screenflow manifest")
    banned = {
        "SandPilot@SquadStart",
        "SandPilot@HQConfirmUpgrade",
        "SandPilot@DayNext",
        "SandPilot@GatherStart",
    }
    for name, task in tasks.items():
        if not name.startswith("SandFlow@") or task.get("action", "DoNothing") not in (
            "DoNothing",
            "ClickSelf",
            "ClickRect",
            "Swipe",
        ):
            raise CheckpointError("Screenflow contains an unsupported action")
        for target in (
            task.get("next", []) + task.get("sub", []) + [task.get("baseTask", "")]
        ):
            if target in banned or (
                target.startswith("SandFlow@") and target not in tasks
            ):
                raise CheckpointError(
                    "Screenflow has a missing or spending task dependency"
                )
        if task.get("action") == "Swipe" and (
            task.get("specialParams") != [550, 0, 10, 10]
            or any(
                not isinstance(task.get(key), list)
                or len(task[key]) != 4
                or task[key][2:] != [1, 1]
                or not 0 <= task[key][0] < 1280
                or not 0 <= task[key][1] < 720
                for key in ("specificRect", "rectMove")
            )
        ):
            raise CheckpointError("Map pan must use the reviewed normalized gesture")
        if task.get("maxTimes") != 1:
            raise CheckpointError("Native screen steps must be bounded to one action")
    for flow in spec["flows"].values():
        if (
            flow.get("spends_act") is not False
            or flow.get("spends_materials") is not False
            or flow["task"] not in tasks
            or not flow.get("entry")
            or not flow.get("destination")
        ):
            raise CheckpointError(
                "Only explicit non-spending navigation flows are executable"
            )
    for case in spec["cases"]:
        path = Path(case["image"])
        if sys.platform.startswith("linux") and not path.is_file():
            windows_path = PureWindowsPath(case["image"])
            if (
                windows_path.is_absolute()
                and len(windows_path.drive) == 2
                and windows_path.drive[1] == ":"
            ):
                path = (
                    Path("/mnt")
                    / windows_path.drive[0].lower()
                    / Path(*windows_path.parts[1:])
                )
        if not path.is_file() or digest(path) != case["sha256"]:
            raise CheckpointError("Missing or changed screenshot: " + case["id"])
        if not case["positive"] and not case["negative"]:
            raise CheckpointError(
                "Every screenshot needs explicit recognition expectations"
            )
    return spec, tasks


def evaluate_cases(spec, reports):
    by_image = {}
    for report in reports:
        key = str(Path(report["image"]).resolve())
        if key in by_image or report.get("error"):
            raise CheckpointError("Duplicate or failed native image report")
        by_image[key] = report
    checks = []
    for case in spec["cases"]:
        report = by_image.get(str(Path(case["image"]).resolve()))
        if report is None:
            raise CheckpointError("Native replay omitted screenshot " + case["id"])
        hits = {row["task"]: row for row in report.get("results", [])}
        for expected, names in ((True, case["positive"]), (False, case["negative"])):
            for name in names:
                if name not in hits:
                    raise CheckpointError("Native replay omitted guard " + name)
                row = hits[name]
                hit = row.get("hit") is True and row.get("score", 0) >= 0.85
                checks.append(
                    {
                        "case": case["id"],
                        "task": name,
                        "expected": expected,
                        "hit": hit,
                        "score": row.get("score"),
                        "passed": hit == expected,
                    }
                )
    return {
        "all_passed": bool(checks) and all(c["passed"] for c in checks),
        "checks_passed": sum(c["passed"] for c in checks),
        "checks_total": len(checks),
        "checks": checks,
    }


def replay(pack, runtime, output, *, evaluator_factory=None):
    spec, _tasks = load_bundle(pack)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if evaluator_factory is None:
        sys.path.insert(
            0, str(Path(__file__).resolve().parents[1] / "upstream/MAA/tools")
        )
        from maa_core_eval import CoreEval

        evaluator_factory = CoreEval
    evaluator = evaluator_factory(
        dll_dir=Path(runtime),
        resource=Path(runtime),
        global_client="YoStarEN",
        user_dir=output / "core",
        overlays=[Path(pack)],
    )
    try:
        reports = evaluator.report([c["image"] for c in spec["cases"]], spec["guards"])
        images = {case["id"]: case["image"] for case in spec["cases"]}
        sequences = {}
        for name, flow in spec["flows"].items():
            frames = [images[key] for key in flow["replay_cases"]]
            steps = evaluator.replay(frames, [flow["task"]])
            passed = (
                len(steps) == len(frames)
                and all(step.get("hit") is True for step in steps)
                and steps[-1].get("next", []) in ([], ["Stop"])
            )
            sequences[name] = {
                "passed": passed,
                "expected_frames": len(frames),
                "steps": steps,
            }

    finally:
        evaluator.close()
    result = {
        **evaluate_cases(spec, reports),
        "schema_version": 1,
        "bundle_sha256": bundle_digest(Path(pack)),
        "native_core_sha256": digest(Path(runtime) / "MaaCore.dll"),
        "game_connected": False,
        "inputs_issued": False,
        "live_complete_flow_verified": False,
        "native_reports": reports,
    }
    result["sequence_replays"] = sequences
    result["flows_passed"] = sum(row["passed"] for row in sequences.values())
    result["flows_total"] = len(sequences)
    result["all_passed"] = (
        result["all_passed"] and result["flows_passed"] == result["flows_total"]
    )
    for name in ("version.json", "resource/version.json"):
        path = Path(runtime) / name
        if path.is_file():
            result.setdefault("runtime_versions", {})[name] = digest(path)
    (output / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf8"
    )
    return result


def verify_report(pack, runtime, report):
    if (
        report.get("all_passed") is not True
        or report.get("game_connected") is not False
        or report.get("inputs_issued") is not False
        or report.get("bundle_sha256") != bundle_digest(Path(pack))
        or report.get("native_core_sha256") != digest(Path(runtime) / "MaaCore.dll")
    ):
        raise CheckpointError(
            "Require a passing offline replay of this exact task pack and native build"
        )
    for name, expected in report.get("runtime_versions", {}).items():
        if digest(Path(runtime) / name) != expected:
            raise CheckpointError("Runtime resources changed; replay screenshots again")


def execute_flow(pack, runtime, output, name, report, *, runtime_factory=None):
    spec, _tasks = load_bundle(pack)
    if name not in spec["flows"]:
        raise CheckpointError("Unknown non-spending screenflow")
    verify_report(pack, runtime, report)
    if runtime_factory is None:
        from maa_sand_player import MaaRuntime

        runtime_factory = MaaRuntime
    from maa_sand_navigation import CampaignNavigator

    flow = spec["flows"][name]
    with runtime_factory(runtime, output, pack, capture_backend="adb") as native:
        navigator = CampaignNavigator(native, pack)
        path, hits = navigator.frame(
            "screenflow-entry", flow["entry"] + flow["destination"]
        )
        if not all(
            hits.get(task, {}).get("score", 0) >= 0.85 for task in flow["entry"]
        ):
            raise CheckpointError(
                "Current screen does not match the selected flow entry; no input sent"
            )
        native.task(flow["task"], timeout=90)
        path, hits = navigator.frame("screenflow-destination", flow["destination"])
        if not all(
            hits.get(task, {}).get("score", 0) >= 0.85 for task in flow["destination"]
        ):
            raise CheckpointError(
                "Native flow destination unconfirmed; do not repeat the action batch"
            )
        return {
            "status": "destination_verified",
            "flow": name,
            "image": str(path),
            "act_spent": False,
            "materials_spent": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--flow")
    parser.add_argument("--verified-report", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--replay", action="store_true")
    modes.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        spec, tasks = load_bundle(args.pack)
        if not args.replay and not args.execute:
            print(
                json.dumps(
                    {
                        "status": "offline_config_checked",
                        "flows": list(spec["flows"]),
                        "native_tasks": len(tasks),
                        "screenshots": len(spec["cases"]),
                        "game_connected": False,
                        "inputs_issued": False,
                    },
                    indent=2,
                )
            )
            return
        if args.runtime is None:
            raise CheckpointError(
                "--runtime is required for native replay or execution"
            )
        output = args.output or data_path("sand-player", "screenflows") / datetime.now(
            UTC
        ).strftime("%Y%m%dT%H%M%SZ")
        if args.replay:
            result = replay(args.pack, args.runtime, output)
            print(
                json.dumps(
                    {
                        k: result[k]
                        for k in [
                            "all_passed",
                            "checks_passed",
                            "checks_total",
                            "game_connected",
                            "inputs_issued",
                            "flows_passed",
                            "flows_total",
                        ]
                    }
                )
            )
            if not result["all_passed"]:
                raise SystemExit(2)
        else:
            if not args.flow or args.verified_report is None:
                raise CheckpointError("--execute requires --flow and --verified-report")
            report = json.loads(args.verified_report.read_text("utf8"))
            print(
                json.dumps(
                    execute_flow(args.pack, args.runtime, output, args.flow, report)
                )
            )
    except (CheckpointError, OSError, ValueError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
