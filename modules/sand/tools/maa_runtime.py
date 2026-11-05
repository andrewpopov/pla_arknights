"""Resolve the active player installation shared by the local MAA tools."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def default_maa_path():
    pointer = ROOT / "reviews/maa-active-install.json"
    if pointer.is_file():
        install = json.loads(pointer.read_text(encoding="utf-8"))["install"]
        if not isinstance(install, str) or not install:
            raise ValueError("Active MAA install must be a nonempty path")
        return Path(install)
    return Path(r"C:\Users\andre\MAA")
