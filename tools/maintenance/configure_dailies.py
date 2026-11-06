"""Prepare a named daily profile by cloning this machine's existing MAA settings.

Preview is the default. Fully exit MAA before --apply. Personal connection,
base and recruit settings stay local; the shared preset contains no account data.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

PRESET = Path(__file__).resolve().parents[2] / "modules/configurations/dailies.json"


def configure(config, preset, source=None, name=None):
    source = source or config["Current"]
    name = name or preset["name"]
    if source == name:
        source_profile = config["Configurations"][source]
    else:
        source_profile = config["Configurations"][source]
        if name in config["Configurations"]:
            raise ValueError(
                "Profile already exists; choose a new --name or explicitly use it as --source"
            )
    profile = copy.deepcopy(source_profile)
    queue = profile["TaskQueue"]
    kinds = {task.get("$type") for task in queue}
    missing = set(preset["enabled_task_types"]) - kinds
    if missing:
        raise ValueError(
            "Source profile lacks required tasks: " + ", ".join(sorted(missing))
        )
    enabled = set(preset["enabled_task_types"])
    optional = set(preset.get("optional_configured_task_types", []))
    for task in queue:
        kind = task.get("$type")
        task["IsEnable"] = kind in enabled or (
            kind in optional and bool(task.get("PlanList"))
        )
        if kind == "FightTask":
            task.update(copy.deepcopy(preset["combat"]))
        if kind == "DepotMaintainTask":
            for flag in ("UseMedicine", "UseStone", "UseExpiringMedicine"):
                task[flag] = False
            for plan in task.get("PlanList", []):
                plan.update(
                    UseMedicine=False, MedicineCount=0, UseStone=False, StoneCount=0
                )
    # Keep native queue ordering and all user-specific settings except auto-run.
    profile.setdefault("Gui", {}).setdefault("StartUpSettings", {})["RunDirectly"] = (
        False
    )
    result = copy.deepcopy(config)
    result["Configurations"][name] = profile
    result["Current"] = name
    return result, name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--preset", type=Path, default=PRESET)
    parser.add_argument("--source")
    parser.add_argument("--name")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config_path = args.install / "config/gui.new.json"
    original = config_path.read_bytes()
    config = json.loads(original.decode("utf-8-sig"))
    preset = json.loads(args.preset.read_text(encoding="utf-8"))
    updated, name = configure(config, preset, args.source, args.name)
    report = {
        "profile": name,
        "source": args.source or config["Current"],
        "enabled_tasks": [
            t["$type"]
            for t in updated["Configurations"][name]["TaskQueue"]
            if t.get("IsEnable")
        ],
        "combat_stages": preset["combat"]["StagePlan"],
        "natural_sanity_only": True,
        "applied": False,
        "game_connected": False,
    }
    if args.apply:
        if os.name != "nt":
            raise RuntimeError("Apply on Windows, with MAA fully closed")
        probe = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "if(Get-Process MAA -ErrorAction SilentlyContinue){exit 1}else{exit 0}",
            ],
            check=False,
        )
        if probe.returncode:
            raise RuntimeError("Fully exit MAA through its tray menu before applying")
        if config_path.read_bytes() != original:
            raise RuntimeError("Configuration changed during preparation")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = config_path.with_name("gui.before-dailies-" + stamp + ".json")
        with backup.open("xb") as stream:
            stream.write(original)
        temp = config_path.with_name("gui.dailies.tmp")
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(updated, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temp.replace(config_path)
        report.update(
            applied=True,
            backup=str(backup),
            before_sha256=hashlib.sha256(original).hexdigest(),
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
