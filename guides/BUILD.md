# Build and package this fork

## Supported build path

Use a full checkout of `andrewpopov/pla_arknights`, not the private research workspace. On a Windows x64 build machine install Git, Python 3.11+, CMake supporting the repository presets, Visual Studio 2026 C++ build tools/Windows SDK, and the .NET 10 SDK. Git for Windows must include Git Bash; the script finds its `bin/bash.exe` beside the Git installation and does not use WSL. Open a Windows PowerShell where `git`, `python`, `cmake` and `dotnet` resolve to those installed tools.

The preset currently selects Visual Studio 18 2026. An older compiler requires a deliberate preset change.

```powershell
git clone --branch dev-v2 https://github.com/andrewpopov/pla_arknights.git
cd pla_arknights
powershell -NoProfile -ExecutionPolicy Bypass -File tools\portable\Build.ps1
```

`Build.ps1` uses the existing optional-submodule helper, MaaDeps download tool, Windows CMake preset, self-contained .NET publish and NetBeauty packaging. It builds and validates Debug resources before producing the redistributable native/GUI pair. It does not update an existing installation or connect to the emulator. Build logs and outputs stay under `build` and `dist`.

To choose a different output drive or limit parallel build processes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\portable\Build.ps1 -OutputRoot D:\MAA-builds -Jobs 4
```

Run from a clean, committed checkout. The script refuses an existing output directory/ZIP, so select a fresh output root for a repeat build of the same commit. It does not require Administrator rights after installing the compiler and SDK prerequisites.

The result is a clean application directory plus ZIP and SHA-256 file under `dist`. The ZIP includes Sand, field-level custom resource overrides, installer and guides. User config, caches, journals, screenshots and local launcher wrappers are excluded.

## CI and packaging existing outputs

The release and nightly Windows workflows call the same `tools/portable/package_windows.py` support-file step before generating the normal file list. GitHub Actions must be enabled on a fork before workflow dispatch can build artifacts. Use its complete Windows package, not the internal core-only artifact. Publication of a GitHub Release is separate from building an artifact.

For matching outputs you have already built:

```powershell
python tools\portable\package_windows.py --gui build\gui --native build\bin\RelWithDebInfo --resources resource --destination dist\app --version v6.0.0-local --zip dist\pla_arknights-win-x64.zip
```

Use a new destination and ZIP name. The app requires the self-contained NetBeauty layout. Include the entire resource tree, not just tasks or an override pack. Preserve the emitted `bundle-manifest.json`, `LICENSE`, dependency notices and source revision.

## Testing

```powershell
python -m unittest discover -s tools\portable -p "test_*.py"
powershell -NoProfile -ExecutionPolicy Bypass -File dist\app\Verify.ps1
```

Install a copied/extracted ZIP into a new path, verify checksums there and launch the GUI without core initialization for a startup smoke test. Then validate the native resource load separately. These offline checks do not establish a successful game run; configure the new emulator and test a small live task after installation.

## Updating upstream

Fetch the official repository and merge its `dev-v2` into the fork's working branch. Preserve local changes and resolve conflicts; never reset the fork to upstream or let stock binary updates replace its custom core. Rebuild GUI and core together with the same version string.

`modules/strategy/local-resource-overrides.json` protects the fork's custom resource fields during remote resource updates. It records its upstream baseline. When changing strategies or merging an upstream resource change, regenerate/review that field-level policy against the new baseline using `tools/portable/update_overrides.py --base <upstream-commit>`. Do not protect a whole stale resource tree; unrelated new upstream fields should remain visible.

Old private-workspace scripts referencing a particular user's drive or active-install receipt are for that research workspace; they are not needed by this build path.
