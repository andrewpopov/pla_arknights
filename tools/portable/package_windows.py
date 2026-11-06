"""Build a clean Windows ZIP from matched self-contained GUI and native outputs."""

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]
REQUIRED = (
    "MAA.exe",
    "MAA.dll",
    "MAA.runtimeconfig.json",
    "hostfxr.dll",
    "hostpolicy.dll",
    "externals/coreclr.dll",
    "MaaCore.dll",
    "MaaUtils.dll",
    "resource/tasks/tasks.json",
    "modules/sand/pack/resource/tasks/SandFlow.json",
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_tree(source, target):
    """Materialize files; reject links so a bundle cannot escape its inputs."""
    source, target = Path(source), Path(target)
    for file in sorted(source.rglob("*")):
        if file.is_symlink() or getattr(file, "is_junction", lambda: False)():
            raise ValueError(f"Linked input must be materialized first: {file}")
        if not file.is_file() or any(p in {".git", "__pycache__"} for p in file.parts):
            continue
        if file.suffix.lower() in {".pyc", ".pdb", ".bak"}:
            continue
        dest = target / file.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, dest)


def validate(root):
    root = Path(root)
    for name in REQUIRED:
        if not (root / name).is_file():
            raise ValueError(f"Missing packaged dependency: {name}")
    config = json.loads(
        (root / "MAA.runtimeconfig.json").read_text(encoding="utf-8-sig")
    )
    if not config.get("runtimeOptions", {}).get("includedFrameworks"):
        raise ValueError("GUI must be published with --self-contained true")
    allowed = {
        "hostfxr.dll",
        "hostpolicy.dll",
        "libloader.dll",
        "directml.dll",
        "dxcompiler.dll",
        "dxil.dll",
    }
    unknown = [
        p.name
        for p in root.glob("*.dll")
        if "maa" not in p.name.lower() and p.name.lower() not in allowed
    ]
    if unknown:
        raise ValueError("Unexpected root DLLs: " + ", ".join(unknown))
    for name in ("config", "debug", "cache", "local-build.json", "Build-Local-MAA.cmd"):
        if (root / name).exists():
            raise ValueError(f"Personal state or local launcher in bundle: {name}")


def collect_notices(app, dependency_source):
    """Preserve notices supplied by the actual native and NuGet build inputs."""
    app, dependency_source = Path(app), Path(dependency_source)
    index = []

    def include(file, relative):
        target = app / "licenses" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        index.append(relative.as_posix())

    native = dependency_source / "src/MaaUtils/MaaDeps/vcpkg/installed"
    for file in sorted(native.glob("*/share/*/copyright")):
        include(file, Path("native") / file.relative_to(native))
    assets = dependency_source / "src/MaaWpfGui/obj/project.assets.json"
    if assets.is_file():
        data = json.loads(assets.read_text(encoding="utf-8-sig"))
        folders = [Path(p) for p in data.get("packageFolders", {})]
        candidates = []
        for entry in data.get("libraries", {}).values():
            if entry.get("type") == "package":
                candidates.extend(
                    (folder, folder / entry["path"]) for folder in folders
                )
        for folder in folders:
            for name in (
                "microsoft.netcore.app.runtime.win-*",
                "microsoft.windowsdesktop.app.runtime.win-*",
            ):
                candidates.extend(
                    (folder, p) for p in folder.glob(name + "/*") if p.is_dir()
                )
        seen = set()
        for folder, package in candidates:
            if not package.is_dir() or package in seen:
                continue
            seen.add(package)
            for file in sorted(package.iterdir()):
                if file.is_file() and any(
                    word in file.name.casefold()
                    for word in ("license", "notice", "copying")
                ):
                    include(file, Path("nuget") / file.relative_to(folder))
    if index:
        (app / "licenses/INDEX.json").write_text(
            json.dumps(sorted(index), indent=2) + "\n", encoding="utf-8"
        )
    return index


def matched_versions(app):
    """Check the actual x64 core export against GUI file metadata on Windows."""
    import os

    if os.name != "nt":
        return {"status": "not_run", "reason": "Windows check required"}
    # CI can cross-build ARM64 on an x64 runner; don't load a foreign DLL.
    import platform
    import struct

    core = Path(app) / "MaaCore.dll"
    with core.open("rb") as stream:
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset + 4)
        machine = struct.unpack("<H", stream.read(2))[0]
    host = platform.machine().lower()
    if (machine == 0xAA64 and host not in {"arm64", "aarch64"}) or (
        machine == 0x8664 and host not in {"amd64", "x86_64"}
    ):
        return {"status": "not_run", "reason": "cross-architecture build"}
    import ctypes

    with os.add_dll_directory(str(Path(app).resolve())):
        dll = ctypes.WinDLL(str(core.resolve()))
        dll.AsstGetVersion.restype = ctypes.c_char_p
        native = dll.AsstGetVersion().decode()
    path = str(Path(app).resolve() / "MAA.dll").replace("'", "''")
    gui = (
        subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                f"(Get-Item -LiteralPath '{path}').VersionInfo.ProductVersion",
            ],
            text=True,
        )
        .strip()
        .split("+")[0]
    )
    if gui != native:
        raise ValueError(f"UI/core version mismatch: {gui!r} != {native!r}")
    return {"status": "passed", "gui": gui, "core": native}


def prepare(
    app,
    source=SOURCE,
    version=None,
    revision=None,
    check_versions=True,
    dependency_source=None,
):
    """The shared packaging step for local, release and nightly builds."""
    app, source = Path(app), Path(source)
    for name in ("Install.ps1", "Install.cmd", "Verify.ps1"):
        shutil.copy2(source / "tools/portable" / name, app / name)
    shutil.copy2(source / "FORK_README.md", app / "README.md")
    copy_tree(source / "guides", app / "guides")
    copy_tree(source / "tools/maintenance", app / "tools/maintenance")
    copy_tree(source / "modules/sand", app / "modules/sand")
    shutil.copy2(source / "LICENSE", app / "LICENSE")
    shutil.copy2(
        source / "modules/strategy/local-resource-overrides.json",
        app / "local-resource-overrides.json",
    )
    if revision is None:
        revision = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()
    collect_notices(app, dependency_source or source)
    validate(app)
    manifest = {
        "schema_version": 1,
        "product": "pla_arknights",
        "version": version,
        "source_commit": revision,
        "source_url": "https://github.com/andrewpopov/pla_arknights",
        "personal_settings_included": False,
        "files": {},
        "version_check": matched_versions(app)
        if check_versions
        else {"status": "test_fixture"},
    }
    for p in sorted(app.rglob("*")):
        if p.is_symlink() or getattr(p, "is_junction", lambda: False)():
            raise ValueError(f"Link in package: {p}")
        if p.is_file() and p.name != "bundle-manifest.json":
            manifest["files"][p.relative_to(app).as_posix()] = digest(p)
    (app / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def assemble(
    gui,
    native,
    resources,
    destination,
    source=SOURCE,
    version=None,
    revision=None,
    check_versions=True,
):
    gui, native, resources, destination, source = map(
        Path, (gui, native, resources, destination, source)
    )
    if destination.exists():
        raise ValueError(f"Destination must be new: {destination}")
    destination.mkdir(parents=True)
    # Ignore GUI resource/debug junctions, local launchers and mutable user state.
    for file in gui.iterdir():
        if file.is_file() and file.suffix.lower() in {".exe", ".dll", ".json"}:
            if file.name in {
                "local-build.json",
                "bundle-manifest.json",
                "gui.json",
                "gui.new.json",
            }:
                continue
            shutil.copy2(file, destination / file.name)
        elif file.name in {"externals", "Res", "runtimes"} and file.is_dir():
            copy_tree(file, destination / file.name)
    for file in native.iterdir():
        if file.is_file() and file.suffix.lower() == ".dll":
            if file.stem.lower().endswith("d_maa"):
                raise ValueError(f"Debug dependency cannot be distributed: {file.name}")
            shutil.copy2(file, destination / file.name)
    for name in ("MaaAppHostStub.exe", "MAA.Updater.exe"):
        shutil.copy2(
            native / name,
            destination / ("MAA.exe" if name == "MaaAppHostStub.exe" else name),
        )
    copy_tree(resources, destination / "resource")
    copy_tree(source / "src/Python", destination / "Python")
    dep = source / "tools/DependencySetup_依赖库安装.bat"
    shutil.copy2(dep, destination / dep.name)
    return prepare(
        destination, source, version, revision, check_versions, resources.parent
    )


def archive(app, output):
    app, output = Path(app), Path(output)
    if output.exists() or output.resolve().is_relative_to(app.resolve()):
        raise ValueError("ZIP must be new and outside the application directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for file in sorted(app.rglob("*")):
            if file.is_file():
                bundle.write(file, file.relative_to(app).as_posix())
    sha = digest(output)
    output.with_suffix(output.suffix + ".sha256").write_text(f"{sha}  {output.name}\n")
    return sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, help="Prepare a clean assembled CI app")
    for name in ("gui", "native", "resources", "destination", "zip"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--version")
    parser.add_argument("--revision")
    parser.add_argument("--dependency-source", type=Path)
    args = parser.parse_args()
    if args.app:
        app = args.app
        prepare(
            app,
            version=args.version,
            revision=args.revision,
            dependency_source=args.dependency_source,
        )
    else:
        if not all((args.gui, args.native, args.resources, args.destination)):
            parser.error(
                "Provide --app or all of --gui --native --resources --destination"
            )
        app = args.destination
        assemble(
            args.gui,
            args.native,
            args.resources,
            app,
            version=args.version,
            revision=args.revision,
        )
    if args.zip:
        print(json.dumps({"zip": str(args.zip), "sha256": archive(app, args.zip)}))


if __name__ == "__main__":
    main()
