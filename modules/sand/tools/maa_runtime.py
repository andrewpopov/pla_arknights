"""Portable runtime and diagnostics locations for the optional Sand tools."""

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def default_maa_path():
    if os.environ.get("MAA_RUNTIME"):
        return Path(os.environ["MAA_RUNTIME"])
    installed = ROOT.parent.parent
    if (installed / "MAA.exe").is_file():
        return installed
    pointer = ROOT / "reviews/maa-active-install.json"
    if pointer.is_file():
        return Path(json.loads(pointer.read_text(encoding="utf-8"))["install"])
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "pla_arknights"


def data_path(*parts):
    location = os.environ.get("MAA_DATA_DIR")
    if not location:
        location = str(
            Path(os.environ.get("LOCALAPPDATA", Path.home())) / "pla_arknights-data"
        )
    return Path(location).joinpath(*parts)


def adb_path():
    value = os.environ.get("MAA_ADB") or shutil.which("adb")
    if not value:
        raise RuntimeError("Set MAA_ADB to your emulator's adb.exe or put adb on PATH")
    return value
