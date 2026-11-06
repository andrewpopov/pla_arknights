"""Packaging, relocation and integrity regressions; no game input."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from package_windows import (
    SOURCE,
    REQUIRED,
    archive,
    collect_notices,
    assemble,
    copy_tree,
    digest,
    prepare,
    validate,
)


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scripts = {
            name: (SOURCE / "tools/portable" / name).read_bytes()
            for name in ("Install.ps1", "Install.cmd", "Verify.ps1")
        }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.source = self.root / "source"
        for name, content in self.scripts.items():
            p = self.source / "tools/portable" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(content)
        for name in (
            "LICENSE",
            "FORK_README.md",
            "guides/INSTALL.md",
            "guides/SAND.md",
            "modules/sand/pack/resource/tasks/SandFlow.json",
            "modules/strategy/local-resource-overrides.json",
            "src/Python/asst/asst.py",
            "tools/DependencySetup_依赖库安装.bat",
            "tools/maintenance/configure_resource_stock.py",
        ):
            p = self.source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture", encoding="utf-8")
        for name in REQUIRED:
            p = self.app / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"fixture")
        (self.app / "MAA.runtimeconfig.json").write_text(
            json.dumps(
                {
                    "runtimeOptions": {
                        "includedFrameworks": [
                            {"name": "Microsoft.NETCore.App", "version": "10.0.0"}
                        ]
                    }
                }
            )
        )

    def prepare(self):
        return prepare(
            self.app,
            source=self.source,
            version="test",
            revision="fixture",
            check_versions=False,
        )

    def test_bundle_has_guides_installer_modules_and_policy_without_personal_state(
        self,
    ):
        manifest = self.prepare()
        for name in [
            "Install.cmd",
            "Verify.ps1",
            "guides/INSTALL.md",
            "guides/SAND.md",
            "local-resource-overrides.json",
        ]:
            self.assertIn(name, manifest["files"])
        self.assertFalse(manifest["personal_settings_included"])
        self.assertFalse(
            any("C:/Users/andre" in name or "I:" in name for name in manifest["files"])
        )

    def test_missing_self_contained_runtime_is_rejected(self):
        (self.app / "externals/coreclr.dll").unlink()
        with self.assertRaisesRegex(ValueError, "Missing packaged dependency"):
            validate(self.app)

    def test_framework_dependent_gui_is_rejected(self):
        (self.app / "MAA.runtimeconfig.json").write_text(
            '{"runtimeOptions":{"framework":{"name":"Microsoft.NETCore.App"}}}'
        )
        with self.assertRaisesRegex(ValueError, "self-contained"):
            validate(self.app)

    def test_webgpu_runtime_dependencies_are_accepted_but_unknown_dlls_are_not(self):
        for name in ("dxcompiler.dll", "dxil.dll", "webgpu_dawn_maa.dll"):
            (self.app / name).write_bytes(b"fixture")
        validate(self.app)
        (self.app / "foreign.dll").write_bytes(b"fixture")
        with self.assertRaisesRegex(ValueError, "Unexpected root DLLs"):
            validate(self.app)

    def test_dependency_notices_are_preserved_without_personal_paths(self):
        notice = (
            self.source
            / "src/MaaUtils/MaaDeps/vcpkg/installed/maa-x64-windows/share/opencv/copyright"
        )
        notice.parent.mkdir(parents=True, exist_ok=True)
        notice.write_text("Upstream notice")
        index = collect_notices(self.app, self.source)
        self.assertEqual(len(index), 1)
        self.assertEqual(
            (self.app / "licenses" / index[0]).read_text(), "Upstream notice"
        )
        self.assertNotIn(
            str(self.source), (self.app / "licenses/INDEX.json").read_text()
        )

    def test_personal_config_is_rejected(self):
        (self.app / "config").mkdir()
        with self.assertRaisesRegex(ValueError, "Personal state"):
            self.prepare()

    def test_zip_relocates_and_hashes_match(self):
        manifest = self.prepare()
        output = self.root / "bundle.zip"
        checksum = archive(self.app, output)
        self.assertEqual(checksum, digest(output))
        relocated = self.root / "another machine with spaces"
        with zipfile.ZipFile(output) as z:
            z.extractall(relocated)
            self.assertTrue(
                all(
                    not n.startswith("/") and ".." not in Path(n).parts
                    for n in z.namelist()
                )
            )
        for name, expected in manifest["files"].items():
            self.assertEqual(digest(relocated / name), expected, name)

    def test_archive_cannot_write_into_its_own_input(self):
        with self.assertRaises(ValueError):
            archive(self.app, self.app / "bad.zip")

    @unittest.skipIf(os.name == "nt", "symlink creation needs privileges on Windows")
    def test_external_junction_or_symlink_is_not_exported(self):
        (self.app / "escape").symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Linked input"):
            copy_tree(self.app, self.root / "copy")

    def test_assembly_does_not_copy_profile_logs_or_local_launcher(self):
        gui, native, resources = [self.root / n for n in ("gui", "native", "resources")]
        gui.mkdir()
        native.mkdir()
        resources.mkdir()
        for name in (
            "MAA.exe",
            "MAA.dll",
            "hostfxr.dll",
            "hostpolicy.dll",
            "externals/coreclr.dll",
            "MAA.runtimeconfig.json",
        ):
            src = self.app / name
            dest = gui / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
        for name in (
            "MaaCore.dll",
            "MaaUtils.dll",
            "MaaAppHostStub.exe",
            "MAA.Updater.exe",
        ):
            (native / name).write_bytes(b"fixture")
        (resources / "tasks").mkdir()
        (resources / "tasks/tasks.json").write_text("{}")
        for name in (
            "config/gui.new.json",
            "debug/test.png",
            "cache/a",
            "Build-Local-MAA.cmd",
            "local-build.json",
        ):
            p = gui / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("private")
        target = self.root / "assembled"
        assemble(
            gui,
            native,
            resources,
            target,
            source=self.source,
            revision="fixture",
            check_versions=False,
        )
        self.assertFalse((target / "config").exists())
        self.assertFalse((target / "debug").exists())
        self.assertFalse((target / "Build-Local-MAA.cmd").exists())

    @unittest.skipUnless(os.name == "nt", "Windows verifier integration")
    def test_windows_verifier_default_root_and_readable_count(self):
        manifest = self.prepare()
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.app / "Verify.ps1"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"Verified {len(manifest['files'])} bundle files.", result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows installer integration")
    def test_windows_installer_relocates_rejects_tamper_and_existing_destination(self):
        self.prepare()
        destination = self.root / "installed with spaces"
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.app / "Install.ps1"),
            "-Destination",
            str(destination),
            "-NoShortcut",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((destination / "MAA.exe").is_file())
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        (self.app / "MAA.dll").write_bytes(b"tampered")
        command[-2] = str(self.root / "must not exist")
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertFalse((self.root / "must not exist").exists())


class DailyPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "daily_config", SOURCE / "tools/maintenance/configure_dailies.py"
        )
        cls.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.helper)
        cls.preset = json.loads(
            (SOURCE / "modules/configurations/dailies.json").read_text(encoding="utf-8")
        )

    def config(self):
        types = self.preset["enabled_task_types"] + [
            "RoguelikeTask",
            "ReclamationTask",
            "DepotMaintainTask",
        ]
        queue = [{"$type": t, "IsEnable": True} for t in types]
        queue[-1]["PlanList"] = [{"Stage": "1-7", "UseStone": True, "StoneCount": 3}]
        profile = {
            "TaskQueue": queue,
            "Gui": {
                "ConnectSettings": {"AdbPath": "local-only"},
                "StartUpSettings": {"RunDirectly": True},
            },
        }
        return {"Current": "Original", "Configurations": {"Original": profile}}

    def test_clone_preserves_original_connection_and_disables_other_modes(self):
        original = self.config()
        frozen = json.dumps(original, sort_keys=True)
        updated, name = self.helper.configure(original, self.preset)
        self.assertEqual(json.dumps(original, sort_keys=True), frozen)
        self.assertEqual(
            updated["Configurations"][name]["Gui"]["ConnectSettings"],
            {"AdbPath": "local-only"},
        )
        tasks = {t["$type"]: t for t in updated["Configurations"][name]["TaskQueue"]}
        self.assertFalse(tasks["RoguelikeTask"]["IsEnable"])
        self.assertFalse(tasks["ReclamationTask"]["IsEnable"])
        self.assertEqual(tasks["FightTask"]["StagePlan"], ["CE-6", "LS-6"])
        self.assertFalse(tasks["FightTask"]["UseMedicine"])
        self.assertFalse(tasks["FightTask"]["UseStone"])
        self.assertFalse(tasks["DepotMaintainTask"]["PlanList"][0]["UseStone"])
        self.assertFalse(
            updated["Configurations"][name]["Gui"]["StartUpSettings"]["RunDirectly"]
        )

    def test_existing_profile_requires_explicit_source_and_refresh_is_idempotent(self):
        updated, _ = self.helper.configure(self.config(), self.preset)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.helper.configure(updated, self.preset, source="Original")
        refreshed, _ = self.helper.configure(updated, self.preset, source="Dailies")
        self.assertEqual(refreshed, updated)

    def test_missing_daily_task_is_rejected(self):
        config = self.config()
        config["Configurations"]["Original"]["TaskQueue"] = []
        with self.assertRaisesRegex(ValueError, "required tasks"):
            self.helper.configure(config, self.preset)


class PortableDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "portable_runtime", SOURCE / "modules/sand/tools/maa_runtime.py"
        )
        cls.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runtime)

    def test_environment_overrides_are_respected(self):
        with patch.dict(
            os.environ,
            {
                "MAA_RUNTIME": "D:/Apps/maa",
                "MAA_DATA_DIR": "E:/evidence",
                "MAA_ADB": "F:/emulator/adb.exe",
            },
        ):
            self.assertEqual(
                str(self.runtime.default_maa_path()), str(Path("D:/Apps/maa"))
            )
            self.assertEqual(self.runtime.data_path("runs"), Path("E:/evidence/runs"))
            self.assertEqual(self.runtime.adb_path(), "F:/emulator/adb.exe")

    def test_controller_connection_and_lock_follow_environment(self):
        spec = importlib.util.spec_from_file_location(
            "portable_session", SOURCE / "modules/sand/tools/maa_session.py"
        )
        session = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"maa_runtime": self.runtime}):
            spec.loader.exec_module(session)
        with patch.dict(
            os.environ,
            {"MAA_ADDRESS": "127.0.0.1:5555", "MAA_DATA_DIR": "D:/local-evidence"},
        ):
            native = session.NativeSession(Path("runtime"), Path("output"), None)
            self.assertEqual(native.address, "127.0.0.1:5555")
            self.assertEqual(
                native.lease.directory, Path("D:/local-evidence/controller-locks")
            )

    def test_adb_missing_has_actionable_error(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.runtime.shutil, "which", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "MAA_ADB"):
                self.runtime.adb_path()

    def test_bundle_runtime_defaults_do_not_reference_original_pc(self):
        folder = SOURCE / "modules/sand/tools"
        for p in folder.glob("*.py"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("C:\\Users\\andre", text, str(p))
            self.assertNotIn("I:\\MuMuPlayerGlobal", text, str(p))
            self.assertNotIn("I:/MAA-data", text, str(p))


if __name__ == "__main__":
    unittest.main()
