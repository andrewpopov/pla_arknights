[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'pla_arknights'),
    [switch]$NoShortcut
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Verify.ps1') -Root $PSScriptRoot
$Destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $Destination) { throw 'Choose a new destination. Existing installations and settings are never overwritten.' }
if ($Destination.StartsWith($PSScriptRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Install outside the extracted bundle' }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'bundle-manifest.json') -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Path $Destination | Out-Null
foreach ($entry in $manifest.files.PSObject.Properties) {
    $target = Join-Path $Destination $entry.Name
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $entry.Name) -Destination $target
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'bundle-manifest.json') -Destination $Destination
& (Join-Path $Destination 'Verify.ps1') -Root $Destination
if (-not $NoShortcut) {
    $shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'pla_arknights.lnk'
    if (Test-Path -LiteralPath $shortcutPath) { throw "Installed, but shortcut already exists: $shortcutPath. Launch MAA.exe from $Destination." }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcutPath)
    $shortcut.TargetPath = Join-Path $Destination 'MAA.exe'
    $shortcut.WorkingDirectory = $Destination
    $shortcut.IconLocation = $shortcut.TargetPath + ',0'
    $shortcut.Save()
}
Write-Host "Installed to $Destination. Start MAA.exe and configure your emulator. Administrator rights are not needed."
