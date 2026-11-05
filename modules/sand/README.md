# Sand extension

This module supplies the English Tales Within the Sand task graphs, templates
and research controllers used by this fork. The queued Reclamation Algorithm
task uses the GUI's existing MaaCore instance and controller.

The default queue operation resumes an existing save and stops at the world map
without spending an Act. It handles Home, Terminal, the Reclamation overview,
theme selection, selected Tales, Resume, and an already-open Sand world.
Native prosperity farming is a separate existing-save mode and spends crafting
materials. Neither queued mode creates or resets a save.

Windows release workflows include this directory as `modules/sand` in the app
folder. For a manual GUI build, copy this directory to the same path beside the
executable. The queued resume mode does not require Python.

The optional Python controllers in `tools/` require Python, `pack/requirements.txt`
and a compatible native Debug runtime supplied through their CLI options.
Archived screenshots, user journals and camera-anchor images are not included;
calibrate and provide those locally. Controller commands default to validation;
review their help before explicit execution. Experimental route profiles do not
establish unattended Day 1–6 campaign combat support.
