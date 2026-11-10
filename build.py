"""Build dist/Extractor/Extractor.exe with PyInstaller.

Run it with the project venv, which has pywebview and PyInstaller installed:

    python -m venv .venv
    .venv\\Scripts\\python -m pip install pywebview pyinstaller
    .venv\\Scripts\\python build.py

Then run "Install Extractor.bat" to install it for the current user.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
ICON = ROOT / "ui" / "extractor.ico"


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
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        # Not needed by the packaged app (the native window has its own folder dialog).
        "--exclude-module", "tkinter",
        str(ROOT / "app.py"),
    ]
    print(f"Building Extractor {version}…", flush=True)
    subprocess.run(args, check=True, cwd=ROOT)
    exe = ROOT / "dist" / "Extractor" / "Extractor.exe"
    size = sum(p.stat().st_size for p in exe.parent.rglob("*") if p.is_file()) / 1_048_576
    print(f"\nBuilt {exe} ({size:.0f} MB with its support files).")
    print('Next: double-click "Install Extractor.bat" to install it for this user.')


if __name__ == "__main__":
    main()
