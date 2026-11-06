"""Shared native MAA runtime setup and exclusive emulator ownership."""

import hashlib
import csv
import io
import os
import shutil
import subprocess
import sys

from maa_runtime import adb_path, data_path
from contextlib import AbstractContextManager
from pathlib import Path


class ControllerLease(AbstractContextManager):
    """OS-held byte lock: shared by our tools and released automatically on process exit."""

    def __init__(self, address, directory=None):
        self.directory = (
            Path(directory) if directory is not None else data_path("controller-locks")
        )
        self.path = self.directory / (
            hashlib.sha256(address.encode()).hexdigest()[:20] + ".lock"
        )
        self.stream = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError("Another native controller owns this emulator") from exc
        self.stream = stream
        return self

    def __exit__(self, *_):
        if self.stream:
            self.stream.close()
            self.stream = None


def resource_layers(install, client="YoStarEN", overlays=()):
    install = Path(install)
    candidates = [
        install / "resource/global" / client,
        install / "cache",
        install / "cache/resource/global" / client,
        *overlays,
    ]
    seen = set()
    layers = []
    for layer in candidates:
        layer = Path(layer)
        resolved = layer.resolve()
        if (layer / "resource").is_dir() and resolved not in seen:
            layers.append(layer)
            seen.add(resolved)
    return layers


def load_runtime(install, output, client="YoStarEN", overlays=()):
    install, output = Path(install), Path(output)
    if not (install / "resource/global" / client / "resource").is_dir():
        raise RuntimeError(f"Missing client resource layer: {client}")
    sys.path.insert(0, str(install / "Python"))
    from asst.asst import Asst

    cache = install / "cache/avatars"
    if cache.is_dir() and not (output / "cache/avatars").exists():
        shutil.copytree(cache, output / "cache/avatars")
    if not Asst.load(path=install, user_dir=output):
        raise RuntimeError("MAA resource loading failed")
    for layer in resource_layers(install, client, overlays):
        if not Asst._Asst__lib.AsstLoadResource(str(layer).encode("utf-8")):
            raise RuntimeError(f"Resource layer failed: {layer}")
    return Asst


def _require_windows_gui_stopped():
    result = subprocess.run(
        ["tasklist.exe", "/FI", "IMAGENAME eq MAA.exe", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    output = result.stdout.strip()
    if output == "INFO: No tasks are running which match the specified criteria.":
        return
    rows = list(csv.reader(io.StringIO(output)))
    if rows and all(len(row) >= 2 and row[1].strip().isdigit() for row in rows):
        if any(row[0].casefold() == "maa.exe" for row in rows):
            raise RuntimeError(
                "MAA GUI is running; stop it before claiming emulator control"
            )
    raise RuntimeError(
        "MAA process query returned unrecognized output; no emulator control"
    )


def require_gui_stopped():
    if os.name == "nt":
        _require_windows_gui_stopped()


class NativeSession(AbstractContextManager):
    def __init__(
        self,
        install,
        output,
        callback,
        address="127.0.0.1:16384",
        overlays=(),
        deployment_with_pause=True,
        touch_mode="minitouch",
    ):
        if touch_mode not in {"adb", "minitouch", "maatouch"}:
            raise ValueError("Unsupported native touch mode")
        self.touch_mode = touch_mode
        self.install, self.output = Path(install), Path(output)
        self.callback, self.address = callback, os.environ.get("MAA_ADDRESS", address)
        self.overlays, self.deployment_with_pause = overlays, deployment_with_pause
        self.lease = ControllerLease(self.address)
        self.bot = None

    def __enter__(self):
        self.lease.__enter__()
        try:
            require_gui_stopped()
            Asst = load_runtime(self.install, self.output, overlays=self.overlays)
            from asst.utils import InstanceOptionType

            connection = os.environ.get("MAA_CONNECTION_CONFIG", "General")
            emulator = os.environ.get("MAA_EMULATOR_PATH")
            if emulator:
                Asst.set_connection_extras(
                    connection,
                    {"path": emulator, "touch": False, "client_type": "YoStarEN"},
                )
            self.bot = Asst(callback=self.callback)
            options = [
                (InstanceOptionType.touch_type, self.touch_mode),
                (InstanceOptionType.adblite_enabled, "1"),
                (
                    InstanceOptionType.deployment_with_pause,
                    "1" if self.deployment_with_pause else "0",
                ),
            ]
            for key, value in options:
                if not self.bot.set_instance_option(key, value):
                    raise RuntimeError(f"MAA rejected connection option {key}")
            require_gui_stopped()
            if not self.bot.connect(adb_path(), self.address, connection):
                raise RuntimeError("Arknights emulator connection failed")
            return self.bot
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        try:
            if self.bot:
                self.bot.stop()
        finally:
            self.bot = None
            self.lease.__exit__()


class CheckpointStop:
    """A soft deadline waits for combat end; an explicit abort or task error stops now."""

    def __init__(self):
        self.pending = False

    def observe(self, requested, message=None, data=None, abort=False):
        data = data or {}
        self.pending = self.pending or requested
        if abort or message == "TaskChainError":
            return True
        return self.pending and (
            data.get("what") in {"RoguelikeCombatEnd", "RoguelikeSettlement"}
            or message in {"TaskChainCompleted", "AllTasksCompleted"}
        )
