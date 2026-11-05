"""Export campaign tile projections through MAA's native TilePack, without a device."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from maa_sand_config import CheckpointError, default_pack


def project_campaign(evaluator, stages, pack=None):
    pack = Path(pack) if pack else default_pack()
    catalog = json.loads((pack / "campaign/stages.json").read_text(encoding="utf8"))[
        "stages"
    ]
    if (
        not isinstance(stages, list)
        or not stages
        or any(not isinstance(s, str) for s in stages)
        or len(stages) != len(set(stages))
        or any(stage not in catalog for stage in stages)
    ):
        raise CheckpointError(
            "Request unique canonical IDs from the reviewed campaign catalog"
        )
    rows = evaluator.tile_projection(stages)
    if len(rows) != len(stages) or {r.get("stage_id") for r in rows} != set(stages):
        raise CheckpointError(
            "Native tile projection did not return every requested stage"
        )
    for row in rows:
        if row.get("error") or row.get("mode") != "tile_projection":
            raise CheckpointError("Native tile projection failed")
        stage = catalog[row["stage_id"]]
        if row.get("level_id", "").casefold() != stage["level_id"].casefold():
            raise CheckpointError(
                "Native tile data does not match the exported campaign level ID"
            )
        width, height = row.get("width"), row.get("height")
        tiles = row.get("tiles", [])
        if (
            type(width) is not int
            or type(height) is not int
            or min(width, height) < 1
            or len(tiles) != width * height
            or row.get("camera_shift") != [0, 0]
            or row.get("live_camera_verified") is not False
        ):
            raise CheckpointError("Incomplete or unbound native projection metadata")
        positions = set()
        for tile in tiles:
            loc = tile.get("tile")
            if (
                not isinstance(loc, list)
                or len(loc) != 2
                or any(type(v) is not int for v in loc)
                or not (0 <= loc[0] < width and 0 <= loc[1] < height)
                or tuple(loc) in positions
            ):
                raise CheckpointError("Duplicate or invalid native map tile")
            positions.add(tuple(loc))
            poses = ["normal", "selected"]
            if row.get("floor_plane_available"):
                if row.get("floor_plane_live_verified") is not False:
                    raise CheckpointError(
                        "Diagnostic floor plane must not claim live terrain verification"
                    )
                poses.extend(["floor_normal", "floor_selected"])
            for pose in poses:
                point = tile.get(pose)
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(type(v) is not int for v in point)
                ):
                    raise CheckpointError("Missing native camera projection")
            if not isinstance(tile.get("tile_key"), str) or any(
                type(tile.get(k)) is not int for k in ("height_type", "buildable_type")
            ):
                raise CheckpointError("Native terrain identity is missing")
        row["english_stage"] = stage["english"]
    return rows


def rank_waypoint_tiles(projection, point, *, pose="normal", surface="initial"):
    """Rank diagnostic geometry hypotheses; never authorize placement or terrain changes."""
    if (
        pose not in ("normal", "selected")
        or surface not in ("initial", "floor")
        or not isinstance(point, (list, tuple))
        or len(point) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)
        or not (0 <= point[0] < 1280 and 0 <= point[1] < 720)
    ):
        raise CheckpointError(
            "Waypoint must specify a finite normalized point, camera pose and surface model"
        )
    if surface == "floor" and (
        projection.get("floor_plane_available") is not True
        or projection.get("floor_plane_live_verified") is not False
    ):
        raise CheckpointError(
            "Native diagnostic floor-plane projections are unavailable or unbound"
        )
    field = ("floor_" if surface == "floor" else "") + pose
    candidates = []
    for tile in projection["tiles"]:
        target = tile.get(field)
        if (
            not isinstance(target, list)
            or len(target) != 2
            or any(type(v) is not int for v in target)
        ):
            raise CheckpointError(
                "Native waypoint candidate has no exact projected point"
            )
        candidates.append(
            {
                "tile": tile["tile"],
                "projected": target,
                "distance": math.dist(point, target),
                "tile_key": tile["tile_key"],
                "initial_buildable_type": tile["buildable_type"],
                "initial_height_type": tile["height_type"],
            }
        )
    candidates.sort(key=lambda item: item["distance"])
    return {
        "stage_id": projection["stage_id"],
        "point": list(point),
        "pose": pose,
        "surface_model": surface,
        "candidates": candidates[:3],
        "execution_allowed": False,
        "live_terrain_verified": False,
    }


def pin_tile_resources(runtime, stages):
    resource = Path(runtime) / "resource"
    if (
        resource / "global/YoStarEN/resource/Arknights-Tile-Pos/overview.json"
    ).exists():
        raise CheckpointError(
            "Layered tile resource overrides require explicit provenance"
        )
    directory = (resource / "Arknights-Tile-Pos").resolve()
    overview = directory / "overview.json"
    index = json.loads(overview.read_text(encoding="utf8"))
    pins = {
        "overview_sha256": hashlib.sha256(overview.read_bytes()).hexdigest(),
        "stages": {},
    }
    for stage in stages:
        candidates = [v for v in index.values() if v.get("stageId") == stage]
        if len(candidates) != 1 or not isinstance(candidates[0].get("filename"), str):
            raise CheckpointError("Exact tile data provenance is missing or ambiguous")
        source = (directory / candidates[0]["filename"]).resolve()
        if not source.is_relative_to(directory):
            raise CheckpointError("Tile data path escapes its resource directory")
        pins["stages"][stage] = {
            "file": source.name,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    return pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--stage", action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upstream/MAA/tools"))
    from maa_core_eval import CoreEval

    catalog = json.loads(
        (args.pack / "campaign/stages.json").read_text(encoding="utf8")
    )["stages"]
    stages = args.stage or list(catalog)
    pins = pin_tile_resources(args.runtime, stages)
    evaluator = CoreEval(
        dll_dir=args.runtime,
        resource=args.runtime,
        global_client="YoStarEN",
        user_dir=args.output,
    )
    try:
        rows = project_campaign(evaluator, stages, args.pack)
        if pin_tile_resources(args.runtime, stages) != pins:
            raise CheckpointError(
                "Tile resource inputs changed during native projection"
            )
        report = {
            "kind": "native nominal tile projection; not live camera calibration",
            "game_connected": False,
            "runtime": str(args.runtime),
            "tile_resources": pins,
            "core_sha256": hashlib.sha256(
                (args.runtime / "MaaCore.dll").read_bytes()
            ).hexdigest(),
            "stages": rows,
        }
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
        print(
            json.dumps(
                {
                    "stages": [
                        {"stage_id": r["stage_id"], "tiles": len(r["tiles"])}
                        for r in rows
                    ],
                    "game_connected": False,
                }
            ),
            flush=True,
        )
    finally:
        evaluator.close()


if __name__ == "__main__":
    main()
