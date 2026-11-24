"""Pemrosesan video dengan FFmpeg/ffprobe.

Hanya memakai pustaka standar, supaya mudah diuji sendiri.

Arti rotasi (searah jarum jam, diterapkan pada gambar yang sudah tegak):
  0   = tidak diputar
  90  = putar 90 derajat searah jarum jam
  180 = putar 180 derajat
  270 = putar 90 derajat berlawanan arah jarum jam
"""
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

MAX_SIDE = 1920          # sisi terpanjang maksimal setelah rotasi
TARGET_FPS = 30
MAX_DURATION_S = 300     # video lebih panjang dari ini dilewati
FFMPEG_TIMEOUT_S = 240


class VideoError(Exception):
    pass


@dataclass
class VideoInfo:
    duration_s: float
    width: int
    height: int
    fps: float


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise VideoError(f"{cmd[0]} tidak ditemukan di sistem") from None
    except subprocess.TimeoutExpired:
        raise VideoError(f"{cmd[0]} melebihi batas waktu {timeout} detik") from None


def _parse_fps(value: str | None) -> float:
    if not value or "/" not in value:
        return 0.0
    num, _, den = value.partition("/")
    try:
        return float(num) / float(den) if float(den) else 0.0
    except ValueError:
        return 0.0


def probe(path: Path) -> VideoInfo:
    r = _run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        timeout=60,
    )
    if r.returncode != 0:
        raise VideoError(f"ffprobe gagal: {r.stderr.strip()[-200:]}")
    try:
        data = json.loads(r.stdout)
    except ValueError:
        raise VideoError("ffprobe mengembalikan keluaran yang tidak valid") from None

    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if stream is None:
        raise VideoError("file tidak memiliki stream video")

    duration = data.get("format", {}).get("duration") or stream.get("duration")
    try:
        duration_s = float(duration)
    except (TypeError, ValueError):
        raise VideoError("durasi video tidak terbaca") from None

    return VideoInfo(
        duration_s=duration_s,
        width=int(stream.get("width", 0)),
        height=int(stream.get("height", 0)),
        fps=_parse_fps(stream.get("avg_frame_rate")) or _parse_fps(stream.get("r_frame_rate")),
    )


def build_filter(rotation: int, source_fps: float) -> str:
    """Rantai filter video. Rotasi metadata dari ponsel diterapkan FFmpeg
    otomatis lebih dulu (autorotate), sehingga rotasi di sini selalu
    relatif terhadap gambar yang sudah tegak."""
    parts: list[str] = []
    if rotation == 90:
        parts.append("transpose=1")
    elif rotation == 180:
        parts.append("transpose=1,transpose=1")
    elif rotation == 270:
        parts.append("transpose=2")
    elif rotation != 0:
        raise VideoError(f"rotasi tidak didukung: {rotation}")

    # Perkecil bila lebih besar dari batas; tidak pernah memperbesar.
    # Dimensi dibulatkan ke genap (syarat H.264 yuv420p).
    parts.append(
        f"scale=w='min({MAX_SIDE},iw)':h='min({MAX_SIDE},ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    parts.append("setsar=1")
    if source_fps > TARGET_FPS + 0.5:
        parts.append(f"fps={TARGET_FPS}")
    parts.append("format=yuv420p")
    return ",".join(parts)


def transcode(src: Path, dst: Path, rotation: int, source_fps: float) -> None:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
        "-map_metadata", "-1",
        "-vf", build_filter(rotation, source_fps),
        "-c:v", "libx264", "-profile:v", "high", "-preset", "veryfast", "-crf", "23",
        "-maxrate", "6M", "-bufsize", "12M",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]
    r = _run(cmd, timeout=FFMPEG_TIMEOUT_S)
    if r.returncode != 0:
        raise VideoError(f"ffmpeg gagal: {r.stderr.strip()[-300:]}")
    if not dst.exists() or dst.stat().st_size == 0:
        raise VideoError("ffmpeg tidak menghasilkan file keluaran")
