"""Validate Debug task resources and optional Sand overlay without game input."""

import argparse
import json
import os
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime", "source", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(a.source / "src/Python"))
    from asst.asst import Asst

    passed = Asst.load(path=a.runtime.resolve(), user_dir=a.output.resolve())
    for layer in (
        a.source,
        a.source / "resource/global/YoStarEN",
        a.source / "modules/sand/pack",
    ):
        passed = passed and Asst._Asst__lib.AsstLoadResource(
            str(layer.resolve()).encode("utf-8")
        )
    report = {
        "success": bool(passed),
        "game_connected": False,
        "version": Asst._Asst__lib.AsstGetVersion().decode(),
    }
    (a.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)
    os._exit(0 if passed else 1)


if __name__ == "__main__":
    main()
