"""
downloader.py
=============
Backend engine for JAJAS Downloader.
Handles URL analysis, format fetching, and download execution via yt-dlp.
"""

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional
import yt_dlp


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

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
        "ffmpeg_location": ".",
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
        "ffmpeg_location": ".",
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
    Calls task.progress_hook with a dict on every progress update.
    This function is blocking — run it in a thread.
    """
    url = task.video.url
    fmt = task.format_string
    out_path = task.output_path

    # Determine extension from format string heuristics
    is_audio = "ExtractAudio" in str(task)  # won't matter, we use postprocessors
    ext = "%(ext)s"

    ydl_opts = {
        "format": fmt,
        "outtmpl": f"{out_path}/%(title)s.%(ext)s",
        "progress_hooks": [task.progress_hook],
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": None,
        "postprocessors": [],
        "ffmpeg_location": ".",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def download_with_options(
    video: VideoEntry,
    output_path: str,
    quality_label: str,
    extension: str,
    progress_hook: Callable,
) -> None:
    """
    High-level download helper that wires everything together.
    Builds format string and postprocessors from human-readable choices.
    """
    fmt = build_format_string(quality_label)
    pps = build_postprocessors(quality_label, extension.lower())

    ydl_opts = {
        "format": fmt,
        "outtmpl": f"{output_path}/%(title)s.%(ext)s",
        "progress_hooks": [progress_hook],
        "quiet": True,
        "no_warnings": True,
        "postprocessors": pps,
        "keepvideo": False,
        "ffmpeg_location": ".",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video.url])


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
) -> threading.Thread:
    """Run download_with_options in a daemon thread."""
    def _run():
        try:
            download_with_options(video, output_path, quality_label, extension, progress_hook)
            on_done(video)
        except Exception as exc:
            on_error(video, exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
