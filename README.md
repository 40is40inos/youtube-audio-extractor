# Extractor

A small Windows desktop app that saves the audio of a YouTube video as a file. It wraps
[yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org/) in an interface built around a
turntable:

- Paste a link and the video's thumbnail becomes the record label. The deck behind it picks up the artwork's colours,
  and the app's accent colour (button, progress ring, highlights) is taken from the artwork too, so every track gets its
  own palette. Greyscale or dark artwork keeps the brand lime.
- Press **Extract**: the platter spins up, the tonearm drops onto the record and tracks the download from the outer
  groove inwards. A ring around the platter shows the exact progress; the taskbar button fills like any Windows
  download and the window title shows the percentage.
- When the file is saved, the record spins down, the arm parks, and the track drops into **Recent**, with buttons to
  play it or show it in its folder. If the window is in the background, its taskbar button flashes.

It runs as a native Windows app (`Extractor.exe`) with its own icon, a dark title bar, a Start menu entry and an
uninstaller in Settings > Apps.

## Download

For Windows 10 and 11 (64-bit).

1. Download `Extractor-<version>-win64.zip` from the [latest release](https://github.com/40is40inos/youtube-audio-extractor/releases/latest).
2. Extract it (right-click > **Extract All**) and double-click **Install Extractor.bat**. The app isn't code-signed,
   so Windows may warn that it comes from the internet or is unrecognised: choose **More info > Run anyway**.
3. Extractor opens. Press **Download tools** once. It fetches [yt-dlp](https://github.com/yt-dlp/yt-dlp) and
   [FFmpeg](https://github.com/yt-dlp/FFmpeg-Builds) (about 115 MB) from their official GitHub releases and checks each
   against its published SHA-256 before using it.

It installs for your Windows user only (no administrator rights), to `%LOCALAPPDATA%\Programs\Extractor`, with Start
menu and desktop shortcuts. Audio goes to `Music\Extractor` unless you pick another folder. To try it without
installing, run `Extractor\Extractor.exe` from the extracted folder.

To remove it, use Settings > Apps > Installed apps > Extractor > Uninstall. That also deletes the downloaded tools;
your music is never touched, and preferences stay in `%LOCALAPPDATA%\YouTubeAudioExtractor` (delete that folder to
forget them).

## Features

- Formats: `mp3`, `opus`, `m4a`, `flac`, `wav`, `aac`, or `best` (no conversion). A one-line hint explains each one.
- Save to `Music\Extractor` or another folder in your Music library (from source: any subfolder of the home folder,
  and the folders inside `YoutubeExtracts`), or pick any folder with **Browse**.
- Cookies from a browser (Chrome, Firefox, Edge, Brave) or from an exported `cookies.txt` (put it in
  `Music\Extractor`, or in the home folder when running from source), for videos that need a signed-in session. Warns
  when a cookie file is old or looks signed out.
- Optional custom file name.
- Spots a YouTube link in your clipboard and offers to use it. **Ctrl+V** anywhere pastes into the link field and
  **Enter** starts the extraction.
- Failures are explained in plain language (HTTP 403, sign-in required, unreadable browser cookies, unavailable video,
  missing ffmpeg). The full yt-dlp output is in the **Log** drawer.
- Shows the yt-dlp version, warns when it is more than 60 days old, and updates it in place (`yt-dlp -U` plus
  `--rm-cache-dir`).
- Remembers your format, folder and cookie choices, your recent extractions, and the window size.
- One instance at a time: launching it again brings the open window to the front.
- Respects Windows' "reduce motion" setting: the record stops spinning and transitions become simple fades.

## Where things go

- **Downloaded release:** music goes to `Music\Extractor`; yt-dlp and FFmpeg live in
  `%LOCALAPPDATA%\YouTubeAudioExtractor\tools`, where **Download tools** puts them and **Update yt-dlp** updates them.
- **From source:** this folder is Extractor's *home*. It holds the music folders (`YoutubeExtracts` by default) and
  cookie files, and you can put `yt-dlp.exe`, `ffmpeg.exe` and `ffprobe.exe` here yourself (they are not in the repo).
  If they are missing, **Download tools** fetches them into the data folder above instead.

## Build and install from source

1. Install Python 3.10+, then build the app (this creates a private `.venv` here, so your Python stays clean):

   ```bash
   python -m venv .venv
   .venv\Scripts\python -m pip install pywebview pyinstaller
   .venv\Scripts\python build.py
   ```

   This writes `dist\Extractor\Extractor.exe` and the release zip `dist\Extractor-<version>-win64.zip`.

2. Double-click **Install Extractor.bat**. Installed from a checkout, the app keeps this folder as its home (the
   installer records it in `home.json` next to `Extractor.exe`). Run it again after rebuilding to update in place.

To publish a release, attach the zip to a GitHub release:

```bash
gh release create v<version> dist/Extractor-<version>-win64.zip --title "Extractor <version>" --notes "…"
```

## Run from source

Double-click `Launch_Extractor_GUI.bat`. It uses the `.venv` (native window) when it exists, otherwise plain Python,
which shows the interface in a frameless Edge app window instead.

## How it works

`app.py` runs a small web server on `127.0.0.1` that drives yt-dlp and streams its progress, and shows the interface in
`ui/` in a native window (pywebview on Microsoft's WebView2, which is part of Windows 11). Closing the window quits
the app. `build.py` packages all of it, with the icon (`ui/extractor.ico`, drawn by `tools/make_icon.py`) and version
details, into `dist\Extractor\Extractor.exe` with PyInstaller.

- The server only accepts requests from this machine that carry a random per-launch token, so web pages can't drive it.
- Preferences and the recent list are kept in `%LOCALAPPDATA%\YouTubeAudioExtractor\state.json`.
- For development, `python app.py --dev --port 47380 --token devtoken` serves the UI without opening a window or
  shutting down; open `http://127.0.0.1:47380/#t=devtoken`. `--browser` forces the Edge app window. To see what a
  downloaded copy does on first run, add `--data-dir <empty folder> --music-dir <empty folder>`.
- The version lives in `app.py` (`__version__`); it is shown on hover over the logo and in the exe's Properties.

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
