from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    content_type: str
    total_bytes: int
    received_bytes: int
    completed_at: datetime | None
    created_at: datetime
    max_chunk_size: int  # FORGE_STORAGE_CHUNK_SIZE — pour un PUT /files/{id}


class StartUploadRequest(BaseModel):
    filename: str
    content_type: str
    total_bytes: int
