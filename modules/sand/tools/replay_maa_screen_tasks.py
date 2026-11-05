"""Replay native task recognition against saved images without connecting to the game."""

import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--image", action="append", required=True)
    p.add_argument("--task", action="append", default=[])
    p.add_argument("--overlay", type=Path, action="append", default=[])
    p.add_argument(
        "--mode", choices=["report", "ocr", "battle_deployment"], default="report"
    )
    p.add_argument("--roi", nargs=4, type=int)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "upstream/MAA/tools"))
    from maa_core_eval import CoreEval

    evaluator = CoreEval(
        dll_dir=a.runtime,
        resource=a.runtime,
        global_client="YoStarEN",
        user_dir=a.output,
        overlays=a.overlay,
    )
    try:
        if a.mode == "report":
            assert a.task, "Report mode requires task names"
            results = evaluator.report(a.image, a.task)
        elif a.mode == "battle_deployment":
            results = evaluator.battle_deployment(a.image)
        else:
            results = evaluator.ocr(a.image, roi=a.roi)
        if not results or any(item.get("error") for item in results):
            raise RuntimeError("Native saved-image replay failed")
        (a.output / "report.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(results, ensure_ascii=False), flush=True)
    finally:
        evaluator.close()


if __name__ == "__main__":
    main()
