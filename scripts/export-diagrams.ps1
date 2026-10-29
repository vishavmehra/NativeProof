<#
.SYNOPSIS
    Re-export every draw.io source in docs/diagrams/src to SVG and PNG.

.DESCRIPTION
    Uses the draw.io desktop CLI. By default it looks for
    %LOCALAPPDATA%\Programs\draw.io\draw.io.exe; pass -Drawio or set DRAWIO_EXE to override.
    Writes docs/diagrams/svg/<name>.svg and docs/diagrams/png/<name>.png (scale 2) and fails
    when any export is missing or empty.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/export-diagrams.ps1
#>
[CmdletBinding()]
param(
    [string]$Drawio = $env:DRAWIO_EXE
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$srcDir = Join-Path $root 'docs\diagrams\src'
$svgDir = Join-Path $root 'docs\diagrams\svg'
$pngDir = Join-Path $root 'docs\diagrams\png'

if (-not $Drawio) {
    $Drawio = Join-Path $env:LOCALAPPDATA 'Programs\draw.io\draw.io.exe'
}
if (-not (Test-Path $Drawio)) {
    $command = Get-Command 'draw.io' -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw 'draw.io CLI not found. Install draw.io Desktop, or pass -Drawio <path> or set DRAWIO_EXE.'
    }
    $Drawio = $command.Source
}

New-Item -ItemType Directory -Force -Path $svgDir, $pngDir | Out-Null
$sources = @(Get-ChildItem -Path $srcDir -Filter '*.drawio' | Sort-Object Name)
if ($sources.Count -eq 0) {
    throw "No .drawio files in $srcDir"
}

$failed = @()
foreach ($file in $sources) {
    $name = $file.BaseName
    $targets = @(
        # --theme light keeps the diagram palette in dark-mode viewers instead of an automatic inversion.
        @{ Path = (Join-Path $svgDir "$name.svg"); Options = @('-x', '-f', 'svg', '-b', '16', '--theme', 'light') },
        @{ Path = (Join-Path $pngDir "$name.png"); Options = @('-x', '-f', 'png', '-s', '2', '-b', '16', '--theme', 'light') }
    )
    foreach ($target in $targets) {
        if (Test-Path $target.Path) {
            Remove-Item $target.Path -Force
        }
        $arguments = $target.Options + @('-o', $target.Path, $file.FullName)
        # Piping to Out-Null makes PowerShell wait for draw.io, which is a GUI-subsystem executable.
        & $Drawio @arguments | Out-Null
        $output = Get-Item $target.Path -ErrorAction SilentlyContinue
        $relative = $target.Path.Substring($root.Length + 1)
        if ($null -eq $output -or $output.Length -eq 0) {
            $failed += $relative
            Write-Host "FAILED  $relative"
        }
        else {
            Write-Host ('ok      {0} ({1:N0} bytes)' -f $relative, $output.Length)
        }
    }
}

if ($failed.Count -gt 0) {
    throw "$($failed.Count) export(s) missing or empty: $($failed -join ', ')"
}
Write-Host "Exported $($sources.Count) diagrams to SVG and PNG."
