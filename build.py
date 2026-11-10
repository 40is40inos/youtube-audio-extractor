"""Build dist/Extractor/Extractor.exe with PyInstaller, and the release zip next to it.

Run it with the project venv, which has pywebview and PyInstaller installed:

    python -m venv .venv
    .venv\\Scripts\\python -m pip install pywebview pyinstaller
    .venv\\Scripts\\python build.py

Then run "Install Extractor.bat" to install it for the current user, or attach
dist/Extractor-<version>-win64.zip to a GitHub release for others to download.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ICON = ROOT / "ui" / "extractor.ico"
REPO_URL = "https://github.com/40is40inos/youtube-audio-extractor"

RELEASE_README = """Extractor {version}
Save the audio of YouTube videos as MP3, Opus, M4A, FLAC, WAV or AAC.
For Windows 10 and 11 (64-bit).

INSTALL
  1. Extract this zip: right-click it > Extract All.
  2. Double-click "Install Extractor.bat".
     The app isn't code-signed, so Windows may warn that it comes from the
     internet or is unrecognised. Choose More info > Run anyway.
  3. Extractor opens. Press "Download tools" once: it downloads yt-dlp and
     FFmpeg (about 115 MB) from their official GitHub releases and checks
     each against its published checksum.

It installs for your Windows user only (no administrator rights), adds Start
menu and desktop shortcuts, and lists itself in Settings > Apps. Audio is saved
to Music\\Extractor unless you pick another folder.

To try it without installing, open the Extractor folder and run Extractor.exe.

UNINSTALL
  Settings > Apps > Installed apps > Extractor > Uninstall.
  Your music is never touched.

Source code and help: {repo}
Only download content you have the right to save.
"""


def crlf(text: str) -> str:
    """Windows line endings, for files people open in Notepad or run with cmd.exe."""
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def package(version: str) -> Path:
    """Zip the built app with the installer, laid out the way install.ps1 expects."""
    app_dir = DIST / "Extractor"
    archive = DIST / f"Extractor-{version}-win64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        out.writestr("Read me.txt", crlf(RELEASE_README.format(version=version, repo=REPO_URL)))
        out.writestr("Install Extractor.bat", crlf((ROOT / "Install Extractor.bat").read_text("utf-8")))
        for name in ("install.ps1", "uninstall.ps1"):
            out.writestr(f"installer/{name}", crlf((ROOT / "installer" / name).read_text("utf-8")))
        for path in sorted(app_dir.rglob("*")):
            if path.is_file():
                out.write(path, "Extractor/" + path.relative_to(app_dir).as_posix())
    return archive


def app_version() -> str:
    match = re.search(r'^__version__ = "([\d.]+)"', (ROOT / "app.py").read_text("utf-8"), re.M)
    if not match:
        sys.exit("Couldn't find __version__ in app.py")
    return match.group(1)


def version_resource(version: str) -> str:
    """The Windows version resource: what Properties > Details and Task Manager show."""
    parts = tuple(int(p) for p in (version.split(".") + ["0", "0", "0"])[:4])
    strings = {
        "CompanyName": "Extractor",
        "FileDescription": "Extractor",
        "FileVersion": version,
        "InternalName": "Extractor",
        "LegalCopyright": "Personal use",
        "OriginalFilename": "Extractor.exe",
        "ProductName": "Extractor",
        "ProductVersion": version,
    }
    table = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts}, prodvers={parts}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
          {table}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    try:
        import PyInstaller  # noqa: F401
        import webview  # noqa: F401
    except ImportError as exc:
        sys.exit(f"Missing {exc.name}. Use the project venv: .venv\\Scripts\\python build.py")

    if not ICON.is_file():
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")], check=True)

    version = app_version()
    BUILD.mkdir(exist_ok=True)
    version_file = BUILD / "version_info.txt"
    version_file.write_text(version_resource(version), "utf-8")

    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "Extractor",
        "--icon", str(ICON),
        "--version-file", str(version_file),
        "--add-data", f"{ROOT / 'ui'};ui",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        # Not needed by the packaged app (the native window has its own folder dialog).
        "--exclude-module", "tkinter",
        str(ROOT / "app.py"),
    ]
    print(f"Building Extractor {version}…", flush=True)
    subprocess.run(args, check=True, cwd=ROOT)
    exe = DIST / "Extractor" / "Extractor.exe"
    size = sum(p.stat().st_size for p in exe.parent.rglob("*") if p.is_file()) / 1_048_576
    print(f"\nBuilt {exe} ({size:.0f} MB with its support files).")
    archive = package(version)
    print(f"Release zip: {archive} ({archive.stat().st_size / 1_048_576:.0f} MB)")
    print('Next: double-click "Install Extractor.bat" to install it for this user.')


if __name__ == "__main__":
    main()
