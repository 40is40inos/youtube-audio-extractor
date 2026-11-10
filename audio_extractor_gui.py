import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Set high-DPI scaling on Windows if supported
try:
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

class AudioExtractorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Audio Extractor")
        self.root.geometry("750x640")
        self.root.minsize(650, 500)
        
        # Get directory where script is running
        if getattr(sys, 'frozen', False):
            self.script_dir = os.path.dirname(sys.executable)
        else:
            self.script_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.current_process = None
        self.is_downloading = False
        self.is_updating = False
        
        # Style definition - Catppuccin Mocha-inspired Theme
        self.BG_COLOR = "#1e1e2e"
        self.SURFACE_COLOR = "#252538"
        self.TEXT_COLOR = "#cdd6f4"
        self.MUTED_TEXT = "#a6adc8"
        self.ACCENT_BLUE = "#89b4fa"
        self.ACCENT_GREEN = "#a6e3a1"
        self.ACCENT_RED = "#f38ba8"
        self.TERMINAL_BG = "#11111b"
        self.TERMINAL_FG = "#a6e3a1"
        self.BORDER_COLOR = "#313244"
        
        self.root.configure(bg=self.BG_COLOR)
        self.setup_styles()
        self.create_widgets()
        self.auto_detect_options()
        # Auto-check yt-dlp age on startup (background, non-blocking).
        # Never auto-updates - only warns. Manual update via UPDATE button.
        try:
            threading.Thread(target=self.update_worker, args=(True,), daemon=True).start()
        except Exception:
            pass
        
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Configure frames
        self.style.configure("TFrame", background=self.BG_COLOR)
        
        # Configure labels
        self.style.configure("TLabel", background=self.BG_COLOR, foreground=self.TEXT_COLOR, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background=self.BG_COLOR, foreground=self.ACCENT_BLUE, font=("Segoe UI Semibold", 16, "bold"))
        self.style.configure("Muted.TLabel", background=self.BG_COLOR, foreground=self.MUTED_TEXT, font=("Segoe UI", 9))
        
        # Configure combobox
        self.style.configure("TCombobox", 
                             background=self.SURFACE_COLOR, 
                             foreground=self.TEXT_COLOR, 
                             fieldbackground=self.SURFACE_COLOR, 
                             bordercolor=self.BORDER_COLOR,
                             arrowcolor=self.TEXT_COLOR)
        self.style.map("TCombobox", 
                       fieldbackground=[('readonly', self.SURFACE_COLOR)],
                       foreground=[('readonly', self.TEXT_COLOR)])
                       
    def create_widgets(self):
        # Main container with padding
        main_container = ttk.Frame(self.root, padding=20)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # 1. Header Frame
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        header_label = ttk.Label(header_frame, text="YOUTUBE AUDIO EXTRACTOR", style="Header.TLabel")
        header_label.pack(side=tk.LEFT)
        
        subtitle_label = ttk.Label(header_frame, text="High-Fidelity Audio Extraction", style="Muted.TLabel")
        subtitle_label.pack(side=tk.LEFT, padx=15, pady=(5, 0))
        
        # Divider line
        divider = tk.Frame(main_container, height=2, bg=self.BORDER_COLOR)
        divider.pack(fill=tk.X, pady=(0, 15))
        
        # 2. Input Frame (URL)
        input_frame = ttk.Frame(main_container)
        input_frame.pack(fill=tk.X, pady=(0, 15))
        
        url_label = ttk.Label(input_frame, text="YouTube URL / Link:", font=("Segoe UI Semibold", 10))
        url_label.pack(anchor=tk.W, pady=(0, 5))
        
        # Custom-styled URL Entry
        entry_container = tk.Frame(input_frame, bg=self.BORDER_COLOR, bd=1)
        entry_container.pack(fill=tk.X, ipady=1)
        
        self.url_entry = tk.Entry(
            entry_container, 
            bg=self.SURFACE_COLOR, 
            fg=self.TEXT_COLOR, 
            insertbackground=self.TEXT_COLOR,
            relief="flat", 
            font=("Segoe UI", 11),
            bd=0
        )
        self.url_entry.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=8, pady=5)
        
        # Helper buttons for link input
        btn_frame = ttk.Frame(input_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.paste_btn = self.create_custom_button(btn_frame, "Paste Link", self.paste_from_clipboard, self.SURFACE_COLOR, self.ACCENT_BLUE)
        self.paste_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.clear_btn = self.create_custom_button(btn_frame, "Clear", self.clear_url, self.SURFACE_COLOR, self.ACCENT_RED)
        self.clear_btn.pack(side=tk.LEFT)
        
        # 2b. Filename Frame (Optional Custom Name)
        filename_frame = ttk.Frame(main_container)
        filename_frame.pack(fill=tk.X, pady=(0, 15))
        
        filename_label = ttk.Label(filename_frame, text="Custom Filename (optional - leave blank for video title):", font=("Segoe UI Semibold", 10))
        filename_label.pack(anchor=tk.W, pady=(0, 5))
        
        filename_entry_container = tk.Frame(filename_frame, bg=self.BORDER_COLOR, bd=1)
        filename_entry_container.pack(fill=tk.X, ipady=1)
        
        self.filename_entry = tk.Entry(
            filename_entry_container, 
            bg=self.SURFACE_COLOR, 
            fg=self.TEXT_COLOR, 
            insertbackground=self.TEXT_COLOR,
            relief="flat", 
            font=("Segoe UI", 11),
            bd=0
        )
        self.filename_entry.pack(fill=tk.X, expand=True, padx=8, pady=5)
        
        # 3. Settings Grid Frame
        settings_frame = ttk.Frame(main_container)
        settings_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Column weights
        settings_frame.columnconfigure(0, weight=1)
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(2, weight=1)
        
        # Destination Folder selection
        folder_subframe = ttk.Frame(settings_frame)
        folder_subframe.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        folder_label = ttk.Label(folder_subframe, text="Save Folder:", font=("Segoe UI Semibold", 10))
        folder_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.folder_combobox = ttk.Combobox(folder_subframe, style="TCombobox")
        self.folder_combobox.pack(fill=tk.X, side=tk.LEFT, expand=True, ipady=3)
        
        self.browse_btn = self.create_custom_button(folder_subframe, "Browse...", self.browse_folder, self.SURFACE_COLOR, self.TEXT_COLOR)
        self.browse_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # Format selection
        format_subframe = ttk.Frame(settings_frame)
        format_subframe.grid(row=0, column=1, sticky="ew", padx=(5, 5))
        
        format_label = ttk.Label(format_subframe, text="Audio Format:", font=("Segoe UI Semibold", 10))
        format_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.format_combobox = ttk.Combobox(format_subframe, state="readonly", style="TCombobox")
        self.format_combobox.pack(fill=tk.X, ipady=3)
        self.format_combobox['values'] = ("opus", "mp3", "m4a", "flac", "wav", "aac", "best")
        self.format_combobox.set("mp3")
        
        # Cookies selection
        cookies_subframe = ttk.Frame(settings_frame)
        cookies_subframe.grid(row=0, column=2, sticky="ew", padx=(10, 0))
        
        cookies_label = ttk.Label(cookies_subframe, text="Cookies file:", font=("Segoe UI Semibold", 10))
        cookies_label.pack(anchor=tk.W, pady=(0, 5))
        
        self.cookies_combobox = ttk.Combobox(cookies_subframe, state="readonly", style="TCombobox")
        self.cookies_combobox.pack(fill=tk.X, ipady=3)
        
        # 4. Action Buttons
        actions_frame = ttk.Frame(main_container)
        actions_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.extract_btn = self.create_custom_button(
            actions_frame, 
            "EXTRACT TO AUDIO FILE", 
            self.start_extraction, 
            self.ACCENT_GREEN, 
            self.BG_COLOR, 
            font=("Segoe UI Semibold", 11, "bold"),
            height=35
        )
        self.extract_btn.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0, 5))
        
        self.stop_btn = self.create_custom_button(
            actions_frame, 
            "STOP", 
            self.stop_extraction, 
            self.ACCENT_RED, 
            self.BG_COLOR, 
            font=("Segoe UI Semibold", 11, "bold"),
            height=35,
            width=10
        )
        self.stop_btn.pack(side=tk.LEFT)
        self.set_button_state(self.stop_btn, False)

        self.update_btn = self.create_custom_button(
            actions_frame,
            "UPDATE YT-DLP",
            self.start_update,
            self.ACCENT_BLUE,
            self.BG_COLOR,
            font=("Segoe UI Semibold", 11, "bold"),
            height=35,
            width=16
        )
        self.update_btn.pack(side=tk.LEFT, padx=(5, 0))
        
        # 5. Output Console
        console_frame = ttk.Frame(main_container)
        console_frame.pack(fill=tk.BOTH, expand=True)
        
        console_label = ttk.Label(console_frame, text="Extraction Log:", font=("Segoe UI Semibold", 10))
        console_label.pack(anchor=tk.W, pady=(0, 5))
        
        # ScrolledText console
        self.log_text = scrolledtext.ScrolledText(
            console_frame,
            bg=self.TERMINAL_BG,
            fg=self.TERMINAL_FG,
            insertbackground=self.TEXT_COLOR,
            font=("Consolas", 10),
            relief="flat",
            bd=1
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)
        
        # 6. Status bar
        self.status_bar = tk.Label(
            self.root, 
            text="Ready", 
            bg=self.SURFACE_COLOR, 
            fg=self.MUTED_TEXT, 
            anchor=tk.W, 
            padx=15, 
            pady=5,
            font=("Segoe UI", 9)
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
    def create_custom_button(self, parent, text, command, bg_color, fg_color, font=("Segoe UI", 9, "bold"), height=25, width=None):
        # A helper to create custom flat Tkinter buttons with hover effect and clean border
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg_color,
            fg=fg_color,
            activebackground=fg_color,
            activeforeground=bg_color,
            font=font,
            relief="solid",
            bd=1,
            highlightthickness=0,
            cursor="hand2",
            padx=12,
            width=width
        )
        
        # Bind hover effects
        def on_enter(e):
            if btn['state'] != tk.DISABLED:
                # slightly lighter color on hover
                btn.config(bg=self.lighten_color(bg_color, 0.15))
                
        def on_leave(e):
            if btn['state'] != tk.DISABLED:
                btn.config(bg=bg_color)
                
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        
        # Save color references to restore after disabling
        btn.orig_bg = bg_color
        btn.orig_fg = fg_color
        
        return btn
        
    def set_button_state(self, btn, enabled):
        if enabled:
            btn.config(state=tk.NORMAL, bg=btn.orig_bg, fg=btn.orig_fg, cursor="hand2")
        else:
            btn.config(state=tk.DISABLED, bg=self.SURFACE_COLOR, fg=self.MUTED_TEXT, cursor="arrow")
            
    def lighten_color(self, hex_color, factor=0.15):
        # Lightens a hex color code
        try:
            hex_color = hex_color.lstrip('#')
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            new_rgb = tuple(min(255, int(c + (255 - c) * factor)) for c in rgb)
            return '#{:02x}{:02x}{:02x}'.format(*new_rgb)
        except Exception:
            return hex_color
            
    def paste_from_clipboard(self):
        try:
            clipboard = self.root.clipboard_get()
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, clipboard.strip())
        except tk.TclError:
            self.log_message("Clipboard is empty or doesn't contain text.\n")
            
    def clear_url(self):
        self.url_entry.delete(0, tk.END)
        self.filename_entry.delete(0, tk.END)
        
    def browse_folder(self):
        selected = filedialog.askdirectory(initialdir=self.script_dir, title="Select Destination Folder")
        if selected:
            # Check if selected folder is within script_dir, and if so make it relative
            norm_selected = os.path.normpath(selected)
            norm_script = os.path.normpath(self.script_dir)
            
            if norm_selected.startswith(norm_script):
                rel = os.path.relpath(norm_selected, norm_script)
                if rel == ".":
                    rel = ""
                self.folder_combobox.set(rel if rel else "YoutubeExtracts")
            else:
                self.folder_combobox.set(norm_selected)
                
    def auto_detect_options(self):
        # 1. Detect subdirectories
        subdirs = ["YoutubeExtracts", "Downloads", "Dukys"]
        try:
            for item in os.listdir(self.script_dir):
                item_path = os.path.join(self.script_dir, item)
                if os.path.isdir(item_path) and not item.startswith('.') and item not in ["__pycache__", "temp"]:
                    if item not in subdirs:
                        subdirs.append(item)
        except Exception:
            pass
            
        self.folder_combobox['values'] = subdirs
        # Default to YoutubeExtracts (or first found, or make YoutubeExtracts default)
        if "YoutubeExtracts" in subdirs:
            self.folder_combobox.set("YoutubeExtracts")
        elif subdirs:
            self.folder_combobox.set(subdirs[0])
        else:
            self.folder_combobox.set("YoutubeExtracts")
            
        # 2. Detect cookies (file-based) and offer direct browser-cookie options.
        # Browser options are listed first since they read your live, logged-in
        # session and don't go stale the way an exported cookies.txt does.
        cookie_files = ["None", "Browser: Chrome", "Browser: Firefox", "Browser: Edge", "Browser: Brave"]
        try:
            for item in os.listdir(self.script_dir):
                if os.path.isfile(os.path.join(self.script_dir, item)) and item.endswith(".txt") and "cookie" in item.lower():
                    cookie_files.append(item)
        except Exception:
            pass
            
        self.cookies_combobox['values'] = cookie_files
        
        # Default to reading live from Chrome - more reliable than a static export
        self.cookies_combobox.set("Browser: Chrome")
            
    def log_message(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        
    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        
    def update_status(self, text, color=None):
        if color:
            self.status_bar.config(text=text, fg=color)
        else:
            self.status_bar.config(text=text, fg=self.MUTED_TEXT)
            
    def start_extraction(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Input Required", "Please enter a valid YouTube link.")
            return
            
        if not (url.startswith("http://") or url.startswith("https://") or "youtube.com" in url or "youtu.be" in url or "y2u.be" in url):
            messagebox.showwarning("Invalid URL", "Please enter a valid HTTP/HTTPS link (e.g. YouTube URL).")
            return
            
        folder = self.folder_combobox.get().strip()
        if not folder:
            folder = "YoutubeExtracts"
            
        audio_format = self.format_combobox.get()
        cookies = self.cookies_combobox.get()
        custom_name = self.filename_entry.get().strip()
        
        # Verify yt-dlp.exe exists
        ytdlp_path = os.path.join(self.script_dir, "yt-dlp.exe")
        if not os.path.isfile(ytdlp_path):
            messagebox.showerror("Error", f"yt-dlp.exe was not found in the application directory:\n{self.script_dir}")
            return
            
        # Start download thread
        self.is_downloading = True
        self.clear_log()
        self.set_button_state(self.extract_btn, False)
        self.set_button_state(self.update_btn, False)
        self.set_button_state(self.stop_btn, True)
        self.update_status("Downloading & Extracting Audio...", self.ACCENT_BLUE)
        
        download_thread = threading.Thread(
            target=self.extraction_worker, 
            args=(url, folder, audio_format, cookies, custom_name),
            daemon=True
        )
        download_thread.start()
        
    def stop_extraction(self):
        if self.current_process and (self.is_downloading or self.is_updating):
            reply = messagebox.askyesno("Confirm Stop", "Are you sure you want to abort the current process?")
            if reply:
                self.log_message("\n[UI] Attempting to stop process...\n")
                try:
                    # On Windows, taskkill is standard and extremely reliable to terminate process trees
                    subprocess.run(f"taskkill /F /T /PID {self.current_process.pid}", shell=True, capture_output=True)
                except Exception as e:
                    self.log_message(f"[UI] Error while stopping: {e}\n")
                    try:
                        self.current_process.kill()
                    except Exception:
                        pass
                self.is_downloading = False
                self.is_updating = False

    def _get_ytdlp_version(self):
        # Returns (version_str, age_days or None). Never raises.
        try:
            ytdlp_path = os.path.join(self.script_dir, "yt-dlp.exe")
            out = subprocess.run(
                [ytdlp_path, "--version"],
                capture_output=True, text=True, timeout=15, cwd=self.script_dir
            ).stdout.strip().splitlines()
            ver = out[0].strip() if out else "unknown"
            import re as _re
            from datetime import date as _date
            m = _re.search(r"(\d{4})\.(\d{2})\.(\d{2})", ver)
            if m:
                vdate = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                return ver, (_date.today() - vdate).days
            return ver, None
        except Exception:
            return "unknown", None

    def _stream_cmd_to_log(self, cmd):
        # Runs cmd, streams stdout/stderr line-by-line to the log. Returns exit code.
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.script_dir,
            text=True,
            encoding='utf-8',
            errors='replace',
            startupinfo=startupinfo
        )
        while True:
            line = self.current_process.stdout.readline()
            if not line:
                break
            self.root.after(0, lambda l=line: self.log_message(l))
        return self.current_process.wait()

    def start_update(self):
        if self.is_downloading:
            messagebox.showwarning("Busy", "An extraction is running. Stop it before updating.")
            return
        if self.is_updating:
            return
        self.is_updating = True
        self.set_button_state(self.extract_btn, False)
        self.set_button_state(self.update_btn, False)
        self.set_button_state(self.stop_btn, True)
        self.update_status("Updating yt-dlp...", self.ACCENT_BLUE)
        threading.Thread(target=self.update_worker, args=(False,), daemon=True).start()

    def update_worker(self, auto=False):
        ytdlp_path = os.path.join(self.script_dir, "yt-dlp.exe")
        if not os.path.isfile(ytdlp_path):
            self.root.after(0, lambda: self.on_update_complete(1, auto, "yt-dlp.exe not found."))
            return
        ver, age = self._get_ytdlp_version()
        if auto:
            # Silent when fresh; warn only when stale so startup stays clean.
            if age is None:
                self.root.after(0, lambda: self.update_status(f"yt-dlp {ver}", None))
            elif age > 60:
                self.root.after(0, lambda a=age, v=ver: (
                    self.log_message(
                        f"[Update] yt-dlp {v} is {a} days old. Click UPDATE YT-DLP "
                        f"(runs: yt-dlp.exe -U + --rm-cache-dir).\n"),
                    self.update_status(f"yt-dlp {v} outdated ({a}d) - click UPDATE", self.ACCENT_RED)
                ))
            else:
                self.root.after(0, lambda v=ver: self.update_status(f"yt-dlp {v} - Ready", None))
            return
        # Manual update: run -U, then clear cache, then show new version.
        try:
            self.root.after(0, lambda v=ver: self.log_message(
                f"Checking for yt-dlp updates...\nCurrent version: {v}\n\n"))
            rc = self._stream_cmd_to_log([ytdlp_path, "-U"])
            if rc != 0:
                self.root.after(0, lambda: self.on_update_complete(
                    rc, False,
                    "Update failed (no internet, GitHub limit, or exe locked). "
                    "Close other yt-dlp instances and retry, or download manually from "
                    "github.com/yt-dlp/yt-dlp/releases."))
                return
            self.root.after(0, lambda: self.log_message("\nClearing player cache...\n"))
            rc2 = self._stream_cmd_to_log([ytdlp_path, "--rm-cache-dir"])
            new_ver, _ = self._get_ytdlp_version()
            self.root.after(0, lambda: self.on_update_complete(
                rc2, False, f"Update finished. Now on yt-dlp {new_ver}."))
        except Exception as e:
            self.root.after(0, lambda: self.on_update_complete(1, False, str(e)))

    def on_update_complete(self, return_code, auto=False, message=""):
        self.is_updating = False
        self.is_downloading = False
        self.current_process = None
        # Restore buttons (extract always re-enabled; stop disabled when idle).
        try:
            self.set_button_state(self.extract_btn, True)
            self.set_button_state(self.update_btn, True)
            self.set_button_state(self.stop_btn, False)
        except Exception:
            pass
        if auto:
            return
        if return_code == 0:
            self.update_status("yt-dlp up to date!", self.ACCENT_GREEN)
            self.log_message("\n" + "="*70 + f"\n[UI] SUCCESS: {message}\n")
            messagebox.showinfo("Update", message)
        else:
            self.update_status("Update failed.", self.ACCENT_RED)
            self.log_message("\n" + "="*70 + f"\n[UI] UPDATE FAILED: {message}\n")
            messagebox.showwarning("Update Failed", message)
                
    def extraction_worker(self, url, folder, audio_format, cookie_file, custom_name=""):
        # Resolve absolute output folder
        if not os.path.isabs(folder):
            abs_folder = os.path.abspath(os.path.join(self.script_dir, folder))
        else:
            abs_folder = folder
            
        # Ensure directory exists
        try:
            os.makedirs(abs_folder, exist_ok=True)
        except Exception as e:
            self.root.after(0, lambda: self.on_extraction_error(f"Failed to create target folder: {e}"))
            return
            
        # Build command
        ytdlp_path = os.path.join(self.script_dir, "yt-dlp.exe")
        
        cmd = [
            ytdlp_path,
            "-f", "bestaudio/best",
            "--extract-audio",
            "--audio-format", audio_format,
            "--ffmpeg-location", self.script_dir,
            "--no-playlist",
            "--retries", "10",
            "--fragment-retries", "10",
        ]

        # Warn if yt-dlp itself is stale (>60 days). The Aug 2026 android_vr
        # 403 breakage (fixed in stable 2026.08.19) is the classic example.
        try:
            ver_out = subprocess.run(
                [ytdlp_path, "--version"],
                capture_output=True, text=True, timeout=15, cwd=self.script_dir
            ).stdout.strip().splitlines()
            ver_str = ver_out[0].strip() if ver_out else ""
            import re as _re
            from datetime import date as _date
            m = _re.search(r"(\d{4})\.(\d{2})\.(\d{2})", ver_str)
            if m:
                vdate = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                age_days = (_date.today() - vdate).days
                if age_days > 60:
                    self.root.after(0, lambda a=age_days, v=ver_str: self.log_message(
                        f"[Warning] yt-dlp {v} is {a} days old. YouTube changes break old "
                        f"versions with 'HTTP Error 403'. Run: yt-dlp.exe -U  and  "
                        f"yt-dlp.exe --rm-cache-dir\n"
                    ))
        except Exception:
            pass
        
        # Cookies
        if cookie_file and cookie_file != "None":
            if cookie_file.startswith("Browser: "):
                browser_name = cookie_file.replace("Browser: ", "").strip().lower()
                cmd.extend(["--cookies-from-browser", browser_name])
                if browser_name == "chrome":
                    self.root.after(0, lambda: self.log_message(
                        "[Info] Using live Chrome cookies. If this fails, fully close "
                        "Chrome first - it locks its cookie database while running, "
                        "which can make yt-dlp read a stale or empty copy.\n"
                    ))
            else:
                cookie_path = os.path.join(self.script_dir, cookie_file)
                if os.path.isfile(cookie_path):
                    cmd.extend(["--cookies", cookie_path])
                    # Freshness + logged-in check: static exports go stale in
                    # hours, and a file without SID/HSID/LOGIN_INFO is logged-out.
                    try:
                        import time as _time
                        age_h = (_time.time() - os.path.getmtime(cookie_path)) / 3600
                        with open(cookie_path, "r", encoding="utf-8", errors="replace") as _f:
                            _data = _f.read(20000)
                        has_auth = any(k in _data for k in ("SID", "HSID", "SSID", "LOGIN_INFO", "SAPISID"))
                        if age_h > 24:
                            self.root.after(0, lambda a=age_h: self.log_message(
                                f"[Warning] Cookie file is {a:.0f}h old. Re-export it from your "
                                f"browser (Get cookies.txt LOCALLY) - stale cookies cause 403.\n"
                            ))
                        if not has_auth:
                            self.root.after(0, lambda: self.log_message(
                                "[Warning] Cookie file looks LOGGED-OUT (no SID/HSID/LOGIN_INFO). "
                                "Export while logged into YouTube, or pick 'Browser: ...' instead.\n"
                            ))
                    except Exception:
                        pass
                else:
                    self.root.after(0, lambda m=f"[Warning] Cookie file '{cookie_file}' was selected but not found.\n": self.log_message(m))
                
        # Output template
        if custom_name:
            # Strip any typed extension from custom_name to prevent double extension (like .mp3.mp3)
            clean_name = custom_name
            for ext in ['.mp3', '.opus', '.m4a', '.flac', '.wav', '.aac', '.ogg', '.webm', '.mkv', '.mp4']:
                if custom_name.lower().endswith(ext):
                    clean_name = custom_name[:-len(ext)]
                    break
            output_template = os.path.join(abs_folder, f"{clean_name}.%(ext)s")
        else:
            output_template = os.path.join(abs_folder, "%(title)s.%(ext)s")
            
        cmd.extend(["-o", output_template])
        
        # Add URL
        cmd.append(url)
        
        # Log starting command
        self.root.after(0, lambda: self.log_message(f"Starting Extraction...\nCommand: {' '.join(cmd)}\n\n" + "="*70 + "\n\n"))
        
        try:
            # Run the process
            # startupinfo hides the console window on Windows when starting sub-processes
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.script_dir,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo
            )
            
            # Read stdout line by line
            while True:
                line = self.current_process.stdout.readline()
                if not line:
                    break
                # Send log to UI thread
                self.root.after(0, lambda l=line: self.log_message(l))
                
            # Wait for completion
            return_code = self.current_process.wait()
            
            # Finish up in the main thread
            self.root.after(0, lambda: self.on_extraction_complete(return_code))
            
        except Exception as e:
            self.root.after(0, lambda: self.on_extraction_error(str(e)))
            
    def on_extraction_complete(self, return_code):
        self.is_downloading = False
        self.set_button_state(self.extract_btn, True)
        self.set_button_state(self.update_btn, True)
        self.set_button_state(self.stop_btn, False)
        self.current_process = None
        
        if return_code == 0:
            self.update_status("Extraction Completed Successfully!", self.ACCENT_GREEN)
            self.log_message("\n" + "="*70 + "\n[UI] SUCCESS: Extraction finished!\n")
            messagebox.showinfo("Success", "Audio has been successfully extracted and saved!")
        else:
            # If terminated by taskkill, return code is usually not 0
            self.update_status("Extraction Stopped or Failed.", self.ACCENT_RED)
            self.log_message(f"\n" + "="*70 + f"\n[UI] STOPPED / FAILED: Process exited with return code {return_code}.\n")
            try:
                log_dump = self.log_text.get(1.0, tk.END)
            except Exception:
                log_dump = ""
            if "403" in log_dump or "Forbidden" in log_dump:
                self.log_message(
                    "[Hint] 403 Forbidden on YouTube usually means stale yt-dlp/player cache,\n"
                    "not a ban. Fix order: 1) yt-dlp.exe -U  2) yt-dlp.exe --rm-cache-dir\n"
                    "3) re-export cookies.txt while logged in (or use Browser: cookies)\n"
                    "4) retry. If it persists, try another video / network (disable VPN).\n"
                )
            messagebox.showwarning("Extraction Ended", "The process did not complete successfully. Check the log for details.")
            
    def on_extraction_error(self, err_msg):
        self.is_downloading = False
        self.set_button_state(self.extract_btn, True)
        self.set_button_state(self.update_btn, True)
        self.set_button_state(self.stop_btn, False)
        self.current_process = None
        
        self.update_status("Error Occurred", self.ACCENT_RED)
        self.log_message(f"\n" + "="*70 + f"\n[UI] ERROR: {err_msg}\n")
        messagebox.showerror("Error", f"An error occurred during extraction:\n{err_msg}")

if __name__ == "__main__":
    root = tk.Tk()
    app = AudioExtractorApp(root)
    root.mainloop()