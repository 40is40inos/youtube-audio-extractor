# YouTube Audio Extractor

A small Windows desktop app (Python + Tkinter) that wraps [yt-dlp](https://github.com/yt-dlp/yt-dlp) and
[ffmpeg](https://ffmpeg.org/) to save the audio of a YouTube video as a file.

## Features

- Paste a link, pick a save folder and a format (`mp3`, `opus`, `m4a`, `flac`, `wav`, `aac`, or `best`), click
  **Extract**.
- Optional custom filename (defaults to the video title).
- Cookies from your browser (Chrome, Firefox, Edge, Brave) or from an exported `cookies.txt`, for videos that need a
  signed-in session. Warns when a cookie file is old or looks signed-out.
- Live log of yt-dlp's output, a **Stop** button, and an **Update yt-dlp** button (`yt-dlp -U` plus
  `--rm-cache-dir`). Warns on startup when yt-dlp is more than 60 days old, since old versions start failing with
  HTTP 403.
- Hints for the common 403 fixes when an extraction fails.

## Setup

1. Install Python 3.10+ (Tkinter is included with the standard Windows installer).
2. Put these executables in the same folder as `audio_extractor_gui.py` (they are not in this repo):
   - `yt-dlp.exe` from [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases)
   - `ffmpeg.exe` and `ffprobe.exe` from an [ffmpeg Windows build](https://ffmpeg.org/download.html#build-windows)
3. Double-click `Launch_Extractor_GUI.bat` (runs the app with `pythonw`, so no console window).

Files are saved under the chosen folder next to the script (`YoutubeExtracts` by default). Any subfolder there shows
up in the folder list automatically, and any `*.txt` file with "cookie" in its name shows up in the cookies list.

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
