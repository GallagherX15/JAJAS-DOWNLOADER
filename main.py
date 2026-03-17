import os
import threading
import sys
import tkinter as tk
import re
from io import BytesIO

import customtkinter as ctk
from PIL import Image
import requests

from downloader import (
    VideoEntry,
    analyze_url_async,
    download_async,
    RESOLUTION_MAP,
    AUDIO_FORMATS,
    EXTENSION_MAP,
    get_ffmpeg_path
)

# Speed Limits in Bytes
SPEED_LIMITS = {
    "🐌 Caracol": 50 * 1024,
    "⚖️ Normal": 1024 * 1024,
    "🚀 Turbo": None
}

# App Configuration
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class PlaylistRow(ctk.CTkFrame):
    def __init__(self, master, entry: VideoEntry, global_formats: list[str], global_extensions: list[str], **kwargs):
        super().__init__(master, **kwargs)
        self.entry = entry

        # Checkbox
        self.var_selected = ctk.BooleanVar(value=True)
        self.checkbox = ctk.CTkCheckBox(self, text="", variable=self.var_selected, width=20, command=self._on_check)
        self.checkbox.pack(side="left", padx=10, pady=10)

        # Thumbnail
        self.thumb_label = ctk.CTkLabel(self, text="Cargando...", width=120, height=68, fg_color="gray20", corner_radius=6)
        self.thumb_label.pack(side="left", padx=10)

        # Title
        self.title_label = ctk.CTkLabel(self, text=entry.title, anchor="w", justify="left")
        self.title_label.pack(side="left", fill="x", expand=True, padx=10)

        # Format Dropdowns Frame
        self.dropdowns_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.dropdowns_frame.pack(side="right", padx=10)
        
        # Extension Selector
        self.ext_var = ctk.StringVar(value="MP4")
        self.ext_dropdown = ctk.CTkOptionMenu(
            self.dropdowns_frame,
            values=["MP4", "MKV", "MP3", "WAV"],
            variable=self.ext_var,
            width=80,
            command=self._on_ext_change
        )
        self.ext_dropdown.pack(side="left", padx=(0, 5))

        # Quality Selector
        self.quality_var = ctk.StringVar(value="1080p")
        self.quality_dropdown = ctk.CTkOptionMenu(
            self.dropdowns_frame,
            values=global_formats,
            variable=self.quality_var,
            width=120
        )
        self.quality_dropdown.pack(side="left")

        # Load Thumbnail
        if entry.thumbnail:
            self._load_thumbnail_async(entry.thumbnail)

    def _on_check(self):
        self.entry.selected = self.var_selected.get()

    def _on_ext_change(self, choice):
        if choice in ("MP3", "WAV"):
            self.quality_dropdown.configure(values=list(AUDIO_FORMATS))
            self.quality_var.set(f"Solo Audio ({choice})")
            self.quality_dropdown.configure(state="disabled")
        else:
            self.quality_dropdown.configure(values=[k for k in RESOLUTION_MAP.keys() if k not in AUDIO_FORMATS])
            self.quality_var.set("1080p")
            self.quality_dropdown.configure(state="normal")

    def _load_thumbnail_async(self, url):
        def _fetch():
            try:
                response = requests.get(url, timeout=5)
                img = Image.open(BytesIO(response.content))
                # Crop to 16:9 roughly
                w, h = img.size
                target_h = int(w * 9 / 16)
                if h > target_h:
                    top = (h - target_h) // 2
                    img = img.crop((0, top, w, h - top))
                
                ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(120, 68))
                self.after(0, lambda: self.thumb_label.configure(image=ctk_img, text=""))
            except Exception as e:
                print(f"Thumbnail load failed: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    def set_global_mode(self, enabled: bool):
        """If global mode is enabled, disable individual selectors."""
        state = "disabled" if enabled else "normal"
        self.quality_dropdown.configure(state=state)
        self.ext_dropdown.configure(state=state)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("JAJAS Downloader")
        self.geometry("900x700")
        self.minsize(800, 600)

        # State
        self.output_dir = ctk.StringVar(value=os.path.expanduser("~/Downloads"))
        self.current_analysis = None
        self.active_downloads = 0
        self.total_downloads = 0
        self.completed_downloads = 0

        self.active_tasks = []
        self.is_paused = False

        # Speed limit choice
        self.speed_limit_var = ctk.StringVar(value="🚀 Turbo")

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._set_app_icon()
        self._create_menu()
        self._build_ui()

    def _set_app_icon(self):
        icon_path = os.path.join(get_ffmpeg_path(), "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
                # For Windows taskbar icon fix
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mycompany.jajasdownloader.v1")
            except Exception:
                pass

    def _create_menu(self):
        self.menubar = tk.Menu(self)
        self.config(menu=self.menubar)
        
        options_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="Opciones", menu=options_menu)
        options_menu.add_command(label="🔄 Actualizar motor (yt-dlp)", command=self.on_update_requested)
        options_menu.add_separator()
        options_menu.add_command(label="Salir", command=self.quit)

    def on_update_requested(self):
        self.status_label.configure(text="Actualizando yt-dlp...")
        def _do_update():
            try:
                import subprocess
                subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"])
                self.after(0, lambda: tk.messagebox.showinfo("Actualización", "yt-dlp se actualizó correctamente."))
                self.after(0, lambda: self.status_label.configure(text="Listo."))
            except Exception as e:
                self.after(0, lambda: tk.messagebox.showerror("Error", f"No se pudo actualizar: {e}"))
        threading.Thread(target=_do_update, daemon=True).start()

    def on_uninstall_requested(self):
        msg = "¿Está seguro de que desea desinstalar JAJAS Downloader?\n\nEsto abrirá el desinstalador de Windows."
        if tk.messagebox.askyesno("Desinstalar", msg):
            os.system("control appwiz.cpl")
            self.quit()


    def on_speed_change(self, choice):
        limit = SPEED_LIMITS.get(choice)
        for task in self.active_tasks:
            task.ratelimit = limit

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(header, text="JAJAS Downloader", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")

        # Input Area
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=20)

        self.url_entry = ctk.CTkEntry(input_frame, placeholder_text="Pega la URL del video o playlist aquí...", height=40)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.cancel_analyze_btn = ctk.CTkButton(input_frame, text="Cancelar x", height=40, fg_color="#C0392B", hover_color="#922B21", font=ctk.CTkFont(weight="bold"), command=self.on_cancel_analyze)
        
        self.analyze_btn = ctk.CTkButton(input_frame, text="Analizar", height=40, font=ctk.CTkFont(weight="bold"), command=self.on_analyze)
        self.analyze_btn.pack(side="right")

        self._cancel_analysis = False

        # Global Config
        config_frame = ctk.CTkFrame(self)
        config_frame.pack(fill="x", padx=20, pady=20)

        ctk.CTkLabel(config_frame, text="Carpeta destino:").pack(side="left", padx=10, pady=10)
        self.dir_label = ctk.CTkLabel(config_frame, textvariable=self.output_dir, text_color="gray60", width=250, anchor="w")
        self.dir_label.pack(side="left", padx=10)
        ctk.CTkButton(config_frame, text="Cambiar ruta", width=80, command=self.on_choose_dir).pack(side="left", padx=10)

        # Speed Limiter UI
        ctk.CTkLabel(config_frame, text="Limitar:").pack(side="left", padx=(20, 5))
        self.speed_menu = ctk.CTkSegmentedButton(
            config_frame, 
            values=list(SPEED_LIMITS.keys()),
            variable=self.speed_limit_var,
            command=self.on_speed_change
        )
        self.speed_menu.pack(side="left", padx=10)

        # Playlist Area
        self.playlist_container = ctk.CTkFrame(self, fg_color="transparent")
        
        self.playlist_header = ctk.CTkFrame(self.playlist_container, fg_color="transparent")
        self.playlist_header.pack(fill="x", pady=(0, 5))
        
        self.playlist_title = ctk.CTkLabel(self.playlist_header, text="Videos encontrados", font=ctk.CTkFont(weight="bold"))
        self.playlist_title.pack(side="left")

        # Global Format for Playlist
        self.global_format_frame = ctk.CTkFrame(self.playlist_container, fg_color="gray15", corner_radius=6)
        self.global_format_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(self.global_format_frame, text="Formato Masivo:").pack(side="left", padx=(10, 10), pady=10)
        
        self.global_ext_var = ctk.StringVar(value="MP4")
        self.global_ext_menu = ctk.CTkOptionMenu(
            self.global_format_frame, 
            values=["MP4", "MKV", "MP3", "WAV"], 
            variable=self.global_ext_var, 
            width=80,
            command=self._on_global_ext_change
        )
        self.global_ext_menu.pack(side="left", padx=(0, 5), pady=10)

        video_res = [k for k in RESOLUTION_MAP.keys() if k not in AUDIO_FORMATS]
        self.global_quality_var = ctk.StringVar(value="1080p")
        self.global_quality_menu = ctk.CTkOptionMenu(
            self.global_format_frame, 
            values=video_res, 
            variable=self.global_quality_var, 
            width=120
        )
        self.global_quality_menu.pack(side="left", pady=10)

        self.individual_mode_var = ctk.BooleanVar(value=False)
        self.individual_mode_switch = ctk.CTkSwitch(
            self.global_format_frame, 
            text="Activar formato individual", 
            variable=self.individual_mode_var,
            command=self.on_mode_change
        )
        self.individual_mode_switch.pack(side="right", padx=10, pady=10)

        self.scroll_list = ctk.CTkScrollableFrame(self.playlist_container)
        self.scroll_list.pack(fill="both", expand=True)
        self.row_widgets = []

        # Download Button Row
        self.action_frame = ctk.CTkFrame(self, fg_color="transparent")
        
        self.download_btn = ctk.CTkButton(
            self.action_frame, 
            text="Descargar", 
            height=45, 
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#2E8B57",
            hover_color="#277D4E",
            command=self.on_download
        )
        self.download_btn.pack(side="right", fill="x", expand=True, padx=20)

        # Status Bar
        self.status_frame = ctk.CTkFrame(self, height=45)
        self.status_frame.pack(side="bottom", fill="x", padx=20, pady=20)
        
        self.status_label = ctk.CTkLabel(self.status_frame, text="Listo.")
        self.status_label.pack(side="left", padx=10)

        # Control Buttons (Hidden by default)
        self.controls_frame = ctk.CTkFrame(self.status_frame, fg_color="transparent")
        
        self.pause_btn = ctk.CTkButton(self.controls_frame, text="⏸️ Pausar", width=100, command=self.on_toggle_pause)
        self.pause_btn.pack(side="left", padx=5)
        
        self.cancel_dl_btn = ctk.CTkButton(self.controls_frame, text="🛑 Cancelar", width=100, fg_color="#C0392B", hover_color="#922B21", command=self.on_cancel_downloads)
        self.cancel_dl_btn.pack(side="left", padx=5)

        self.pc_label = ctk.CTkLabel(self.status_frame, text="0%", font=ctk.CTkFont(weight="bold"))
        self.pc_label.pack(side="right", padx=10)

        self.progress_bar = ctk.CTkProgressBar(self.status_frame, width=200)
        self.progress_bar.set(0)
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=10)

        self.eta_label = ctk.CTkLabel(self.status_frame, text="ETA: --")
        self.eta_label.pack(side="right", padx=10)
        
        self.speed_label = ctk.CTkLabel(self.status_frame, text="Velocidad: --")
        self.speed_label.pack(side="right", padx=10)



    def _on_global_ext_change(self, choice):
        if choice in ("MP3", "WAV"):
            self.global_quality_menu.configure(values=list(AUDIO_FORMATS))
            self.global_quality_var.set(f"Solo Audio ({choice})")
            self.global_quality_menu.configure(state="disabled")
        else:
            self.global_quality_menu.configure(values=[k for k in RESOLUTION_MAP.keys() if k not in AUDIO_FORMATS])
            self.global_quality_var.set("1080p")
            self.global_quality_menu.configure(state="normal")

    def on_choose_dir(self):
        d = ctk.filedialog.askdirectory(initialdir=self.output_dir.get())
        if d:
            self.output_dir.set(d)

    def on_analyze(self):
        url = self.url_entry.get().strip()
        if not url:
            return

        self._cancel_analysis = False
        self.analyze_btn.pack_forget()
        self.cancel_analyze_btn.pack(side="right")
        self.status_label.configure(text="Obteniendo información del enlace...")

        
        # Clear old rows
        for w in self.row_widgets:
            w.destroy()
        self.row_widgets.clear()
        self.playlist_container.pack_forget()
        self.action_frame.pack_forget()

        analyze_url_async(url, self._on_analyze_done, self._on_analyze_err)

    def on_cancel_analyze(self):
        self._cancel_analysis = True
        self.status_label.configure(text="Análisis cancelado por el usuario.")
        self._restore_analyze_btn()

    def _restore_analyze_btn(self):
        self.cancel_analyze_btn.pack_forget()
        self.analyze_btn.pack(side="right")
        self.analyze_btn.configure(state="normal", text="Analizar")

    def _on_analyze_done(self, analysis):
        if getattr(self, "_cancel_analysis", False):
            return
        self.after(0, self._render_analysis, analysis)

    def _on_analyze_err(self, exc):
        if getattr(self, "_cancel_analysis", False):
            return
        print(exc)
        self.after(0, lambda: self.status_label.configure(text=f"Error: {exc}"))
        self.after(0, self._restore_analyze_btn)

    def _render_analysis(self, analysis):
        self._restore_analyze_btn()
        self.current_analysis = analysis

        if analysis.is_playlist:
            self.status_label.configure(text=f"Análisis completado: Playlist de {len(analysis.entries)} video(s)")
            self.playlist_title.configure(text=analysis.title)
            self.playlist_header.pack(fill="x", pady=(0, 5))
            self.global_format_frame.pack(fill="x", pady=(0, 10))
            self.individual_mode_var.set(False)
            self.on_mode_change()
        else:
            self.status_label.configure(text="Análisis completado: 1 video encontrado")
            self.playlist_header.pack_forget()
            self.global_format_frame.pack_forget()
            self.individual_mode_var.set(True) # Force individual mode so the row dropdowns are active
        
        self.playlist_container.pack(fill="both", expand=True, padx=20, pady=10)
        self.action_frame.pack(fill="x", pady=(0, 10))

        video_res = [k for k in RESOLUTION_MAP.keys() if k not in AUDIO_FORMATS]
        exts = ["MP4", "MKV", "MP3", "WAV"]

        def _build_rows(start_idx=0, batch_size=15):
            end_idx = min(start_idx + batch_size, len(analysis.entries))
            for i in range(start_idx, end_idx):
                entry = analysis.entries[i]
                row = PlaylistRow(self.scroll_list, entry, video_res, exts)
                row.pack(fill="x", pady=2, padx=5)
                row.set_global_mode(not self.individual_mode_var.get())
                self.row_widgets.append(row)
            
            if end_idx < len(analysis.entries):
                self.status_label.configure(text=f"Cargando UI... {end_idx}/{len(analysis.entries)}")
                self.after(50, _build_rows, end_idx, batch_size)
            else:
                txt = f"Playlist detectada ({len(analysis.entries)} videos)" if analysis.is_playlist else "Video listo para descarga"
                self.status_label.configure(text=txt)

        _build_rows(0, 15)

    def on_mode_change(self, *args):
        is_individual = self.individual_mode_var.get()
        state = "disabled" if is_individual else "normal"
        self.global_ext_menu.configure(state=state)
        self.global_quality_menu.configure(state=state)
        
        for row in self.row_widgets:
            row.set_global_mode(not is_individual)

    def on_download(self):
        if not self.current_analysis:
            return

        to_download = []
        is_global = not self.individual_mode_var.get() and self.current_analysis.is_playlist
        
        global_qual = self.global_quality_var.get()
        global_ext = self.global_ext_var.get()

        for row in self.row_widgets:
            if row.entry.selected:
                if is_global:
                    q = global_qual
                    e = global_ext
                else:
                    q = row.quality_var.get()
                    e = row.ext_var.get()
                to_download.append((row.entry, q, e))

        if not to_download:
            self.status_label.configure(text="No hay videos seleccionados.")
            return

        self.total_downloads = len(to_download)
        self.completed_downloads = 0
        self.active_downloads = 0

        self.download_btn.configure(state="disabled", text="Descargando...")
        self.analyze_btn.configure(state="disabled")
        self.status_label.configure(text="Preparando descarga...")

        limit = SPEED_LIMITS.get(self.speed_limit_var.get())
        self.active_tasks = []
        self.is_paused = False
        self.pause_btn.configure(text="⏸️ Pausar")
        self.controls_frame.pack(side="left", padx=10)

        for entry, qual, ext in to_download:
            self.active_downloads += 1
            task = download_async(
                video=entry,
                output_path=self.output_dir.get(),
                quality_label=qual,
                extension=ext,
                progress_hook=self.on_progress,
                on_done=self._on_download_done,
                on_error=self._on_download_err,
                ratelimit=limit
            )
            self.active_tasks.append(task)

    def on_toggle_pause(self):
        self.is_paused = not self.is_paused
        txt = "▶️ Reanudar" if self.is_paused else "⏸️ Pausar"
        self.pause_btn.configure(text=txt)
        for task in self.active_tasks:
            if self.is_paused: task.pause_event.set()
            else: task.pause_event.clear()

    def on_cancel_downloads(self):
        if tk.messagebox.askyesno("Cancelar", "¿Deseas cancelar todas las descargas activas?"):
            for task in self.active_tasks:
                task.stop_event.set()
            self.active_tasks = []
            self._check_all_done()

    def on_closing(self):
        if len(self.active_tasks) > 0:
            if tk.messagebox.askyesno("Salir", "Hay descargas en curso. ¿Deseas cancelarlas y salir?"):
                for task in self.active_tasks:
                    task.stop_event.set()
                self.destroy()
        else:
            self.destroy()


    def on_progress(self, d):
        def strip_ansi(text):
            if not text: return ""
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            return ansi_escape.sub('', str(text))

        if d['status'] == 'downloading':
            try:
                # 1. Calculation based on raw bytes (more reliable)
                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                
                if total:
                    pct = downloaded / total
                    self.after(0, self.progress_bar.set, pct)
                    self.after(0, self.pc_label.configure, {"text": f"{int(pct*100)}%"})
                
                # 2. Cleanup strings with regex
                speed_str = strip_ansi(d.get('_speed_str', '--- b/s')).strip()
                eta_str = strip_ansi(d.get('_eta_str', '---')).strip()
                percent_str = strip_ansi(d.get('_percent_str', '0.0%')).strip()
                
                self.after(0, self.speed_label.configure, {"text": f"Velocidad: {speed_str}"})
                self.after(0, self.eta_label.configure, {"text": f"ETA: {eta_str}"})
                
                status_txt = f"Descargando ({self.completed_downloads}/{self.total_downloads}): {percent_str}"
                self.after(0, self.status_label.configure, {"text": status_txt})
            except Exception as e:
                print(f"Progress UI error: {e}")
        elif d['status'] == 'finished':
            self.after(0, self.status_label.configure, {"text": "Procesando archivo final..."})

    def _on_download_done(self, video):
        self.after(0, self._check_all_done)

    def _on_download_err(self, video, exc):
        err_msg = str(exc)
        if "Download canceled" in err_msg:
            self.after(0, lambda: self.status_label.configure(text="Descarga cancelada."))
        else:
            self.after(0, lambda: self.status_label.configure(text=f"Error en {video.title[:20]}: {err_msg[:40]}..."))
        self.after(0, self._check_all_done)

    def _check_all_done(self):
        self.completed_downloads += 1
        if self.completed_downloads >= self.total_downloads:
            self.controls_frame.pack_forget()
            self.active_tasks = []
            if "Error" not in self.status_label.cget("text"):
                self.status_label.configure(text="¡Todas las descargas completadas!")
            self.progress_bar.set(1)
            self.pc_label.configure(text="100%")
            self.download_btn.configure(state="normal", text="Descargar")
            self.analyze_btn.configure(state="normal")
            
            self.speed_label.configure(text="Velocidad: --")
            self.eta_label.configure(text="ETA: --")


if __name__ == "__main__":
    app = App()
    app.mainloop()
