# pla_arknights

A custom [MaaAssistantArknights](https://github.com/MaaAssistantArknights/MaaAssistantArknights) build with Integrated Strategies improvements, resource-stock farming, daily-task recovery and modular English Tales Within the Sand support.

## Install on another Windows PC

Use a full Windows ZIP built from this fork, rather than the GitHub source-code ZIP or an upstream MAA binary. Extract the entire archive, run `Install.cmd`, then start the normal-user `pla_arknights` desktop shortcut. Alternatively run `MAA.exe` directly from the extracted folder. Keep its DLLs, `externals`, `resource` and `modules` together.

The full bundle includes the self-contained .NET runtime, matching GUI/core, game recognition resources, Sand task module, checksum verifier, installer and these guides. An emulator and Arknights are separate installations. No account, local settings, emulator installation, screenshot archive or research journal is shipped.

- [Installation and first connection](guides/INSTALL.md)
- [Daily tasks, resource farming and IS](guides/USAGE.md)
- [Sand support and research tools](guides/SAND.md)
- [Build, package and update this fork](guides/BUILD.md)
- [Troubleshooting and diagnostics](guides/TROUBLESHOOTING.md)

## Current support

The WPF task queue is the normal entry point. Sand's default mode resumes an existing English save to the world map without spending an Act. Existing-save prosperity farming is a separate mode that spends crafting materials. Full unattended Day 1–6 campaign combat is experimental and still requires map/camera calibration; installing the module does not complete that calibration.

Binary updates through the stock upstream updater are disabled in this fork to keep custom UI/core pairs together. Remote resource updates remain available, and the bundle includes field-level overrides for this fork's custom resources. Upgrade with another full fork bundle in a new directory.

## Source and licensing

This repository contains the app changes and the distributable Sand module; it does not require the private research repository to build or use the GUI. Build instructions use the existing CMake presets, MaaDeps downloader, .NET publisher and NetBeauty layout. See [LICENSE](LICENSE) and preserve included dependency notices when redistributing.

The guides are currently in English. Upstream documentation and translations remain available through the original project.
