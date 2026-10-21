from __future__ import annotations

import mimetypes
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
import yt_dlp
from yt_dlp.utils import DownloadError


MAX_DOWNLOAD_MB = 200
MAX_DOWNLOAD_BYTES = MAX_DOWNLOAD_MB * 1024 * 1024

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def is_valid_youtube_url(url: str) -> bool:
    """Return True only for supported HTTP(S) YouTube URLs."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False

    hostname = (parsed.hostname or "").lower().rstrip(".")

    return (
        parsed.scheme in {"http", "https"}
        and hostname in ALLOWED_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def find_javascript_runtimes() -> dict[str, dict[str, str]]:
    """Enable supported JavaScript runtimes when installed."""
    runtimes: dict[str, dict[str, str]] = {}

    for runtime_name in ("deno", "node"):
        runtime_path = shutil.which(runtime_name)

        if runtime_path:
            runtimes[runtime_name] = {"path": runtime_path}

    return runtimes


def detect_mime_type(file_path: Path) -> str:
    """Return a suitable MIME type for Streamlit's download button."""
    known_types = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
    }

    return (
        known_types.get(file_path.suffix.lower())
        or mimetypes.guess_type(file_path.name)[0]
        or "application/octet-stream"
    )


def download_youtube_content(
    url: str,
    download_type: str,
    progress_bar,
) -> dict[str, str | bytes]:
    """Download one YouTube item and return its data and metadata."""

    def progress_hook(status: dict) -> None:
        state = status.get("status")

        if state == "downloading":
            downloaded = status.get("downloaded_bytes", 0)
            total = status.get("total_bytes") or status.get(
                "total_bytes_estimate"
            )

            if total:
                percentage = min(int(downloaded / total * 100), 100)
                progress_bar.progress(
                    percentage,
                    text=f"Downloading: {percentage}%",
                )
            else:
                downloaded_mb = downloaded / (1024 * 1024)
                progress_bar.progress(
                    0,
                    text=f"Downloaded: {downloaded_mb:.1f} MB",
                )

        elif state == "finished":
            progress_bar.progress(
                100,
                text="Download finished. Processing file...",
            )

    with tempfile.TemporaryDirectory(prefix="youtube_download_") as temp_dir:
        temp_path = Path(temp_dir)

        options: dict = {
            "outtmpl": str(
                temp_path / "%(title).120B [%(id)s].%(ext)s"
            ),
            "noplaylist": True,
            "max_filesize": MAX_DOWNLOAD_BYTES,
            "restrictfilenames": True,
            "overwrites": True,
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "quiet": True,
            "no_warnings": True,
            "cachedir": False,
            "progress_hooks": [progress_hook],
        }

        javascript_runtimes = find_javascript_runtimes()

        if javascript_runtimes:
            options["js_runtimes"] = javascript_runtimes

        if download_type == "Audio (MP3)":
            options.update(
                {
                    "format": "bestaudio/best",
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
        else:
            options.update(
                {
                    "format": (
                        "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
                        "b[height<=1080][ext=mp4]/"
                        "bv*[height<=1080]+ba/"
                        "b[height<=1080]"
                    ),
                    "merge_output_format": "mp4",
                }
            )

        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(url, download=True)

        candidates = [
            path
            for path in temp_path.iterdir()
            if path.is_file()
            and not path.name.endswith((".part", ".ytdl", ".temp"))
        ]

        if not candidates:
            raise RuntimeError("The downloaded file could not be found.")

        final_file = max(
            candidates,
            key=lambda path: path.stat().st_mtime,
        )
        file_size = final_file.stat().st_size

        if file_size > MAX_DOWNLOAD_BYTES:
            raise ValueError(
                f"The resulting file is larger than {MAX_DOWNLOAD_MB} MB."
            )

        return {
            "data": final_file.read_bytes(),
            "file_name": final_file.name,
            "mime_type": detect_mime_type(final_file),
        }


st.set_page_config(
    page_title="YouTube Content Downloader",
    page_icon="▶",
    layout="centered",
)

st.title("YouTube Content Downloader")
st.caption(
    "Download a single public YouTube video as video or MP3 audio."
)

with st.form("youtube_download_form"):
    youtube_url = st.text_input(
        "YouTube URL",
        placeholder="https://www.youtube.com/watch?v=...",
    )

    download_type = st.selectbox(
        "Download format",
        ("Video (up to 1080p)", "Audio (MP3)"),
    )

    has_permission = st.checkbox(
        "I own this content or have permission to download it."
    )

    submitted = st.form_submit_button(
        "Prepare download",
        type="primary",
        use_container_width=True,
    )

if submitted:
    st.session_state.pop("prepared_download", None)

    if not has_permission:
        st.warning("Please confirm that you have permission to download it.")

    elif not is_valid_youtube_url(youtube_url):
        st.error("Enter a valid YouTube or youtu.be URL.")

    else:
        progress = st.progress(0, text="Starting download...")

        try:
            with st.spinner("Preparing your file..."):
                st.session_state.prepared_download = (
                    download_youtube_content(
                        youtube_url.strip(),
                        download_type,
                        progress,
                    )
                )

            progress.empty()
            st.success("Your file is ready.")

        except DownloadError as error:
            progress.empty()
            st.error(f"YouTube could not provide this file: {error}")

        except (OSError, RuntimeError, ValueError) as error:
            progress.empty()
            st.error(f"The download could not be completed: {error}")

        except Exception:
            progress.empty()
            st.error(
                "An unexpected error occurred. Check the app logs for details."
            )

prepared_download = st.session_state.get("prepared_download")

if prepared_download:
    file_size_mb = len(prepared_download["data"]) / (1024 * 1024)

    st.write(
        f"**File:** {prepared_download['file_name']}  \n"
        f"**Size:** {file_size_mb:.1f} MB"
    )

    st.download_button(
        label="Download file",
        data=prepared_download["data"],
        file_name=prepared_download["file_name"],
        mime=prepared_download["mime_type"],
        type="primary",
        use_container_width=True,
    )

st.caption(
    f"Maximum resulting file size: {MAX_DOWNLOAD_MB} MB. "
    "Playlists, private videos, and sign-in-protected content are not supported."
)
