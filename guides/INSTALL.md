# Install and connect

## Requirements

- Windows x64 for the locally produced x64 bundle. Upstream CI also has a separate ARM64 build; use the matching architecture.
- An Android emulator with Arknights installed, signed in and ADB enabled.
- A writable local folder with room for the extracted app, resources and diagnostics. Do not install in Program Files.
- Internet access for the game and optional remote resource updates.

The self-contained package includes .NET. If Windows reports missing Visual C++ runtime DLLs, use the included `DependencySetup_依赖库安装.bat` to install the official prerequisites; this optional system dependency step may request elevation. The MAA app itself runs normally without Administrator rights.

## Install

1. Copy the full ZIP and its `.sha256` file to the new PC. In PowerShell use `Get-FileHash .\pla_arknights-win-x64.zip -Algorithm SHA256` and compare with the supplied checksum. Use the actual downloaded filename.
2. Extract the entire ZIP. Read `README.md` in that folder.
3. Run `Install.cmd`. It verifies the bundle and copies it to `%LOCALAPPDATA%\pla_arknights`, then creates a normal-user desktop shortcut. It refuses to overwrite an existing installation.
4. For another destination, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Destination D:\Apps\pla_arknights`. Add `-NoShortcut` to avoid creating a shortcut. Use a new directory for each upgrade.
5. Start the app and complete first-use setup on this machine. Choose the correct game client; the custom Sand work targets the English client.
6. In connection settings select your emulator, its actual `adb.exe`, and its ADB address. These values must come from the new emulator, not the old PC. Use the app's connection test before starting tasks.
7. Start one small daily task first and check its result. Review task selections and sanity spending before enabling a larger queue.

The installer does not start the game or run tasks. Double-clicking `MAA.exe` from the extracted folder is also supported and does not require installation.

## Settings migration and storage

Fresh installs contain no old profiles. To migrate your own settings, fully exit both copies through the tray menu, back up the destination, then copy only the old `config` folder. Reconfigure ADB, emulator paths, schedules and local folders before running anything. Keep your profile private.

Logs normally live under the app's `debug` folder. To move them off the system drive, close MAA, create a diagnostic directory on your data drive, and link the app's `debug` directory there with a Windows directory junction. An existing `debug` folder must first be moved aside. The distributed ZIP never contains a junction to the original PC.

## Upgrade or uninstall

Install a newer full fork build in a new folder, migrate settings deliberately, verify the connection, and keep the previous folder for rollback. Do not mix individual GUI/core DLLs. To uninstall, exit MAA and remove its installation folder and shortcut. Your emulator and game are separate.
