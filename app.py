"""Extractor: a local web UI over yt-dlp and ffmpeg for saving YouTube audio.

Serves the interface in ui/ on 127.0.0.1 and shows it in a native window
(pywebview on WebView2). Without pywebview installed it falls back to a
frameless Edge or Chrome app window, which needs nothing beyond the standard
library. Packaged as Extractor.exe by build.py.

    pythonw app.py                 normal launch (what Launch_Extractor_GUI.bat runs)
    python app.py --dev            serve only: no window, no idle shutdown, prints the URL
"""

from __future__ import annotations

import argparse
import collections
import ctypes
from glob import escape as glob_escape
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

__version__ = "2.1.0"
APP_NAME = "Extractor"


def _resource_dir() -> Path:
    """Where the ui/ folder lives. PyInstaller unpacks bundled data under sys._MEIPASS."""
    return Path(getattr(sys, "_MEIPASS", None) or Path(__file__).resolve().parent)


def _home_dir() -> Path:
    """The folder that holds yt-dlp.exe, ffmpeg.exe and the music subfolders.

    From source it is this folder. An installed Extractor.exe reads it from the home.json
    the installer writes next to the exe; a portable exe uses its own folder.
    """
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).resolve().parent
    try:
        home = Path(json.loads((exe_dir / "home.json").read_text("utf-8-sig"))["home"])
        if home.is_dir():
            return home
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return exe_dir


APP_DIR = _home_dir()
UI_DIR = _resource_dir() / "ui"
ICON = UI_DIR / "extractor.ico"
YTDLP = APP_DIR / "yt-dlp.exe"
FFMPEG = APP_DIR / "ffmpeg.exe"
DEFAULT_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "YouTubeAudioExtractor"
PREFERRED_PORT = 47361
APP_ID = "youtube-audio-extractor"

FORMATS = ("mp3", "opus", "m4a", "flac", "wav", "aac", "best")
BROWSERS = ("chrome", "firefox", "edge", "brave")
DEFAULT_FOLDER = "YoutubeExtracts"
HIDDEN_DIRS = {"__pycache__", "temp", "ui", "build", "dist", "installer", "tools"}
AUDIO_EXTS = {".mp3", ".opus", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".webm", ".mka", ".alac"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROGRESS_TAG = "@@progress "
DESTINATION = re.compile(r"^\[(?:download|ExtractAudio)\] Destination: (.+)$")
THUMB_PREFIX = "https://i.ytimg.com/"
THUMB_URL = re.compile(r"^https://i\.ytimg\.com/vi/[A-Za-z0-9_-]{11}/(?:maxresdefault|sddefault|hqdefault|mqdefault)\.jpg$")
WINDOW_BG = "#0A0A0C"

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
CSP = (
    "default-src 'self'; img-src 'self' https://i.ytimg.com data:; style-src 'self'; "
    "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

# Failure codes the UI turns into plain-language messages, matched against the log (lowercased).
ERROR_PATTERNS = (
    ("http403", ("http error 403", "403: forbidden")),
    ("signin", ("sign in to confirm", "sign in to view", "use --cookies-from-browser or --cookies")),
    ("cookies_browser", ("failed to decrypt", "could not copy", "cookie database", "could not find")),
    ("unavailable", (
        "video unavailable", "video is unavailable", "private video", "has been removed",
        "not available in your country",
    )),
    ("unsupported", ("unsupported url",)),
    ("ffmpeg", ("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed")),
)


class Busy(Exception):
    """Another extraction or update is already running."""


# --------------------------------------------------------------------------- helpers


def clean_url(raw) -> str:
    if not isinstance(raw, str):
        raise ValueError("url")
    url = raw.strip()
    if not url or len(url) > 2048 or any(c.isspace() for c in url):
        raise ValueError("url")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme.lower() not in ("http", "https") or "." not in host:
        raise ValueError("url")
    return url


def youtube_id(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    candidate = ""
    if host in ("youtu.be", "www.youtu.be"):
        candidate = parts.path.lstrip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com") or host.endswith("youtube-nocookie.com"):
        query = urllib.parse.parse_qs(parts.query)
        if query.get("v"):
            candidate = query["v"][0]
        else:
            match = re.match(r"^/(?:shorts|live|embed|v)/([^/?#]+)", parts.path)
            candidate = match.group(1) if match else ""
    else:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate) else None


def clean_filename(raw) -> str:
    if not isinstance(raw, str):
        return ""
    name = raw.strip()
    lower = name.lower()
    for ext in sorted(AUDIO_EXTS | {".mp4", ".mkv"}, key=len, reverse=True):
        if lower.endswith(ext):
            name = name[: -len(ext)]
            break
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:180]


def short_text(raw, limit: int) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text[:limit] if text else None


def resolve_folder(value) -> Path:
    value = value.strip() if isinstance(value, str) else ""
    path = Path(value or DEFAULT_FOLDER)
    if path.is_absolute():
        return path
    if path.drive or ".." in path.parts:
        raise ValueError("folder")
    return APP_DIR / path


def list_folders(custom: list) -> list:
    names = [DEFAULT_FOLDER]
    try:
        for entry in sorted(APP_DIR.iterdir(), key=lambda p: p.name.lower()):
            if (
                entry.is_dir()
                and not entry.name.startswith(".")
                and entry.name not in HIDDEN_DIRS
                and entry.name not in names
            ):
                names.append(entry.name)
    except OSError:
        pass
    folders = []
    for name in names:
        folders.append({"value": name, "label": name})
        if name != DEFAULT_FOLDER:
            continue
        # The default folder often holds the real library (one folder per playlist or person).
        try:
            children = sorted((APP_DIR / name).iterdir(), key=lambda p: p.name.lower())
        except OSError:
            children = []
        for child in children:
            if child.is_dir() and not child.name.startswith("."):
                folders.append({"value": f"{name}\\{child.name}", "label": f"{name} › {child.name}"})
    for path in custom:
        if isinstance(path, str) and Path(path).is_dir():
            folders.append({"value": path, "label": path, "custom": True})
    return folders


def list_cookie_sources() -> list:
    sources = [{"value": "none", "label": "No cookies"}]
    sources += [{"value": f"browser:{b}", "label": f"{b.title()} (live session)"} for b in BROWSERS]
    try:
        for entry in sorted(APP_DIR.glob("*.txt"), key=lambda p: p.name.lower()):
            if "cookie" in entry.name.lower() and entry.is_file():
                age = (time.time() - entry.stat().st_mtime) / 3600
                sources.append({"value": f"file:{entry.name}", "label": entry.name, "age_hours": round(age, 1)})
    except OSError:
        pass
    return sources


def read_clipboard_text() -> str:
    """Read Unicode text from the Windows clipboard without any GUI toolkit."""
    if os.name != "nt":
        return ""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    cf_unicodetext = 13
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        return ""
    try:
        handle = user32.GetClipboardData(cf_unicodetext)
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)[:4096]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def clipboard_url() -> str | None:
    """Return the clipboard only when it holds a single link, so other clipboard text never reaches the page."""
    text = read_clipboard_text().strip()
    if not text or len(text) > 2048 or any(c.isspace() for c in text):
        return None
    if not re.match(r"^(https?://|www\.|youtu\.be/|m\.youtube\.|music\.youtube\.|youtube\.com/)", text, re.I):
        return None
    try:
        return clean_url(text)
    except ValueError:
        return None


BROWSE_SCRIPT = (
    "import json, sys, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True); root.update()\n"
    "path = filedialog.askdirectory(parent=root, initialdir=sys.argv[1], title='Choose where to save audio')\n"
    "sys.stdout.write(json.dumps(path or ''))\n"
)


def browse_folder(initial: str) -> str | None:
    """Show the native folder picker in a child process (Tk must own its thread)."""
    try:
        out = subprocess.run(
            [sys.executable, "-c", BROWSE_SCRIPT, initial],
            capture_output=True,
            timeout=900,
            creationflags=NO_WINDOW,
        )
        path = json.loads(out.stdout.decode("ascii", "replace").strip() or '""')
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return os.path.normpath(path) if isinstance(path, str) and path else None


def open_path(raw, action: str) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    path = Path(raw)
    if not path.is_absolute():
        path = APP_DIR / path
    if action == "play":
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
            os.startfile(str(path))
            return True
        return False
    if action == "reveal" and path.is_file():
        subprocess.Popen(f'explorer /select,"{path}"')
        return True
    if not path.is_dir():
        path = path.parent
    if path.is_dir():
        os.startfile(str(path))
        return True
    return False


def to_number(raw) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


# --------------------------------------------------------------------------- Windows shell integration


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text: str) -> "GUID":
        import uuid

        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)


class FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("hwnd", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint),
        ("uCount", ctypes.c_uint),
        ("dwTimeout", ctypes.c_uint),
    ]


def find_own_window(title: str) -> int | None:
    """The visible top-level window of this process with the given title."""
    if os.name != "nt":
        return None
    user32 = ctypes.WinDLL("user32")
    found: list[int] = []
    pid = os.getpid()
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _param):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(ctypes.c_void_p(hwnd)):
            buffer = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, 256)
            if buffer.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(callback_type(visit), None)
    return found[0] if found else None


def style_title_bar(hwnd: int) -> None:
    """Dark caption that matches the app background (Windows 11; older Windows ignores it)."""
    dwmapi = ctypes.WinDLL("dwmapi")

    def set_attribute(attribute: int, value: int) -> None:
        data = ctypes.c_int(value)
        dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data))

    set_attribute(20, 1)  # DWMWA_USE_IMMERSIVE_DARK_MODE
    set_attribute(35, 0x000C0A0A)  # DWMWA_CAPTION_COLOR, 0x00BBGGRR for #0A0A0C
    set_attribute(36, 0x00F0EDED)  # DWMWA_TEXT_COLOR, #EDEDF0
    set_attribute(34, 0x00221E1E)  # DWMWA_BORDER_COLOR, #1E1E22


def flash_if_inactive(hwnd: int) -> None:
    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    if user32.GetForegroundWindow() == hwnd:
        return
    info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x2 | 0xC, 0, 0)  # tray, until focused
    user32.FlashWindowEx(ctypes.byref(info))


def bring_to_front(hwnd: int) -> None:
    user32 = ctypes.WinDLL("user32")
    if user32.IsIconic(ctypes.c_void_p(hwnd)):
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
    user32.SetForegroundWindow(ctypes.c_void_p(hwnd))


class Taskbar:
    """Download progress on the window's taskbar button, via ITaskbarList3.

    COM objects are tied to the thread that created them, so one thread owns the
    object and applies updates from a queue. Any failure just turns the feature off.
    """

    NONE, INDETERMINATE, NORMAL, ERROR = 0, 1, 2, 4

    def __init__(self):
        self.hwnd: int | None = None
        self.updates: queue.Queue = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def show(self, state: int, percent: float | None = None) -> None:
        self.updates.put((state, percent))

    def _run(self) -> None:
        try:
            ole32 = ctypes.WinDLL("ole32")
            ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
            ole32.CoCreateInstance.argtypes = [
                ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
            ]
            ole32.CoCreateInstance.restype = ctypes.c_long
            clsid = GUID.parse("56FDF344-FD6D-11D0-958A-006097C9A090")  # CLSID_TaskbarList
            iid = GUID.parse("EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF")  # IID_ITaskbarList3
            this = ctypes.c_void_p()
            if ole32.CoCreateInstance(ctypes.byref(clsid), None, 0x1, ctypes.byref(iid), ctypes.byref(this)) or not this:
                return
            vtable = ctypes.cast(ctypes.cast(this, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
            method = ctypes.WINFUNCTYPE
            hr_init = method(ctypes.c_long, ctypes.c_void_p)(vtable[3])
            set_value = method(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_ulonglong)(vtable[9])
            set_state = method(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)(vtable[10])
            if hr_init(this):
                return
        except (OSError, AttributeError, ValueError):
            return
        while True:
            state, percent = self.updates.get()
            if not self.hwnd:
                continue
            hwnd = ctypes.c_void_p(self.hwnd)
            set_state(this, hwnd, state)
            if state in (self.NORMAL, self.ERROR) and percent is not None:
                set_value(this, hwnd, int(max(0.0, min(100.0, percent)) * 10), 1000)


# --------------------------------------------------------------------------- state


class Store:
    """Preferences and recent extractions, kept in a small JSON file."""

    MAX_HISTORY = 40

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"prefs": {}, "history": []}
        try:
            raw = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict):
            if isinstance(raw.get("prefs"), dict):
                self.data["prefs"] = raw["prefs"]
            if isinstance(raw.get("history"), list):
                self.data["history"] = [
                    h for h in raw["history"] if isinstance(h, dict) and isinstance(h.get("file"), str)
                ][: self.MAX_HISTORY]

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def prefs(self) -> dict:
        with self.lock:
            return dict(self.data["prefs"])

    def update_prefs(self, patch: dict) -> dict:
        with self.lock:
            self.data["prefs"].update(patch)
            self._save()
            return dict(self.data["prefs"])

    def add_custom_folder(self, path: str) -> None:
        with self.lock:
            folders = [p for p in self.data["prefs"].get("custom_folders", []) if p != path]
            self.data["prefs"]["custom_folders"] = [path] + folders[:7]
            self.data["prefs"]["folder"] = path
            self._save()

    def add_history(self, item: dict) -> None:
        with self.lock:
            history = [h for h in self.data["history"] if h.get("file") != item["file"]]
            self.data["history"] = [item] + history[: self.MAX_HISTORY - 1]
            self._save()

    def history(self) -> list:
        with self.lock:
            items = [dict(h) for h in self.data["history"]]
        for item in items:
            item["missing"] = not Path(item["file"]).exists()
        return items


class Hub:
    """Fans server events out to every open event stream (one per window)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients: set[queue.Queue] = set()
        self.listeners: list = []  # in-process observers, e.g. the taskbar
        self.ever_connected = False
        self.last_change = time.monotonic()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=5000)
        with self.lock:
            self.clients.add(q)
            self.ever_connected = True
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            self.clients.discard(q)
            self.last_change = time.monotonic()

    def publish(self, event: dict) -> None:
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - an observer must never break a job
                traceback.print_exc()

    def idle_seconds(self) -> float:
        with self.lock:
            return 0.0 if self.clients else time.monotonic() - self.last_change


class Runner:
    """Runs one yt-dlp job at a time (an extraction or a self-update) and streams its output."""

    def __init__(self, hub: Hub, store: Store):
        self.hub = hub
        self.store = store
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.job: dict | None = None
        self.log: collections.deque = collections.deque(maxlen=800)
        self.seq = 0
        self.stop_requested = False
        self.created: list[Path] = []
        self.version: dict = {"version": None, "age_days": None, "found": YTDLP.is_file()}
        self._last_progress = 0.0

    # ---- shared plumbing

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "job": dict(self.job) if self.job else None,
                "log": [{"seq": s, "line": l} for s, l in self.log],
                "version": dict(self.version),
            }

    def emit_log(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        with self.lock:
            self.seq += 1
            seq = self.seq
            self.log.append((seq, line))
        self.hub.publish({"type": "log", "seq": seq, "line": line})

    def notice(self, level: str, code: str, text: str) -> None:
        self.hub.publish({"type": "notice", "level": level, "code": code, "text": text})

    def update_job(self, **changes) -> None:
        with self.lock:
            if self.job is None:
                return
            self.job.update(changes)
            snap = dict(self.job)
        self.hub.publish({"type": "job", "job": snap})

    def busy(self) -> bool:
        with self.lock:
            return bool(self.job and self.job["status"] == "running")

    def _begin(self, job: dict) -> dict:
        with self.lock:
            if self.job and self.job["status"] == "running":
                raise Busy()
            self.job = job
            self.log.clear()
            self.stop_requested = False
            snap = dict(job)
        self.hub.publish({"type": "log-reset"})
        self.hub.publish({"type": "job", "job": snap})
        return snap

    def _stream(self, cmd: list, on_line) -> int:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(APP_DIR),
            env=env,
            creationflags=NO_WINDOW,
        )
        with self.lock:
            self.proc = proc
        assert proc.stdout is not None
        for raw in iter(proc.stdout.readline, b""):
            for part in raw.decode("utf-8", "replace").replace("\r", "\n").split("\n"):
                if part.strip():
                    on_line(part)
        code = proc.wait()
        with self.lock:
            self.proc = None
        return code

    def stop(self) -> bool:
        with self.lock:
            proc = self.proc
            if proc:
                self.stop_requested = True
        if not proc:
            return False
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW
        )
        return True

    def _finish(self, status: str, **extra) -> None:
        self.update_job(status=status, finished=time.time(), **extra)

    # ---- yt-dlp version

    def refresh_version(self) -> None:
        info = {"version": None, "age_days": None, "found": YTDLP.is_file()}
        if info["found"]:
            try:
                out = subprocess.run(
                    [str(YTDLP), "--version"],
                    capture_output=True,
                    timeout=30,
                    cwd=str(APP_DIR),
                    creationflags=NO_WINDOW,
                )
                lines = out.stdout.decode("utf-8", "replace").strip().splitlines()
                version = lines[0].strip() if lines else None
                match = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", version or "")
                if match:
                    released = date(int(match[1]), int(match[2]), int(match[3]))
                    info["age_days"] = (date.today() - released).days
                info["version"] = version
            except (OSError, subprocess.TimeoutExpired, ValueError):
                pass
        with self.lock:
            self.version = info
        self.hub.publish({"type": "version", "version": info})

    # ---- extraction

    def start_extract(self, url: str, fmt: str, folder: Path, cookies: str, filename: str, meta: dict) -> dict:
        job = {
            "id": secrets.token_hex(4),
            "kind": "extract",
            "status": "running",
            "stage": "resolving",
            "url": url,
            "format": fmt,
            "folder": str(folder),
            "title": meta.get("title"),
            "author": meta.get("author"),
            "thumb": meta.get("thumb"),
            "progress": None,
            "downloaded": None,
            "total": None,
            "speed": None,
            "eta": None,
            "file": None,
            "size": None,
            "error": None,
            "detail": None,
            "started": time.time(),
        }
        snap = self._begin(job)
        threading.Thread(
            target=self._run_extract, args=(url, fmt, folder, cookies, filename), daemon=True
        ).start()
        return snap

    def _cookie_args(self, cookies: str) -> list:
        if cookies.startswith("browser:"):
            browser = cookies.split(":", 1)[1]
            if browser in BROWSERS:
                if browser in ("chrome", "edge"):
                    self.emit_log(
                        f"[app] Reading live {browser.title()} cookies. If this fails, close "
                        f"{browser.title()} completely first: it locks its cookie database."
                    )
                return ["--cookies-from-browser", browser]
            return []
        if not cookies.startswith("file:"):
            return []
        name = cookies.split(":", 1)[1]
        path = APP_DIR / name
        if Path(name).name != name or "cookie" not in name.lower() or not path.is_file():
            self.notice("warn", "cookie_missing", f"The cookie file {name} wasn't found, so no cookies were used.")
            return []
        try:
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            data = path.read_text("utf-8", "replace")[:20000]
        except OSError:
            return ["--cookies", str(path)]
        if age_hours > 24:
            days = age_hours / 24
            age = f"{days:.0f} days" if days >= 2 else f"{age_hours:.0f} hours"
            self.notice(
                "warn",
                "cookie_old",
                f"{name} is {age} old. Stale cookies cause 403 errors: re-export it, or use a live browser session.",
            )
        if not any(key in data for key in ("SID", "HSID", "SSID", "LOGIN_INFO", "SAPISID")):
            self.notice(
                "warn",
                "cookie_signed_out",
                f"{name} looks signed out (no YouTube login cookies). Export it while signed in.",
            )
        return ["--cookies", str(path)]

    def _on_extract_line(self, line: str) -> None:
        if line.startswith(PROGRESS_TAG):
            fields = (line[len(PROGRESS_TAG):].split("|") + [""] * 6)[:6]
            downloaded, total, estimate, speed, eta = (to_number(v) for v in fields[:5])
            total = total or estimate
            progress = min(100.0, downloaded / total * 100) if downloaded is not None and total else None
            now = time.monotonic()
            finished = fields[5].strip() == "finished"
            if not finished and now - self._last_progress < 0.08:
                return
            self._last_progress = now
            self.update_job(
                stage="downloading",
                progress=100.0 if finished else progress,
                downloaded=downloaded,
                total=total,
                speed=speed,
                eta=eta,
            )
            return
        if line.startswith("[ExtractAudio]"):
            self.update_job(stage="converting")
        match = DESTINATION.match(line)
        if match:
            self.created.append(Path(match.group(1).strip()))
        self.emit_log(line)

    def _remove_partial_files(self) -> None:
        """After a stop, delete what this run wrote. Only paths yt-dlp announced as new destinations."""
        time.sleep(0.4)  # let the killed process release its file handles
        for path in self.created:
            candidates = [path, path.with_name(path.name + ".part"), path.with_name(path.name + ".ytdl")]
            candidates += list(path.parent.glob(glob_escape(path.name) + ".part-Frag*"))
            for candidate in candidates:
                try:
                    candidate.unlink()
                    self.emit_log(f"[app] Removed partial file {candidate.name}")
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    self.emit_log(f"[app] Couldn't remove {candidate.name}: {exc}")

    def _run_extract(self, url: str, fmt: str, folder: Path, cookies: str, filename: str) -> None:
        if not YTDLP.is_file():
            self._finish("failed", error="ytdlp_missing")
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._finish("failed", error="folder", detail=str(exc))
            return

        self.created = []
        result_dir = Path(tempfile.mkdtemp(prefix="extractor-"))
        result_file = result_dir / "result.txt"
        stem = filename.replace("%", "%%") if filename else "%(title)s"
        cmd = [
            str(YTDLP),
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", fmt,
            "--ffmpeg-location", str(APP_DIR),
            "--no-playlist",
            "--retries", "10",
            "--fragment-retries", "10",
            "--newline",
            "--color", "never",
            "--progress-template",
            "download:" + PROGRESS_TAG + "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
            "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s|%(progress.status)s",
            "--print-to-file", "after_move:filepath", str(result_file),
        ]
        cmd += self._cookie_args(cookies)
        cmd += ["-o", str(folder / f"{stem}.%(ext)s"), "--", url]

        shown = [Path(cmd[0]).name] + [a for a in cmd[1:] if not a.startswith(("download:" + PROGRESS_TAG))]
        self.emit_log("$ " + subprocess.list2cmdline(shown))
        if not FFMPEG.is_file():
            self.emit_log("[app] ffmpeg.exe is not next to the app; converting the audio will fail.")

        try:
            code = self._stream(cmd, self._on_extract_line)
        except OSError as exc:
            shutil.rmtree(result_dir, ignore_errors=True)
            self._finish("failed", error="ytdlp_missing", detail=str(exc))
            return

        saved = None
        try:
            lines = [l.strip() for l in result_file.read_text("utf-8", "replace").splitlines() if l.strip()]
            saved = Path(lines[-1]) if lines else None
        except OSError:
            pass
        shutil.rmtree(result_dir, ignore_errors=True)

        if self.stop_requested:
            self._remove_partial_files()
            self._finish("stopped")
            return
        if code != 0:
            error, detail = self._classify_failure()
            self._finish("failed", error=error, detail=detail)
            return
        if saved is None or not saved.is_file():
            self._finish("done", file=None, size=None, progress=100.0)
            return

        with self.lock:
            job = dict(self.job or {})
        size = saved.stat().st_size
        item = {
            "file": str(saved),
            "title": job.get("title") or saved.stem,
            "author": job.get("author"),
            "thumb": job.get("thumb"),
            "format": saved.suffix.lstrip(".").lower(),
            "size": size,
            "ts": time.time(),
            "url": job.get("url"),
        }
        self.store.add_history(item)
        self.emit_log(f"[app] Saved {saved}")
        self._finish("done", file=str(saved), size=size, progress=100.0, history_item=item)

    def _classify_failure(self) -> tuple[str, str | None]:
        with self.lock:
            lines = [l for _, l in self.log]
        text = "\n".join(lines).lower()
        detail = next((l[6:].strip() for l in reversed(lines) if l.startswith("ERROR:")), None)
        for code, needles in ERROR_PATTERNS:
            if any(n in text for n in needles):
                return code, detail
        return "generic", detail

    # ---- self-update

    def start_update(self) -> dict:
        snap = self._begin(
            {"id": secrets.token_hex(4), "kind": "update", "status": "running", "stage": "updating", "started": time.time()}
        )
        threading.Thread(target=self._run_update, daemon=True).start()
        return snap

    def _run_update(self) -> None:
        before = self.version.get("version")
        code = 1
        try:
            self.emit_log("$ yt-dlp.exe -U")
            code = self._stream([str(YTDLP), "-U"], self.emit_log)
            if code == 0 and not self.stop_requested:
                self.emit_log("$ yt-dlp.exe --rm-cache-dir")
                self._stream([str(YTDLP), "--rm-cache-dir"], self.emit_log)
        except OSError as exc:
            self.emit_log(f"ERROR: {exc}")
        self.refresh_version()
        after = self.version.get("version")
        if self.stop_requested:
            self._finish("stopped")
        elif code == 0:
            text = f"yt-dlp updated to {after}." if after and after != before else f"yt-dlp is up to date ({after})."
            self.notice("ok", "updated", text)
            self._finish("done", version=after)
        else:
            self.notice(
                "error",
                "update_failed",
                "The update failed: no internet, a GitHub rate limit, or yt-dlp.exe is in use. Close other "
                "copies and try again.",
            )
            self._finish("failed")


# --------------------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "Extractor/2"
    sys_version = ""

    @property
    def app(self) -> "App":
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format, *args):  # noqa: A002 - keep the server quiet
        pass

    # ---- responses

    def _common_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str, ctype: str) -> None:
        try:
            body = (UI_DIR / name).read_bytes()
        except OSError:
            self._json(404, {"error": "missing_ui_file"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self._common_headers()
        if name.endswith(".html"):
            self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, payload: dict) -> None:
        self.wfile.write(b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n")

    # ---- request checks

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.app.allowed_hosts

    def _token_ok(self, query: dict) -> bool:
        token = self.headers.get("X-Token") or (query.get("t") or [""])[0]
        return bool(token) and secrets.compare_digest(token, self.app.token)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64 * 1024:
            raise ValueError("body too large")
        data = json.loads(self.rfile.read(length) or b"{}") if length else {}
        if not isinstance(data, dict):
            raise ValueError("body must be an object")
        return data

    def _guard(self, handler) -> None:
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception:  # noqa: BLE001 - never kill the server thread
            traceback.print_exc()
            try:
                self._json(500, {"error": "internal"})
            except OSError:
                pass

    def do_GET(self):  # noqa: N802
        self._guard(self._get)

    def do_POST(self):  # noqa: N802
        self._guard(self._post)

    # ---- routes

    def _get(self) -> None:
        if not self._host_ok():
            self._json(403, {"error": "host"})
            return
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query)
        if parts.path in STATIC:
            self._static(*STATIC[parts.path])
            return
        if parts.path == "/api/hello":
            self._json(200, {"app": APP_ID, "pid": os.getpid()})
            return
        if not self._token_ok(query):
            self._json(401, {"error": "token"})
            return
        if parts.path == "/api/events":
            self._events()
        elif parts.path == "/api/state":
            self._json(200, self.app.state())
        elif parts.path == "/api/thumb":
            self._thumb((query.get("u") or [""])[0])
        else:
            self._json(404, {"error": "not_found"})

    def _thumb(self, url: str) -> None:
        """Same-origin copy of a YouTube thumbnail, so the page can read its colours."""
        if not THUMB_URL.match(url):
            self._json(400, {"error": "bad_thumb"})
            return
        body = self.app.thumbnail(url)
        if body is None:
            self._json(404, {"error": "no_thumb"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _post(self) -> None:
        if not self._host_ok():
            self._json(403, {"error": "host"})
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/reopen":
            # Lets a second launch bring up a window for the running instance. Browsers always
            # send Origin on cross-site POSTs, so refusing any Origin keeps web pages out.
            if self.headers.get("Origin"):
                self._json(403, {"error": "origin"})
                return
            self.app.open_window()
            self._json(200, {"ok": True})
            return
        if not self._token_ok({}):
            self._json(401, {"error": "token"})
            return
        try:
            body = self._body()
        except ValueError:
            self._json(400, {"error": "bad_body"})
            return
        route = {
            "/api/preview": self._preview,
            "/api/extract": self._extract,
            "/api/stop": self._stop,
            "/api/update": self._update,
            "/api/browse": self._browse,
            "/api/open": self._open,
            "/api/prefs": self._prefs,
            "/api/clipboard": self._clipboard,
        }.get(path)
        if route is None:
            self._json(404, {"error": "not_found"})
            return
        route(body)

    def _events(self) -> None:
        hub = self.app.hub
        q = hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self._common_headers()
            self.end_headers()
            self._sse({"type": "hello", **self.app.runner.snapshot()})
            while not self.app.stopping.is_set():
                try:
                    event = q.get(timeout=5)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    continue
                self._sse(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            hub.unsubscribe(q)

    def _preview(self, body: dict) -> None:
        try:
            url = clean_url(body.get("url"))
        except ValueError:
            self._json(400, {"error": "bad_url"})
            return
        self._json(200, self.app.preview(url))

    def _extract(self, body: dict) -> None:
        try:
            url = clean_url(body.get("url"))
        except ValueError:
            self._json(400, {"error": "bad_url"})
            return
        fmt = body.get("format")
        if fmt not in FORMATS:
            self._json(400, {"error": "bad_format"})
            return
        try:
            folder = resolve_folder(body.get("folder"))
        except ValueError:
            self._json(400, {"error": "bad_folder"})
            return
        cookies = body.get("cookies") if isinstance(body.get("cookies"), str) else "none"
        thumb = body.get("thumb")
        if not (isinstance(thumb, str) and thumb.startswith(THUMB_PREFIX) and len(thumb) < 300):
            # Started before the preview loaded: every YouTube video has this one.
            video = youtube_id(url)
            thumb = f"{THUMB_PREFIX}vi/{video}/mqdefault.jpg" if video else None
        meta = {
            "title": short_text(body.get("title"), 300),
            "author": short_text(body.get("author"), 200),
            "thumb": thumb,
        }
        try:
            job = self.app.runner.start_extract(url, fmt, folder, cookies, clean_filename(body.get("filename")), meta)
        except Busy:
            self._json(409, {"error": "busy"})
            return
        if not meta["title"] and youtube_id(url):
            # Started before the page had the title (Enter pressed early): look it up alongside.
            threading.Thread(target=self.app.fill_title, args=(job["id"], url), daemon=True).start()
        prefs = {"format": fmt, "cookies": cookies[:300]}
        if isinstance(body.get("folder"), str):
            prefs["folder"] = body["folder"][:1024]
        self.app.store.update_prefs(prefs)
        self._json(200, {"job": job})

    def _stop(self, body: dict) -> None:
        self._json(200, {"stopped": self.app.runner.stop()})

    def _update(self, body: dict) -> None:
        if not YTDLP.is_file():
            self._json(400, {"error": "ytdlp_missing"})
            return
        try:
            job = self.app.runner.start_update()
        except Busy:
            self._json(409, {"error": "busy"})
            return
        self._json(200, {"job": job})

    def _browse(self, body: dict) -> None:
        initial = body.get("initial") if isinstance(body.get("initial"), str) else ""
        try:
            start = str(resolve_folder(initial))
        except ValueError:
            start = str(APP_DIR)
        if not Path(start).is_dir():
            start = str(APP_DIR)
        path = self.app.pick_folder(start)
        if path:
            inside = Path(path).resolve()
            try:
                relative = inside.relative_to(APP_DIR)
                path = str(relative) if str(relative) != "." else DEFAULT_FOLDER
                self.app.store.update_prefs({"folder": path})
            except ValueError:
                self.app.store.add_custom_folder(path)
        custom = self.app.store.prefs().get("custom_folders", [])
        self._json(200, {"path": path, "folders": list_folders(custom)})

    def _open(self, body: dict) -> None:
        action = body.get("action") if body.get("action") in ("play", "reveal", "folder") else "reveal"
        target = body.get("path")
        if action == "folder" and isinstance(target, str):
            try:
                folder = resolve_folder(target)
                folder.mkdir(parents=True, exist_ok=True)
                target = str(folder)
            except (ValueError, OSError):
                target = None
        self._json(200, {"ok": open_path(target, action)})

    def _prefs(self, body: dict) -> None:
        patch = {}
        if body.get("format") in FORMATS:
            patch["format"] = body["format"]
        if isinstance(body.get("folder"), str) and len(body["folder"]) < 1024:
            patch["folder"] = body["folder"]
        if isinstance(body.get("cookies"), str) and len(body["cookies"]) < 300:
            patch["cookies"] = body["cookies"]
        self._json(200, {"prefs": self.app.store.update_prefs(patch) if patch else self.app.store.prefs()})

    def _clipboard(self, body: dict) -> None:
        try:
            url = clipboard_url()
        except OSError:
            url = None
        self._json(200, {"url": url})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        traceback.print_exc()


# --------------------------------------------------------------------------- app


class App:
    def __init__(self, args: argparse.Namespace):
        self.dev = args.dev
        self.token = args.token or secrets.token_urlsafe(24)
        data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_DATA_DIR
        self.data_dir = data_dir
        self.store = Store(data_dir / "state.json")
        self.hub = Hub()
        self.runner = Runner(self.hub, self.store)
        self.stopping = threading.Event()
        self.preview_cache: dict[str, dict] = {}
        self.preview_lock = threading.Lock()
        self.server: Server | None = None
        self.port = 0
        self.allowed_hosts: set[str] = set()
        self.thumbs: collections.OrderedDict[str, bytes] = collections.OrderedDict()
        self.thumb_lock = threading.Lock()
        # Native window (pywebview) state
        self.webview = None
        self.window = None
        self.hwnd: int | None = None
        self.taskbar: Taskbar | None = None
        self.window_title = APP_NAME
        self.taskbar_shown: tuple | None = None
        self.window_size: dict | None = None
        self.window_maximized = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#t={self.token}"

    def state(self) -> dict:
        prefs = self.store.prefs()
        snap = self.runner.snapshot()
        return {
            "formats": list(FORMATS),
            "folders": list_folders(prefs.get("custom_folders", [])),
            "cookies": list_cookie_sources(),
            "prefs": {
                "format": prefs.get("format", "mp3"),
                "folder": prefs.get("folder", DEFAULT_FOLDER),
                "cookies": prefs.get("cookies", "browser:chrome"),
            },
            "history": self.store.history(),
            "ffmpeg_found": FFMPEG.is_file(),
            "app_version": __version__,
            **snap,
        }

    def fill_title(self, job_id: str, url: str) -> None:
        info = self.preview(url)
        with self.runner.lock:
            job = self.runner.job
            current = bool(job and job.get("id") == job_id and not job.get("title"))
        if current and info.get("title"):
            self.runner.update_job(title=info["title"], author=info.get("author"))

    def thumbnail(self, url: str) -> bytes | None:
        with self.thumb_lock:
            if url in self.thumbs:
                self.thumbs.move_to_end(url)
                return self.thumbs[url]
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                body = response.read(2_000_001)
        except (urllib.error.URLError, OSError, TimeoutError):
            return None
        if len(body) > 2_000_000:
            return None
        with self.thumb_lock:
            self.thumbs[url] = body
            while len(self.thumbs) > 24:
                self.thumbs.popitem(last=False)
        return body

    def pick_folder(self, start: str) -> str | None:
        if self.window is not None:
            try:
                picked = self.window.create_file_dialog(self.webview.FileDialog.FOLDER, directory=start)
            except Exception:  # noqa: BLE001 - a failed dialog just means no folder
                traceback.print_exc()
                return None
            if not picked:
                return None
            path = picked[0] if isinstance(picked, (list, tuple)) else picked
            return os.path.normpath(path)
        return browse_folder(start)

    def preview(self, url: str) -> dict:
        video = youtube_id(url)
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if not video:
            return {"kind": "other", "url": url, "host": host}
        with self.preview_lock:
            cached = self.preview_cache.get(video)
        if cached:
            return dict(cached, url=url)
        title = author = None
        query = urllib.parse.urlencode({"url": f"https://www.youtube.com/watch?v={video}", "format": "json"})
        request = urllib.request.Request(
            f"https://www.youtube.com/oembed?{query}", headers={"User-Agent": "Mozilla/5.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=6) as response:
                data = json.loads(response.read().decode("utf-8"))
            title = short_text(data.get("title"), 300)
            author = short_text(data.get("author_name"), 200)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            pass
        result = {
            "kind": "youtube",
            "url": url,
            "host": "youtube.com",
            "id": video,
            "title": title,
            "author": author,
            "thumb": f"{THUMB_PREFIX}vi/{video}/maxresdefault.jpg",
            "thumb_fallback": f"{THUMB_PREFIX}vi/{video}/mqdefault.jpg",
        }
        if title:
            with self.preview_lock:
                self.preview_cache[video] = result
        return result

    def open_window(self) -> None:
        """Bring up the UI: focus the native window if there is one, else open a browser app window."""
        if self.window is not None:
            try:
                self.window.restore()
                self.window.show()
            except Exception:  # noqa: BLE001
                pass
            if self.hwnd:
                bring_to_front(self.hwnd)
            return
        open_app_window(self.url, self.data_dir / "window")

    # ---- native window

    def run_native_window(self) -> bool:
        """Show the UI in a pywebview window and block until it is closed. False without pywebview."""
        try:
            import webview
        except ImportError:
            return False
        self.webview = webview
        saved = self.store.prefs().get("window")
        saved = saved if isinstance(saved, dict) else {}

        def dimension(key: str, default: int, low: int, high: int) -> int:
            value = saved.get(key)
            return min(high, max(low, value)) if isinstance(value, int) else default

        if os.name == "nt" and not getattr(sys, "frozen", False):
            # From source the process is python.exe; give the window its own taskbar identity.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Extractor.App")
        self.window = webview.create_window(
            APP_NAME,
            self.url,
            width=dimension("width", 1120, 860, 3800),
            height=dimension("height", 780, 620, 2400),
            min_size=(860, 620),
            maximized=bool(saved.get("maximized")),
            background_color=WINDOW_BG,
        )
        self.window.events.shown += self._on_shown
        self.window.events.resized += self._on_resized
        self.hub.listeners.append(self._on_event)
        webview.start(icon=str(ICON) if ICON.is_file() else None, private_mode=True)
        if self.window_size:
            self.store.update_prefs({"window": {**self.window_size, "maximized": self.window_maximized}})
        return True

    def _on_shown(self) -> None:
        hwnd = find_own_window(APP_NAME)
        if not hwnd:
            return
        self.hwnd = hwnd
        try:
            style_title_bar(hwnd)
        except OSError:
            pass
        self.taskbar = Taskbar()
        self.taskbar.hwnd = hwnd

    def _on_resized(self, width: int, height: int) -> None:
        if not self.hwnd:
            return
        user32 = ctypes.WinDLL("user32")
        if user32.IsIconic(ctypes.c_void_p(self.hwnd)):
            return
        self.window_maximized = bool(user32.IsZoomed(ctypes.c_void_p(self.hwnd)))
        if not self.window_maximized:
            self.window_size = {"width": width, "height": height}

    def _set_title(self, text: str) -> None:
        if text != self.window_title and self.window is not None:
            self.window_title = text
            self.window.set_title(text)

    def _show_progress(self, state: int, percent: float | None = None) -> None:
        shown = (state, None if percent is None else int(percent))
        if self.taskbar and shown != self.taskbar_shown:
            self.taskbar_shown = shown
            self.taskbar.show(state, percent)

    def _on_event(self, event: dict) -> None:
        """Mirror job progress on the taskbar button and the window title."""
        if event.get("type") != "job" or not self.hwnd:
            return
        job = event["job"]
        status = job.get("status")
        if job.get("kind") != "extract":
            self._show_progress(Taskbar.INDETERMINATE if status == "running" else Taskbar.NONE)
            return
        if status == "running":
            progress = job.get("progress")
            if job.get("stage") == "downloading" and progress is not None:
                self._show_progress(Taskbar.NORMAL, progress)
                self._set_title(f"{int(progress)}% · {APP_NAME}")
            else:
                self._show_progress(Taskbar.INDETERMINATE)
                self._set_title(f"Converting · {APP_NAME}" if job.get("stage") == "converting" else APP_NAME)
            return
        self._set_title(APP_NAME)
        if status == "failed":
            self._show_progress(Taskbar.ERROR, 100)
            threading.Timer(5, lambda: None if self.runner.busy() else self._show_progress(Taskbar.NONE)).start()
        else:
            self._show_progress(Taskbar.NONE)
        if status in ("done", "failed"):
            flash_if_inactive(self.hwnd)

    def watchdog(self) -> None:
        """Exit once no window has been connected for a while (the user closed it)."""
        while not self.stopping.wait(2):
            limit = 12 if self.hub.ever_connected else 120
            if self.hub.idle_seconds() > limit:
                self.shutdown()
                return

    def shutdown(self) -> None:
        if self.stopping.is_set():
            return
        self.stopping.set()
        self.runner.stop()
        if self.server:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def find_browser() -> Path | None:
    roots = [os.environ.get(k) for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for root in roots:
            if root and (Path(root) / relative).is_file():
                return Path(root) / relative
    return None


def open_app_window(url: str, profile: Path) -> None:
    browser = find_browser()
    if browser:
        try:
            subprocess.Popen(
                [
                    str(browser),
                    f"--app={url}",
                    f"--user-data-dir={profile}",
                    "--window-size=1120,780",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                creationflags=NO_WINDOW,
            )
            return
        except OSError:
            pass
    webbrowser.open(url)


def running_instance(port: int) -> int | None:
    """The process id of an Extractor already serving on this port, if any."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hello", timeout=0.8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    return int(data.get("pid") or 0) if data.get("app") == APP_ID else None


def main() -> None:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {__version__}: save audio from video links")
    parser.add_argument("--dev", action="store_true", help="serve only: no window, no idle shutdown")
    parser.add_argument("--browser", action="store_true", help="use an Edge/Chrome app window, not the native one")
    parser.add_argument("--port", type=int, default=0, help=f"port to serve on (default {PREFERRED_PORT})")
    parser.add_argument("--token", default="", help="fixed API token (dev only)")
    parser.add_argument("--data-dir", default="", help="where to keep prefs and history")
    args = parser.parse_args()

    app = App(args)
    app.data_dir.mkdir(parents=True, exist_ok=True)
    if sys.stderr is None or sys.stdout is None:  # pythonw: keep errors in a log file
        stream = open(app.data_dir / "app.log", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream

    port = args.port or PREFERRED_PORT
    existing = None if args.dev else running_instance(port)
    if existing is not None:
        if existing and os.name == "nt":
            ctypes.windll.user32.AllowSetForegroundWindow(existing)  # let it come to the front
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/reopen", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(request, timeout=3).close()
            return
        except OSError:
            pass

    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError:
        if args.port:
            raise
        server = Server(("127.0.0.1", 0), Handler)
    server.app = app  # type: ignore[attr-defined]
    app.server = server
    app.port = server.server_address[1]
    app.allowed_hosts = {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}

    threading.Thread(target=app.runner.refresh_version, daemon=True).start()
    print(f"{APP_NAME} {__version__} running at {app.url}", flush=True)
    if args.dev:
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            app.stopping.set()
            app.runner.stop()
            server.server_close()
        return

    serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    serving.start()
    try:
        # The native window blocks until it is closed. Without pywebview, open a browser
        # app window instead and stay alive until no window has been connected for a while.
        if args.browser or not app.run_native_window():
            app.open_window()
            app.watchdog()
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
        serving.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    main()
