# English Tales Within the Sand

## Queued GUI task

Add or enable `Sand (Reclamation Algorithm)` in the task queue. It uses the same native MAA controller as the other tasks.

- `ResumeSand`: resumes an existing save and stops at the world map. Supported entry points include Home, Terminal, theme selection, selected Tales, Resume and an already-open Sand world. It spends no Act.
- `ProsperityInSave`: the separate native prosperity mode works within an existing save and spends crafting materials. Review its tool and batch settings before starting.

Neither mode resets the campaign or creates a new save. Sand is excluded from blanket select-all behavior; enable it deliberately. Stop other queue tasks before doing manual Sand combat.

## Experimental campaign tools

The bundle includes `modules/sand/pack` and `modules/sand/tools`, with day plans, task graphs, OCR/templates and controllers. Full unattended early-campaign Day 1–6 combat is not calibrated. Route profiles can contain archived camera-image paths from the original research PC; those images are not shipped. Use your own images via the tools' `--assets` or other explicit input options and repeat calibration before execution.

The queued GUI task needs no Python. Optional controllers require Windows Python 3.11 or newer, the packages in `modules/sand/pack/requirements.txt`, and a compatible Debug native runtime for the CoreEval adapter. Debug runtimes are developer build outputs, not part of the normal redistributable ZIP; build them using the build guide. Use explicit `--runtime` and `--pack` values for replay tools and read each command's `--help`.

Example PowerShell environment for research tools:

```powershell
$env:MAA_RUNTIME = 'D:\Apps\pla_arknights'
$env:MAA_DATA_DIR = 'D:\MAA-data'
$env:MAA_ADB = 'D:\Emulator\adb.exe'
$env:MAA_ADDRESS = '127.0.0.1:16384'
$env:MAA_CONNECTION_CONFIG = 'General'
python -m venv .venv
.\.venv\Scripts\python -m pip install -r modules\sand\pack\requirements.txt
.\.venv\Scripts\python modules\sand\tools\maa_sand_player.py --help
```

Replace every example location/address with values from your PC. `MAA_EMULATOR_PATH` optionally supplies emulator-specific connection extras. If `MAA_DATA_DIR` is unset, optional controller diagnostics use a per-user local data folder. Put it on a data drive to keep screenshots off C. `--output` can select a run folder.

Offline plan validation is the default for research commands. Live execution requires the command's explicit execution option, calibrated route/assets, enough provisions and an owned squad matching the plan. Run one bounded action, verify the result and save a checkpoint. Pause an active battle while investigating rather than leaving its clock running.
