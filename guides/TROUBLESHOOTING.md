# Troubleshooting

## App does not start or reports UI/core mismatch

Extract a complete package into a fresh folder. Do not combine an upstream GUI, this fork's core and DLLs from an earlier installation. Run `Verify.ps1` from the extracted package. If a runtime dependency is missing, use the included dependency setup script. The self-contained bundle should not require a separate .NET installation.

Keep `MAA.exe` beside `MAA.dll`, `externals`, `resource` and `modules`; a desktop shortcut must point to the executable in that folder, not a copied executable on the desktop. Run as a normal user.

## Cannot connect to emulator

Start the emulator and Arknights, enable ADB and check the emulator's current ADB address and executable path. Test them in MAA's connection settings. Close a second MAA instance or other automation. The old machine's emulator port, drive letter and installation directory are not portable settings.

## Sand task missing or not progressing

Check `modules/sand/pack/resource/tasks/SandFlow.json` exists beside the installed executable. Choose the English game client and an existing Tales Within the Sand save. Resume mode intentionally stops at the world map; it is not the experimental Day 1–6 player. The installer does not enable live spending or create a new save.

For optional controllers, check the configured Python environment, Debug runtime, ADB and local calibration images. Archived image paths in prototype profiles are provenance, not distributable assets. Use the guide's environment settings and explicit path options.

## Updates

Remote resource updates are supported. Binary upgrades use a full new fork bundle. If custom resource policy needs revision, rebuild/package with its reviewed field-level override manifest. Keep the old installation for rollback rather than copying individual DLLs.

## Useful failure evidence

Save the app version, bundle source revision, enabled task and settings, final screen, relevant log segment and the most recent failure screenshots. For IS include stage, current squad, promotions, recruitment/hope decisions, Tongbao effects and life before/after the map. For Sand include day/Acts, provisions, task mode, squad and last checkpoint.

Logs and screenshots can contain account information or local paths; review them before sharing. Local diagnostics and settings are deliberately not bundled for another machine.
