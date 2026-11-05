"""Pinned full-level context for campaign planning; never a playable route."""

import argparse
import hashlib
import json
from pathlib import Path

from maa_sand_config import CheckpointError, default_pack


def game_position_to_tile(position, width, height):
    row, col = position.get("row"), position.get("col")
    if (
        type(row) is not int
        or type(col) is not int
        or not 0 <= row < height
        or not 0 <= col < width
    ):
        raise CheckpointError(
            "Game object position must be an in-grid integer row/column"
        )
    return [col, height - 1 - row]


def extract_levels(manifest_path, tile_directory, pack=None):
    manifest_path, tile_directory = Path(manifest_path), Path(tile_directory)
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    catalog = json.loads(
        ((Path(pack) if pack else default_pack()) / "campaign/stages.json").read_text(
            encoding="utf8"
        )
    )["stages"]
    overview = json.loads((tile_directory / "overview.json").read_text(encoding="utf8"))
    output = {}
    compared = 0
    for stage_id, spec in manifest["files"].items():
        if (
            stage_id not in catalog
            or spec["level_id"].casefold() != catalog[stage_id]["level_id"].casefold()
        ):
            raise CheckpointError("Full level does not bind a reviewed canonical stage")
        path = Path(spec["file"])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
            raise CheckpointError("Pinned full level changed: " + stage_id)
        source = json.loads(raw)
        entries = [v for v in overview.values() if v.get("stageId") == stage_id]
        if len(entries) != 1:
            raise CheckpointError("Canonical compact tile map is missing or ambiguous")
        compact_path = (tile_directory / entries[0]["filename"]).resolve()
        if not compact_path.is_relative_to(tile_directory.resolve()):
            raise CheckpointError("Compact tile map path escapes its directory")
        compact_raw = compact_path.read_bytes()
        compact = json.loads(compact_raw)
        if compact["levelId"].casefold() != spec["level_id"].casefold():
            raise CheckpointError("Full and compact levels have different identities")
        width, height = compact["width"], compact["height"]
        grid, tiles = source["mapData"]["map"], source["mapData"]["tiles"]
        if len(grid) != height or any(len(line) != width for line in grid):
            raise CheckpointError("Full and compact level dimensions differ")
        heights = {"LOWLAND": 0, "HIGHLAND": 1}
        buildable = {"NONE": 0, "MELEE": 1, "RANGED": 2, "ALL": 3}
        for row, line in enumerate(grid):
            for col, index in enumerate(line):
                if type(index) is not int or not 0 <= index < len(tiles):
                    raise CheckpointError("Invalid full-map tile index")
                actual, expected = tiles[index], compact["tiles"][row][col]
                if (
                    actual["tileKey"] != expected["tileKey"]
                    or heights.get(actual["heightType"]) != expected["heightType"]
                    or buildable.get(actual["buildableType"])
                    != expected["buildableType"]
                ):
                    raise CheckpointError("Full level terrain differs from MAA tiles")
                compared += 1
        objects = []
        for obj in source["predefines"]["tokenInsts"]:
            objects.append(
                {
                    "alias": obj["alias"],
                    "trap_id": obj["inst"]["characterKey"],
                    "tile": game_position_to_tile(obj["position"], width, height),
                    "game_position": obj["position"],
                    "direction": obj["direction"],
                    "initially_hidden": obj["hidden"],
                    "activation_verified": False,
                    "override_skill_blackboard": obj["overrideSkillBlackboard"],
                }
            )

        def routes(key, source, width, height):
            result = []
            for route in source[key]:
                result.append(
                    {
                        **route,
                        "maa_start_tile": game_position_to_tile(
                            route["startPosition"], width, height
                        ),
                        "maa_end_tile": game_position_to_tile(
                            route["endPosition"], width, height
                        ),
                        "maa_checkpoint_tiles": [
                            game_position_to_tile(c["position"], width, height)
                            for c in (route["checkpoints"] or [])
                        ],
                    }
                )
            return result

        output[stage_id] = {
            "level_id": spec["level_id"],
            "english_stage": catalog[stage_id]["english"],
            "width": width,
            "height": height,
            "source": {"url": spec["url"], "sha256": spec["sha256"]},
            "compact_tile_sha256": hashlib.sha256(compact_raw).hexdigest(),
            "predefined_candidates": objects,
            "routes": routes("routes", source, width, height),
            "extra_routes": routes("extraRoutes", source, width, height),
            "waves": source["waves"],
            "branches": source["branches"],
            "active_branch": None,
            "live_objects_verified": False,
            "execution_allowed": False,
            "route_binding_note": "Preserve main and extra route sets separately; branch route-index binding is not live-verified.",
        }
    if set(output) != set(catalog):
        raise CheckpointError(
            "Full level extraction requires all reviewed campaign stages"
        )
    return {
        "schema_version": 1,
        "kind": "full level reference; not a Sand execution route",
        "commit": manifest["commit"],
        "game_connected": False,
        "client_version_verified": False,
        "terrain_cells_compared": compared,
        "coordinate_rule": "MAA[col,row]=[game.col,height-1-game.row]",
        "randomized_candidates_are_not_current_resources": True,
        "relative_delays_are_not_absolute_spawn_times": True,
        "stages": output,
    }


def level_advice(stage_id, pack=None):
    path = (Path(pack) if pack else default_pack()) / "campaign/level-rules.json"
    if not path.is_file():
        return {
            "status": "full_level_reference_unavailable",
            "execution_allowed": False,
        }
    data = json.loads(path.read_text(encoding="utf8"))
    if (
        data.get("schema_version") != 1
        or data.get("client_version_verified") is not False
    ):
        raise CheckpointError("Full level context must remain an unverified reference")
    stage = data["stages"].get(stage_id)
    if (
        stage is None
        or stage.get("execution_allowed") is not False
        or stage.get("live_objects_verified") is not False
    ):
        raise CheckpointError(
            "Full level context lacks the exact unverified stage binding"
        )
    return {
        "status": "static_full_level_reference",
        "stage_id": stage_id,
        "source_commit": data["commit"],
        "predefined_candidates": stage["predefined_candidates"],
        "branch_names": list(stage["branches"]),
        "active_branch": None,
        "route_alternatives": {
            "main": len(stage["routes"]),
            "extra": len(stage["extra_routes"]),
        },
        "live_resources_verified": False,
        "absolute_spawn_times_verified": False,
        "execution_allowed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--tiles", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = extract_levels(args.manifest, args.tiles, args.pack)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(
        json.dumps(
            {
                "stages": len(data["stages"]),
                "terrain_cells_compared": data["terrain_cells_compared"],
                "game_connected": False,
                "execution_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
