"""Penyimpanan video di Cloudflare R2 (kompatibel S3).

Memakai: R2_S3_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME.
boto3 diimpor saat dipakai, supaya modul lain tetap ringan.
"""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from app.config import settings


class StorageNotConfigured(RuntimeError):
    pass


def _endpoint() -> str:
    """Hanya skema + host. Jika endpoint tersalin dengan nama bucket atau
    garis miring di belakangnya, bagian itu dibuang."""
    p = urlsplit(settings.r2_s3_endpoint.strip())
    return f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""


def is_configured() -> bool:
    return all([
        _endpoint(),
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket_name,
    ])


@lru_cache(maxsize=1)
def _client():
    if not is_configured():
        raise StorageNotConfigured("R2 belum dikonfigurasi")
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_endpoint(),
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",  # diwajibkan boto3, tidak dipakai R2
        config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    )


def media_key(tenant_id: int, account_id: int, ig_media_id: str) -> str:
    # Kunci deterministik: memproses ulang video yang sama menimpa file lama.
    return f"t{tenant_id}/a{account_id}/{ig_media_id}.mp4"


def upload_video(path: Path, key: str) -> None:
    _client().upload_file(
        str(path), settings.r2_bucket_name, key, ExtraArgs={"ContentType": "video/mp4"}
    )


def presign_get(key: str, ttl_seconds: int) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.r2_bucket_name, "Key": key},
        ExpiresIn=ttl_seconds,
    )


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=settings.r2_bucket_name, Key=key)
