import threading
import sys
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

def get_ffmpeg_path() -> str:
    """Return the correct path for bundled FFmpeg if running from PyInstaller, else '.' """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return "."

@dataclass
class VideoEntry:
    """Represents a single video (inside a playlist or standalone)."""
    url: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None   # seconds
    formats: list = field(default_factory=list)
    selected: bool = True
    chosen_format: str = "bestvideo+bestaudio/best"  # yt-dlp format string


@dataclass
class Analysis:
    """Result returned from analyze_url()."""
    is_playlist: bool
    title: str
    entries: list[VideoEntry]


@dataclass
class DownloadTask:
    """A unit of work for the download engine."""
    video: VideoEntry
    output_path: str
    format_string: str
    progress_hook: Callable
    ratelimit: Optional[int] = None  # bytes per second
    stop_event: threading.Event = threading.Event()
    pause_event: threading.Event = threading.Event() # Set = PAUSED

class DownloadStopException(Exception):
    """Custom exception to stop yt-dlp safely."""
    pass


# ---------------------------------------------------------------------------
# Format helpers
# ---------------------------------------------------------------------------

RESOLUTION_MAP = {
    "Mejor calidad":    "bestvideo+bestaudio/best",
    "4K (2160p)":       "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1080p":            "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p":             "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p":             "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "360p":             "bestvideo[height<=360]+bestaudio/best[height<=360]",
    "Solo Audio (MP3)": "bestaudio/best",
    "Solo Audio (WAV)": "bestaudio/best",
}

AUDIO_FORMATS = {"Solo Audio (MP3)", "Solo Audio (WAV)"}

EXTENSION_MAP = {
    "MP4": "mp4",
    "MKV": "mkv",
    "MP3": "mp3",
    "WAV": "wav",
}


def build_format_string(label: str) -> str:
    """Convert a human-readable quality label to a yt-dlp format selector."""
    return RESOLUTION_MAP.get(label, "bestvideo+bestaudio/best")


def build_postprocessors(label: str, extension: str) -> list:
    """Return yt-dlp postprocessors based on chosen label and container extension."""
    pp = []
    if extension in ("mp3", "wav"):
        pp.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": extension,
            "preferredquality": "192" if extension == "mp3" else "0",
        })
    elif label in AUDIO_FORMATS:
        codec = "mp3" if "MP3" in label else "wav"
        pp.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": "192",
        })
    else:
        pp.append({
            "key": "FFmpegVideoConvertor",
            "preferedformat": extension,
        })
    return pp


# ---------------------------------------------------------------------------
# URL analysis
# ---------------------------------------------------------------------------

def analyze_url(url: str) -> Analysis:
    """
    Extract metadata from a URL without downloading.
    Returns an Analysis with video entries and basic info.
    Raises yt_dlp.utils.DownloadError on bad URLs.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",   # fast playlist scan
        "skip_download": True,
        "ffmpeg_location": get_ffmpeg_path(),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    is_playlist = info.get("_type") in ("playlist", "multi_video")

    if is_playlist:
        playlist_title = info.get("title", "Playlist sin título")
        raw_entries = info.get("entries", [])
        entries = []
        for e in raw_entries:
            if e is None:
                continue
            entry_url = e.get("url") or e.get("webpage_url", "")
            if not entry_url.startswith("http"):
                entry_url = f"https://www.youtube.com/watch?v={e.get('id', '')}"
            entries.append(VideoEntry(
                url=entry_url,
                title=e.get("title", "Sin título"),
                thumbnail=e.get("thumbnail"),
                duration=e.get("duration"),
            ))
        return Analysis(is_playlist=True, title=playlist_title, entries=entries)
    else:
        video_title = info.get("title", "Video sin título")
        thumb = info.get("thumbnail")
        dur = info.get("duration")
        entry = VideoEntry(
            url=url,
            title=video_title,
            thumbnail=thumb,
            duration=dur,
        )
        return Analysis(is_playlist=False, title=video_title, entries=[entry])


def fetch_formats(url: str) -> list[dict]:
    """
    Fetch the list of available formats for a single video.
    Returns a list of dicts with keys: format_id, resolution, ext, filesize.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ffmpeg_location": get_ffmpeg_path(),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    formats = []
    seen = set()
    for f in info.get("formats", []):
        res = f.get("resolution") or (
            f"{f['height']}p" if f.get("height") else "audio only"
        )
        key = (res, f.get("ext", ""))
        if key in seen:
            continue
        seen.add(key)
        formats.append({
            "format_id": f.get("format_id", ""),
            "resolution": res,
            "ext": f.get("ext", "?"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
        })
    return formats


# ---------------------------------------------------------------------------
# Download engine
# ---------------------------------------------------------------------------

def download(task: DownloadTask) -> None:
    """
    Execute a download for the given DownloadTask.
    Implements Stop, Pause, and Dynamic Throttling.
    """
    # Tracking for manual throttling
    start_time = time.time()
    
    def master_hook(d):
        # 1. STOP CHECK
        if task.stop_event.is_set():
            raise DownloadStopException("Download canceled by user")

        # 2. PAUSE CHECK
        while task.pause_event.is_set():
            if task.stop_event.is_set():
                raise DownloadStopException("Download canceled by user")
            time.sleep(0.2)

        # 3. DYNAMIC THROTTLING
        # task.ratelimit can be changed anytime by main.py
        if task.ratelimit and d.get('status') == 'downloading':
            try:
                downloaded = d.get('downloaded_bytes', 0)
                elapsed = time.time() - start_time
                if elapsed > 1: # Allow some ramp up
                    target_time = downloaded / task.ratelimit
                    if elapsed < target_time:
                        time.sleep(target_time - elapsed)
            except Exception:
                pass

        # 4. UI HOOK
        task.progress_hook(d)

    ydl_opts = {
        "format": task.format_string,
        "outtmpl": f"{task.output_path}/%(title)s.%(ext)s",
        "progress_hooks": [master_hook],
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": None,
        "postprocessors": [],
        "ffmpeg_location": get_ffmpeg_path(),
        "ratelimit": task.ratelimit,
    }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([task.video.url])
    except DownloadStopException:
        pass # Handle gracefully
    except Exception as e:
        raise e


def download_with_options(task: DownloadTask, quality_label: str, extension: str) -> None:
    """
    High-level download helper that wires everything together.
    Now uses the DownloadTask to support controls.
    """
    task.format_string = build_format_string(quality_label)
    pps = build_postprocessors(quality_label, extension.lower())

    # We reuse 'download' which already has the control logic
    # But we need to inject postprocessors here
    ydl_opts = {
        "format": task.format_string,
        "outtmpl": f"{task.output_path}/%(title)s.%(ext)s",
        "progress_hooks": [], # We will wrap in download() if needed, but for simplicity:
        "quiet": True,
        "no_warnings": True,
        "postprocessors": pps,
        "keepvideo": False,
        "ffmpeg_location": get_ffmpeg_path(),
        "ratelimit": task.ratelimit,
    }

    # Internal wrapper for controls inside this specific flow
    start_time = time.time()
    def master_hook(d):
        if task.stop_event.is_set(): raise DownloadStopException()
        while task.pause_event.is_set():
            if task.stop_event.is_set(): raise DownloadStopException()
            time.sleep(0.2)
        if task.ratelimit and d.get('status') == 'downloading':
            try:
                target = d.get('downloaded_bytes', 0) / task.ratelimit
                elapsed = time.time() - start_time
                if elapsed < target: time.sleep(target - elapsed)
            except: pass
        task.progress_hook(d)

    ydl_opts["progress_hooks"] = [master_hook]

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([task.video.url])
    except DownloadStopException:
        pass


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------

def analyze_url_async(url: str, on_done: Callable, on_error: Callable) -> threading.Thread:
    """Run analyze_url in a daemon thread. Calls on_done(Analysis) or on_error(Exception)."""
    def _run():
        try:
            result = analyze_url(url)
            on_done(result)
        except Exception as exc:
            on_error(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def download_async(
    video: VideoEntry,
    output_path: str,
    quality_label: str,
    extension: str,
    progress_hook: Callable,
    on_done: Callable,
    on_error: Callable,
    ratelimit: Optional[int] = None,
) -> DownloadTask:
    """Run download_with_options in a daemon thread. Returns task for control."""
    task = DownloadTask(
        video=video,
        output_path=output_path,
        format_string="", # Built inside
        progress_hook=progress_hook,
        ratelimit=ratelimit
    )

    def _run():
        try:
            download_with_options(task, quality_label, extension)
            if not task.stop_event.is_set():
                on_done(video)
        except Exception as exc:
            on_error(video, exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return task
