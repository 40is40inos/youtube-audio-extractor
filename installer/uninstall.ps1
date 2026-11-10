<#
.SYNOPSIS
  Removes an installed copy of Extractor. Settings > Apps runs this.

.DESCRIPTION
  Deletes the program folder this script sits in, its shortcuts and its Settings > Apps entry.
  Your music, yt-dlp.exe and ffmpeg.exe are never touched. Preferences and the recent list stay
  in %LOCALAPPDATA%\YouTubeAudioExtractor unless you pass -RemoveData.
#>
param(
    [switch]$RemoveData,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$installDir = $PSScriptRoot
$exe = Join-Path $installDir 'Extractor.exe'

# Only ever delete an installed copy: the folder must hold the app and the home.json the installer writes.
if (-not ((Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath (Join-Path $installDir 'home.json')))) {
    throw "This doesn't look like an installed copy of Extractor ($installDir). Nothing was removed."
}

$running = Get-Process -Name Extractor -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($installDir, [StringComparison]::OrdinalIgnoreCase) }
if ($running) {
    throw 'Extractor is running. Close its window, then uninstall again.'
}

# Remove only shortcuts that point at this copy.
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in [Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop')) {
    $path = Join-Path $folder 'Extractor.lnk'
    if ((Test-Path -LiteralPath $path) -and $shell.CreateShortcut($path).TargetPath -ieq $exe) {
        Remove-Item -LiteralPath $path -Force
    }
}

$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Extractor'
if ((Test-Path $key) -and ((Get-ItemProperty $key).InstallLocation -ieq $installDir)) {
    Remove-Item -Path $key -Recurse -Force
}

if ($RemoveData) {
    $data = Join-Path $env:LOCALAPPDATA 'YouTubeAudioExtractor'
    if (Test-Path -LiteralPath $data) { Remove-Item -LiteralPath $data -Recurse -Force }
}

Set-Location -LiteralPath $env:TEMP
Remove-Item -LiteralPath $installDir -Recurse -Force

if (-not $Quiet) {
    Write-Host 'Extractor was removed. Your music, yt-dlp and ffmpeg were not touched.'
}
