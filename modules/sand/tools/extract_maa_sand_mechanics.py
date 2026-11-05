"""Extract reviewed tool mechanics from pinned game tables; no game connection."""

import argparse
import hashlib
import json
from pathlib import Path

from maa_sand_config import REVIEWED_FIELD_TOOLS, CheckpointError, default_pack
from maa_sand_tools import load_tool_catalog


def extract_tool_mechanics(manifest_path, pack=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    tables = {}
    provenance = {}
    for name in ("sandbox_perm_table.json", "character_table.json", "skill_table.json"):
        spec = manifest["files"][name]
        path = manifest_path.parent / name
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise CheckpointError("Pinned game table changed: " + name)
        tables[name] = json.loads(raw)
        provenance[name] = {"url": spec["url"], "sha256": spec["sha256"]}
    sandbox = tables["sandbox_perm_table.json"]
    mode = sandbox["detail"]["SANDBOX_V2"]["sandbox_1"]
    characters, skills = tables["character_table.json"], tables["skill_table.json"]
    catalog = load_tool_catalog(pack)
    items = {}
    for item_id, (name, trap_id) in REVIEWED_FIELD_TOOLS.items():
        binding = mode["itemTrapData"][item_id]
        item = sandbox["itemData"][item_id]
        character = characters[trap_id]
        if (
            binding["trapId"] != trap_id
            or binding["baseItemName"] != name
            or item["itemName"] != name
            or character["name"] != name
            or catalog[item_id]["name"] != name
            or catalog[item_id]["battle_identity"]["trap_id"] != trap_id
        ):
            raise CheckpointError("Tool identity changed across source tables")
        recipe = mode["craftItemData"][item_id]
        # Preserve recipe source independently; do not silently replace the reviewed local recipe.
        phase = character["phases"][binding["trapPhase"]]
        frames = [
            f
            for f in phase["attributesKeyFrames"]
            if f["level"] == binding["trapLevel"]
        ]
        if len(frames) != 1:
            raise CheckpointError("Tool needs an exact exported attribute keyframe")
        attrs = frames[0]["data"]
        skill_id = character["skills"][binding["skillIndex"]]["skillId"]
        skill = skills[skill_id]["levels"][binding["skillLevel"] - 1]
        board = {
            x["key"]: {"value": x["value"], "value_str": x["valueStr"]}
            for x in skill["blackboard"]
        }
        if len(board) != len(skill["blackboard"]):
            raise CheckpointError("Duplicate skill blackboard key")
        lifetime = board.get("live_duration", {}).get("value")
        if lifetime is not None and (
            type(lifetime) not in (int, float) or lifetime <= 0
        ):
            raise CheckpointError("Invalid exported tool lifetime")
        items[item_id] = {
            "name": name,
            "trap_id": trap_id,
            "phase": binding["trapPhase"],
            "level": binding["trapLevel"],
            "placement_description": character["description"],
            "position_enum": character["position"],
            "range_id": phase["rangeId"],
            "base_attributes": {
                k: attrs[k]
                for k in (
                    "cost",
                    "maxHp",
                    "def",
                    "magicResistance",
                    "blockCnt",
                    "respawnTime",
                    "spRecoveryPerSec",
                )
            },
            "skill": {
                "id": skill_id,
                "name": skill["name"],
                "description": skill["description"],
                "type": skill["skillType"],
                "sp": skill["spData"],
                "blackboard": board,
            },
            "excluded_from_raid_battles": trap_id
            in mode["basicConst"]["battleExcludedTrapsInRush"],
            "craft_source_record": recipe,
            "interpretation_limits": [
                "Base data does not verify the current client or active modifiers",
                "Lifetime and SP do not prove delivered resource yield",
                "Position NONE does not prove directionless placement",
            ],
        }
    return {
        "schema_version": 1,
        "kind": "reviewed exported tool mechanics; advisory only",
        "game_connected": False,
        "client_version_verified": False,
        "repository": manifest["repository"],
        "commit": manifest["commit"],
        "sources": provenance,
        "items": items,
        "capacity_constants": {
            k: mode["basicConst"][k] for k in ("toolboxCapacity", "toolCntLimitInSquad")
        },
        "runtime_placement_verified": False,
        "automatic_inventory_credit": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = extract_tool_mechanics(args.manifest, args.pack)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(
        json.dumps(
            {
                "items": len(result["items"]),
                "commit": result["commit"],
                "game_connected": False,
                "client_version_verified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
