<#
.SYNOPSIS
  Installs Extractor for the current user. No administrator rights needed.

.DESCRIPTION
  Copies the built app (dist\Extractor) to %LOCALAPPDATA%\Programs\Extractor, records this
  folder as Extractor's home (where yt-dlp.exe, ffmpeg.exe and your music folders are), adds
  Start menu and desktop shortcuts, and registers an uninstaller under Settings > Apps.
  Running it again updates an existing installation in place.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\install.ps1 -Launch
#>
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\Extractor'),
    [switch]$NoDesktopShortcut,
    [switch]$NoShortcuts,
    [switch]$NoRegistry,
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$build = Join-Path $source 'dist\Extractor'
$builtExe = Join-Path $build 'Extractor.exe'
$target = Join-Path $Destination 'Extractor.exe'

if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "Extractor.exe isn't built yet. Run:  .venv\Scripts\python build.py"
}

$running = Get-Process -Name Extractor -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($Destination, [StringComparison]::OrdinalIgnoreCase) }
if ($running) {
    throw 'Extractor is running. Close its window, then run the installer again.'
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

# Mirror the build into place, so files from an older version don't linger.
# home.json and uninstall.ps1 are written below and are kept out of the mirror.
& robocopy $build $Destination /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 /XF home.json uninstall.ps1 | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "Copying the app failed (robocopy exit code $LASTEXITCODE)."
}

# Extractor looks for yt-dlp.exe, ffmpeg.exe and the music subfolders in its home folder.
$homeJson = ConvertTo-Json @{ home = $source }
[IO.File]::WriteAllText((Join-Path $Destination 'home.json'), $homeJson, (New-Object Text.UTF8Encoding $false))
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $Destination -Force

$version = (Get-Item -LiteralPath $target).VersionInfo.ProductVersion

if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    $folders = @([Environment]::GetFolderPath('Programs'))
    if (-not $NoDesktopShortcut) { $folders += [Environment]::GetFolderPath('Desktop') }
    foreach ($folder in $folders) {
        $link = $shell.CreateShortcut((Join-Path $folder 'Extractor.lnk'))
        $link.TargetPath = $target
        $link.WorkingDirectory = $Destination
        $link.IconLocation = "$target,0"
        $link.Description = 'Save the audio from video links'
        $link.Save()
    }
}

if (-not $NoRegistry) {
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Extractor'
    New-Item -Path $key -Force | Out-Null
    $sizeKb = [int]((Get-ChildItem -LiteralPath $Destination -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
    $uninstall = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Destination\uninstall.ps1`""
    $strings = @{
        DisplayName          = 'Extractor'
        DisplayVersion       = $version
        Publisher            = 'Extractor'
        DisplayIcon          = "$target,0"
        InstallLocation      = $Destination
        UninstallString      = $uninstall
        QuietUninstallString = "$uninstall -Quiet"
    }
    foreach ($name in $strings.Keys) {
        New-ItemProperty -Path $key -Name $name -Value $strings[$name] -PropertyType String -Force | Out-Null
    }
    foreach ($name in 'NoModify', 'NoRepair') {
        New-ItemProperty -Path $key -Name $name -Value 1 -PropertyType DWord -Force | Out-Null
    }
    New-ItemProperty -Path $key -Name 'EstimatedSize' -Value $sizeKb -PropertyType DWord -Force | Out-Null
}

Write-Host "Installed Extractor $version"
Write-Host "  App:    $Destination"
Write-Host "  Home:   $source  (yt-dlp, ffmpeg and your music)"
if (-not $NoShortcuts) { Write-Host ('  Shortcuts: Start menu' + $(if ($NoDesktopShortcut) { '' } else { ' and desktop' })) }
if (-not $NoRegistry) { Write-Host '  Uninstall from Settings > Apps > Installed apps.' }

if ($Launch) { Start-Process -FilePath $target -WorkingDirectory $Destination }
