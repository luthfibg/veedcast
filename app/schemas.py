from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ConnectSessionIn(BaseModel):
    external_ref: str = Field(min_length=1, max_length=120)  # ID klien di sisi CMS
    return_url: HttpUrl


class ConnectSessionOut(BaseModel):
    session_id: str
    connect_url: str
    expires_at: datetime


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_ref: str | None
    username: str
    status: str
    rotation: int
    max_active_videos: int
    auto_publish: bool
    token_expires_at: datetime | None
    last_synced_at: datetime | None


class ConnectSessionStatus(BaseModel):
    session_id: str
    status: str
    account: AccountOut | None = None


class AccountUpdate(BaseModel):
    rotation: Literal[0, 90, 180, 270] | None = None
    max_active_videos: int | None = Field(default=None, ge=1, le=50)
    auto_publish: bool | None = None


class MediaOut(BaseModel):
    id: int
    ig_media_id: str
    permalink: str | None
    posted_at: datetime | None
    duration_s: float | None
    width: int | None
    height: int | None
    size_bytes: int
    download_url: str
    expires_at: datetime