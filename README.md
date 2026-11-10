# Extractor

A small Windows desktop app that saves the audio of a YouTube video as a file. It wraps
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/) in an interface built around a
turntable:

- Paste a link and the video's thumbnail becomes the record label. The deck behind it picks up the artwork's colours.
- Press **Extract**: the platter spins up, the tonearm drops onto the record and tracks the download from the outer
  groove inwards. A ring around the platter shows the exact progress, and the window title shows the percentage.
- When the file is saved, the record spins down, the arm parks, and the track drops into **Recent**, with buttons to
  play it or show it in its folder.

## Features

- Formats: `mp3`, `opus`, `m4a`, `flac`, `wav`, `aac`, or `best` (no conversion). A one-line hint explains each one.
- Save to any subfolder of the app folder, or pick another folder with **Browse**.
- Cookies from a browser (Chrome, Firefox, Edge, Brave) or from an exported `cookies.txt`, for videos that need a
  signed-in session. Warns when a cookie file is old or looks signed out.
- Optional custom file name.
- Spots a YouTube link in your clipboard and offers to use it. **Ctrl+V** anywhere pastes into the link field and
  **Enter** starts the extraction.
- Failures are explained in plain language (HTTP 403, sign-in required, unreadable browser cookies, unavailable video,
  missing ffmpeg). The full yt-dlp output is in the **Log** drawer.
- Shows the yt-dlp version, warns when it is more than 60 days old, and updates it in place (`yt-dlp -U` plus
  `--rm-cache-dir`).
- Remembers your format, folder and cookie choices and your recent extractions.
- Respects Windows' "reduce motion" setting: the record stops spinning and transitions become simple fades.

## Setup

1. Install Python 3.10+ (the standard Windows installer is enough; nothing else is needed from pip).
2. Put these executables in this folder (they are not in the repo):
   - `yt-dlp.exe` from [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases)
   - `ffmpeg.exe` and `ffprobe.exe` from an [ffmpeg Windows build](https://ffmpeg.org/download.html#build-windows)
3. Double-click `Launch_Extractor_GUI.bat`.

## How it works

`app.py` runs a small web server on `127.0.0.1` (Python standard library only) and opens the interface in `ui/` as a
frameless Microsoft Edge app window (Chrome is used if Edge isn't found, then the default browser). The server runs
yt-dlp, streams its progress to the window, and shuts itself down a few seconds after the window is closed. Launching
again while it's running just opens another window.

- The server only accepts requests from this machine that carry a random per-launch token, so web pages can't drive it.
- Preferences and the recent list are kept in `%LOCALAPPDATA%\YouTubeAudioExtractor\state.json`; the app window's
  browser profile lives next to it.
- For development, `python app.py --dev --port 47380 --token devtoken` serves the UI without opening a window or
  shutting down; open `http://127.0.0.1:47380/#t=devtoken`.

The previous Tkinter interface is still here as `audio_extractor_gui.py` (`pythonw audio_extractor_gui.py`).

## Command-line version

`rip.sh` is a minimal loop for Git Bash: paste a link, it saves the audio as `opus` into `YoutubeExtracts/` using
`youtube_cookies.txt`.

```bash
bash rip.sh
```

Batch-convert a folder of `.opus` files to 320 kbps MP3:

```bash
mkdir -p MP3 && for f in SomeFolder/*.opus; do ./ffmpeg.exe -i "$f" -vn -c:a libmp3lame -b:a 320k "MP3/$(basename "${f%.*}.mp3")"; done
```

## Notes

- Cookie files are session credentials for your Google account. Keep them private; `.gitignore` excludes them.
- Only download content you have the right to save.
