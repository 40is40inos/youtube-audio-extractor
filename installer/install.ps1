<#
.SYNOPSIS
  Installs Extractor for the current user. No administrator rights needed.

.DESCRIPTION
  Copies the app to %LOCALAPPDATA%\Programs\Extractor, adds Start menu and desktop shortcuts,
  and registers an uninstaller under Settings > Apps. Running it again updates an existing
  installation in place.

  It works from a downloaded release (the app is in the Extractor folder next to this
  script's folder) and from a source checkout after build.py (dist\Extractor). Installed from
  a checkout, the checkout stays Extractor's home: yt-dlp.exe, ffmpeg.exe and the music
  folders are used from there. A release saves music to Music\Extractor and downloads yt-dlp
  and FFmpeg on first launch.

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
$root = Split-Path -Parent $PSScriptRoot
$fromCheckout = $false
$build = Join-Path $root 'Extractor'
if (-not (Test-Path -LiteralPath (Join-Path $build 'Extractor.exe'))) {
    $build = Join-Path $root 'dist\Extractor'
    $fromCheckout = $true
}
$builtExe = Join-Path $build 'Extractor.exe'
$target = Join-Path $Destination 'Extractor.exe'

if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "Extractor.exe wasn't found next to the installer. From the source code, build it first:  .venv\Scripts\python build.py"
}

$running = Get-Process -Name Extractor -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path.StartsWith($Destination, [StringComparison]::OrdinalIgnoreCase) }
if ($running) {
    throw 'Extractor is running. Close its window, then run the installer again.'
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

# Mirror the app into place, so files from an older version don't linger. The files written
# below (and a home.json from an earlier install) are kept out of the mirror.
& robocopy $build $Destination /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 /XF home.json install.json uninstall.ps1 | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "Copying the app failed (robocopy exit code $LASTEXITCODE)."
}

if ($fromCheckout) {
    # Extractor uses the checkout's yt-dlp.exe, ffmpeg.exe and music folders.
    $homeJson = ConvertTo-Json @{ home = $root }
    [IO.File]::WriteAllText((Join-Path $Destination 'home.json'), $homeJson, (New-Object Text.UTF8Encoding $false))
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $Destination -Force

# Files copied out of a downloaded zip carry its "from the internet" mark. Installed program
# files shouldn't, or Windows warns again on every launch.
Get-ChildItem -LiteralPath $Destination -Recurse -File | Unblock-File

$version = (Get-Item -LiteralPath $target).VersionInfo.ProductVersion
# Marks the folder as an installed copy, so the uninstaller knows it may delete it.
$marker = ConvertTo-Json @{ app = 'Extractor'; version = $version }
[IO.File]::WriteAllText((Join-Path $Destination 'install.json'), $marker, (New-Object Text.UTF8Encoding $false))

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
        URLInfoAbout         = 'https://github.com/40is40inos/youtube-audio-extractor'
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
$homeFile = Join-Path $Destination 'home.json'
if (Test-Path -LiteralPath $homeFile) {
    $homeDir = (Get-Content -LiteralPath $homeFile -Raw | ConvertFrom-Json).home
    Write-Host "  Home:   $homeDir  (yt-dlp, ffmpeg and your music)"
} else {
    Write-Host '  Music:  saved to Music\Extractor (you can pick any folder in the app)'
    Write-Host '  First launch: press Download tools to fetch yt-dlp and FFmpeg (about 115 MB).'
}
if (-not $NoShortcuts) { Write-Host ('  Shortcuts: Start menu' + $(if ($NoDesktopShortcut) { '' } else { ' and desktop' })) }
if (-not $NoRegistry) { Write-Host '  Uninstall from Settings > Apps > Installed apps.' }

if ($Launch) { Start-Process -FilePath $target -WorkingDirectory $Destination }
