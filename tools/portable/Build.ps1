[CmdletBinding()]
param([string]$OutputRoot = '', [int]$Jobs = 4)
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $OutputRoot) { $OutputRoot = Join-Path $source 'dist' }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
function Run-Native([string]$Program, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
Push-Location $source
try {
    $revision = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Build from a Git checkout' }
    if (& git status --porcelain --untracked-files=no) { throw 'Commit source changes before producing a distributable build' }
    $version = 'v6.0.0-pla.' + $revision.Substring(0, 12)
    $app = Join-Path $OutputRoot ('app-' + $revision.Substring(0, 12))
    $zip = Join-Path $OutputRoot ('pla_arknights-' + $revision.Substring(0, 12) + '-win-x64.zip')
    if ((Test-Path -LiteralPath $app) -or (Test-Path -LiteralPath $zip)) { throw 'Output already exists; select a fresh OutputRoot' }
    $gitCommand = Get-Command git -ErrorAction Stop
    $gitRoot = Split-Path (Split-Path $gitCommand.Source -Parent) -Parent
    $bash = Join-Path $gitRoot 'bin/bash.exe'
    if (-not (Test-Path -LiteralPath $bash)) {
        throw 'Git Bash not found beside git.exe. Install Git for Windows and use its git.exe on PATH.'
    }
    Run-Native $bash @('./.github/scripts/sync-optional-submodules.sh', '--init', '--depth', '1', 'src/MaaUtils', '3rdparty/EmulatorExtras')
    Run-Native python @('tools/maadeps-download.py', 'x64-windows')
    Run-Native cmake @('--preset', 'windows-x64', "-DMAA_HASH_VERSION=$version", '-DBUILD_DEBUG_DEMO=OFF')
    Run-Native cmake @('--build', 'build', '--config', 'Debug', '--target', 'MaaCore', '--parallel', "$Jobs")
    Run-Native python @('tools/portable/check_runtime.py', '--runtime', 'build/bin/Debug', '--source', $source, '--output', (Join-Path $OutputRoot 'debug-validation'))
    Run-Native cmake @('--build', 'build', '--config', 'RelWithDebInfo', '--target', 'MaaCore', 'MAA.Updater', 'MaaAppHostStub', '--parallel', "$Jobs")
    $gui = Join-Path $source 'build/portable-gui'
    Run-Native dotnet @('publish', 'src/MaaWpfGui/MaaWpfGui.csproj', '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true', '-o', $gui, '-p:DisableBeauty=True', "-p:Version=6.0.0-pla.$($revision.Substring(0,12))", "-p:InformationalVersion=$version")
    $packages = $env:NUGET_PACKAGES
    if (-not $packages) { $packages = Join-Path $HOME '.nuget/packages' }
    $beauty = Join-Path $packages 'nulastudio.netbeauty/2.1.5/tools/win-x86/nbeauty2.exe'
    Run-Native $beauty @('--usepatch', $gui, './externals')
    Run-Native python @('tools/portable/package_windows.py', '--gui', $gui, '--native', 'build/bin/RelWithDebInfo', '--resources', 'resource', '--destination', $app, '--version', $version, '--revision', $revision, '--zip', $zip)
    & (Join-Path $app 'Verify.ps1') -Root $app
    Write-Host "Ready to transfer: $zip"
} finally { Pop-Location }
