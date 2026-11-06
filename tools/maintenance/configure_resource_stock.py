"""Configure native MAA Depot maintenance before natural-sanity LMD farming."""

import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

TASK_NAME = "Promotion materials: keep 10 each"


def build_policy(install, matrix_path, stage_status_path, target=10):
    resource = Path(install) / "resource"
    items = json.loads(
        (resource / "global/YoStarEN/resource/item_index.json").read_text(
            encoding="utf8"
        )
    )
    stages = json.loads((resource / "stages.json").read_text(encoding="utf8"))
    stats = json.loads(Path(matrix_path).read_text(encoding="utf8"))["matrix"]
    availability = {
        s["stageId"]: s
        for s in json.loads(Path(stage_status_path).read_text(encoding="utf8"))
    }
    plans, excluded = [], []
    for item_id, item in sorted(items.items()):
        if (
            not re.fullmatch(r"(?:300|301|310|311)\d3", item_id)
            or item.get("classifyType") != "MATERIAL"
        ):
            continue
        candidates = {
            s["stageId"]: s
            for s in stages
            if s["stageId"].startswith(("main_", "sub_"))
            and any(
                d["itemId"] == item_id and d["dropType"] == "NORMAL_DROP"
                for d in s["dropInfos"]
            )
            and availability.get(s["stageId"], {})
            .get("existence", {})
            .get("US", {})
            .get("exist")
            is True
        }
        if not candidates:
            excluded.append(
                {
                    "item_id": item_id,
                    "name": item["name"],
                    "reason": "No US permanent farming stage in source data",
                }
            )
            continue
        ranked = []
        for row in stats:
            if (
                row["itemId"] == item_id
                and row["stageId"] in candidates
                and row.get("end") is None
                and row["times"] >= 1000
                and row["quantity"] > 0
            ):
                stage = candidates[row["stageId"]]
                ranked.append(
                    (
                        stage["apCost"] * row["times"] / row["quantity"],
                        stage["code"],
                        row["times"],
                    )
                )
        if not ranked:
            raise ValueError(
                "No sufficiently sampled current US drop statistics for " + item["name"]
            )
        expected, code, samples = min(ranked)
        plans.append(
            {
                "item_id": item_id,
                "name": item["name"],
                "stage": code,
                "target": target,
                "expected_sanity_per_target": round(expected, 3),
                "samples": samples,
                "auto_deploy_verified": False,
            }
        )
    if not plans or type(target) is not int or target <= 0:
        raise ValueError(
            "A positive stock target and farmable material list are required"
        )
    return {
        "schema_version": 1,
        "server": "US",
        "scope": "Tier 3 promotion materials",
        "target": target,
        "plans": plans,
        "excluded": excluded,
        "stage_selection": "Lowest observed direct-target sanity cost, current US samples >=1000; secondary-drop value not ranked",
        "fallback": ["CE-6", "LS-6"],
        "use_medicine": False,
        "use_premium_currency": False,
        "statistics_sha256": hashlib.sha256(Path(matrix_path).read_bytes()).hexdigest(),
        "availability_sha256": hashlib.sha256(
            Path(stage_status_path).read_bytes()
        ).hexdigest(),
    }


def configure(config, policy):
    updated = copy.deepcopy(config)
    name = updated["Current"]
    queue = updated["Configurations"][name]["TaskQueue"]
    fight = next(t for t in queue if t.get("$type") == "FightTask")
    queue[:] = [
        t
        for t in queue
        if not (t.get("$type") == "DepotMaintainTask" and t.get("Name") == TASK_NAME)
    ]
    stock = {
        "$type": "DepotMaintainTask",
        "TaskType": "DepotMaintain",
        "Name": TASK_NAME,
        "IsEnable": True,
        "UpdateDepot": True,
        "IsStageManually": True,
        "SkipDuringActivity": False,
        "SkipDuringResourceCollection": False,
        "OnlyFirstInsufficientPlan": False,
        "SortByProgress": True,
        "CountDualChipAsChipPack": False,
        "UseAutoSeries": False,
        "UseMedicine": False,
        "UseStone": False,
        "UseExpiringMedicine": False,
        "PlanList": [
            {
                "Stage": p["stage"],
                "DropId": p["item_id"],
                "DropCount": p["target"],
                "UseMedicine": False,
                "MedicineCount": 0,
                "UseStone": False,
                "StoneCount": 0,
            }
            for p in policy["plans"]
        ],
    }
    queue.insert(queue.index(fight), stock)
    fight.update(
        IsEnable=True,
        StagePlan=policy["fallback"],
        UseOptionalStage=True,
        UseMedicine=False,
        MedicineCount=0,
        UseStone=False,
        StoneCount=0,
        UseExpiringMedicine=False,
        UseExpireMedicineForActivity=False,
        EnableTargetDrop=False,
        IsInventoryTarget=False,
        EnableTimesLimit=False,
    )
    for task in queue:
        if task.get("$type") in ("RoguelikeTask", "ReclamationTask"):
            task["IsEnable"] = False
    return updated, name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--stage-status", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=int, default=10)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    policy = build_policy(args.install, args.matrix, args.stage_status, args.target)
    config_path = args.install / "config/gui.new.json"
    original = config_path.read_bytes()
    config = json.loads(original.decode("utf-8-sig"))
    updated, profile = configure(config, policy)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "resource-stock-policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    report = {
        "profile": profile,
        "materials": len(policy["plans"]),
        "target": args.target,
        "fallback": policy["fallback"],
        "applied": False,
        "game_connected": False,
        "configuration_before_sha256": hashlib.sha256(original).hexdigest(),
        "policy_file": str(args.output / "resource-stock-policy.json"),
    }
    if args.apply:
        probe = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "if (Get-Process -Name MAA -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }",
            ],
            check=False,
        )
        if probe.returncode:
            raise RuntimeError(
                "MAA must be fully closed before saving its configuration"
            )
        gui = (args.install / "MAA.dll").read_bytes()
        if any(name not in gui for name in (b"DepotMaintainTask", b"SortByProgress")):
            raise RuntimeError(
                "Installed GUI does not support native stock maintenance"
            )
        if config_path.read_bytes() != original:
            raise RuntimeError(
                "Configuration changed during preparation; preserve it and re-evaluate"
            )
        backup = args.output / (
            "gui.before-resource-stock-"
            + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + ".json"
        )
        shutil.copy2(config_path, backup)
        temp = config_path.with_name(config_path.name + ".resource-stock.tmp")
        temp.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
        temp.replace(config_path)
        saved = json.loads(config_path.read_text(encoding="utf8"))
        assert saved == updated
        saved_queue = saved["Configurations"][profile]["TaskQueue"]
        stock_index = next(
            i for i, t in enumerate(saved_queue) if t.get("Name") == TASK_NAME
        )
        fight_index = next(
            i for i, t in enumerate(saved_queue) if t.get("$type") == "FightTask"
        )
        assert stock_index < fight_index
        for other in config["Configurations"]:
            if other != profile:
                assert saved["Configurations"][other] == config["Configurations"][other]
        report.update(
            applied=True,
            backup=str(backup),
            configuration_after_sha256=hashlib.sha256(
                config_path.read_bytes()
            ).hexdigest(),
        )
    (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
