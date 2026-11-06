[CmdletBinding()]
param([string]$Root = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root)
$manifest = Get-Content -LiteralPath (Join-Path $Root 'bundle-manifest.json') -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1 -or $manifest.product -ne 'pla_arknights') { throw 'Unsupported bundle manifest' }
foreach ($entry in $manifest.files.PSObject.Properties) {
    $path = [IO.Path]::GetFullPath((Join-Path $Root $entry.Name))
    if (-not $path.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe manifest path' }
    if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked file: $path" }
    $stream = [IO.File]::OpenRead($path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '') }
    finally { $stream.Dispose(); $hasher.Dispose() }
    if ($hash -ne $entry.Value) { throw "Checksum mismatch: $($entry.Name)" }
}
Write-Host "Verified $(@($manifest.files.PSObject.Properties).Count) bundle files."
