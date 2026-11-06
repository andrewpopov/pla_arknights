"""Replay the actual settlement reader through MaaCore against saved images only."""

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

from maa_sand_config import CheckpointError, default_pack
from maa_sand_settlement import read_rewards


class SavedFrameRuntime:
    def __init__(self, evaluator):
        self.evaluator = evaluator

    @staticmethod
    def results(reports):
        if len(reports) != 1 or reports[0].get("error"):
            raise CheckpointError(
                "Saved-frame analysis needs exactly one successful native result"
            )
        return reports[0].get("results", [])

    def analyze(self, path, mode="templ", **params):
        """Expose existing saved-image recognition only, never controller APIs."""
        if mode == "formation_operators":
            reports = self.evaluator.formation_operators([str(path)], **params)
            self.results(reports)
            return reports[0]
        if mode != "templ":
            raise CheckpointError(
                "Saved-frame generic analysis only supports read-only template and formation replay"
            )
        templates = params.pop("templates")
        reports = self.evaluator.templ([str(path)], templates, **params)
        self.results(reports)
        return reports[0]

    def matches(self, path, tasks):
        return {
            row["task"]: row
            for row in self.results(self.evaluator.report([str(path)], tasks))
            if row.get("hit")
        }

    def ocr(self, path, roi):
        return self.results(self.evaluator.ocr([str(path)], roi=list(roi)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", type=Path, action="append", required=True)
    parser.add_argument("--stage", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if importlib.util.find_spec("maa_core_eval") is None:
        sys.path.insert(
            0, str(Path(__file__).resolve().parents[1] / "upstream/MAA/tools")
        )
    from maa_core_eval import CoreEval

    evaluator = CoreEval(
        dll_dir=args.runtime,
        resource=args.runtime,
        global_client="YoStarEN",
        user_dir=args.output / "native",
        overlays=[args.pack],
    )
    outcomes = []
    try:
        runtime = SavedFrameRuntime(evaluator)
        for index, source in enumerate(args.image):
            # Magnified retries are written beside the copy, never into the input evidence folder.
            target = args.output / f"{index:02d}-{source.name}"
            shutil.copy2(source, target)
            record = {
                "source": str(source),
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
            try:
                record.update(result=read_rewards(runtime, target, args.stage))
            except CheckpointError as exc:
                record["error"] = str(exc)
            outcomes.append(record)
        report = {
            "game_connected": False,
            "inventory_updated": False,
            "results": outcomes,
        }
        (args.output / "report.json").write_text(
            json.dumps(report, indent=2) + chr(10), encoding="utf8"
        )
    finally:
        evaluator.close()
    if any("error" in result for result in outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
