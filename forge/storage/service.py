"""
forge.storage.service
========================
Écrit/lit les fichiers sur disque local. Upload direct (un seul
appel) et upload par chunks (résumable) partagent le même modèle et
la même allowlist de types/taille — seule différence : un upload par
chunks passe par completed_at=None tant qu'il n'est pas fini.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select

from forge.config import get_settings
from forge.db import get_session
from forge.storage.models import StorageFile


class UnsupportedFileType(Exception):
    pass


class FileTooLarge(Exception):
    pass


class UploadIncomplete(Exception):
    pass


class ChunkTooLarge(Exception):
    pass


def _storage_dir() -> Path:
    path = Path(get_settings().storage_dir)
    path.mkdir(parents=True, exist_ok=True)

    return path


def _tmp_dir() -> Path:
    path = _storage_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)

    return path


def _tmp_path(storage_key: str) -> Path:
    return _tmp_dir() / storage_key


def path_of(record: StorageFile) -> Path:
    """Tant qu'un upload par chunks n'est pas complété, le fichier vit
    dans tmp/ — jamais exposé tel quel (stream/download exigent
    completed_at, voir get_file)."""
    if record.completed_at is None:
        return _tmp_path(record.storage_key)

    return _storage_dir() / record.storage_key


async def save_upload(upload: UploadFile, owner_id: int | None) -> StorageFile:
    settings = get_settings()
    content_type = upload.content_type or "application/octet-stream"

    if content_type not in settings.storage_allowed_types:
        raise UnsupportedFileType(content_type)

    storage_key = uuid.uuid4().hex
    dest = _storage_dir() / storage_key
    size = 0

    with dest.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)

            if size > settings.storage_max_bytes:
                out.close()
                dest.unlink(missing_ok=True)

                raise FileTooLarge(size)

            out.write(chunk)

    async with get_session() as session:
        record = StorageFile(
            filename=upload.filename or storage_key,
            content_type=content_type,
            total_bytes=size,
            received_bytes=size,
            storage_key=storage_key,
            completed_at=datetime.now(timezone.utc),
            owner_id=owner_id,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        return record


async def get_file(file_id: int, owner_id: int | None, require_complete: bool = True) -> StorageFile | None:
    async with get_session() as session:
        stmt = select(StorageFile).where(StorageFile.id == file_id)

        if owner_id is not None:
            stmt = stmt.where(StorageFile.owner_id == owner_id)

        record = (await session.execute(stmt)).scalar_one_or_none()

    if record is not None and require_complete and record.completed_at is None:
        return None

    return record


async def list_files(owner_id: int) -> list[StorageFile]:
    async with get_session() as session:
        stmt = select(StorageFile).where(StorageFile.owner_id == owner_id)

        return list((await session.execute(stmt)).scalars().all())


async def delete_file(file_id: int, owner_id: int | None) -> bool:
    record = await get_file(file_id, owner_id, require_complete=False)

    if record is None:
        return False

    async with get_session() as session:
        db_record = await session.get(StorageFile, record.id)
        await session.delete(db_record)
        await session.commit()

    path_of(record).unlink(missing_ok=True)

    return True


# ------------------------------------------------------------------
# Upload par chunks — même StorageFile du début à la fin
# ------------------------------------------------------------------


async def start_chunked_upload(
    filename: str, content_type: str, total_bytes: int, owner_id: int | None
) -> StorageFile:
    settings = get_settings()

    if content_type not in settings.storage_allowed_types:
        raise UnsupportedFileType(content_type)

    if total_bytes > settings.storage_max_bytes:
        raise FileTooLarge(total_bytes)

    storage_key = uuid.uuid4().hex
    _tmp_path(storage_key).touch()

    async with get_session() as session:
        record = StorageFile(
            filename=filename,
            content_type=content_type,
            total_bytes=total_bytes,
            received_bytes=0,
            storage_key=storage_key,
            completed_at=None,
            owner_id=owner_id,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        return record


async def append_chunk(file_id: int, owner_id: int | None, chunk: bytes) -> StorageFile:
    """Ajoute `chunk` à la suite de ce qui est déjà reçu — toujours en
    fin de fichier. Un client qui a perdu la connexion relit
    received_bytes (get_file) pour reprendre, sans tout renvoyer."""
    record = await get_file(file_id, owner_id, require_complete=False)

    if record is None or record.completed_at is not None:
        return None

    settings = get_settings()

    if len(chunk) > settings.storage_chunk_size:
        raise ChunkTooLarge(len(chunk))

    new_total = record.received_bytes + len(chunk)

    if new_total > record.total_bytes or new_total > settings.storage_max_bytes:
        raise FileTooLarge(new_total)

    with _tmp_path(record.storage_key).open("ab") as out:
        out.write(chunk)

    async with get_session() as session:
        db_record = await session.get(StorageFile, record.id)
        db_record.received_bytes = new_total
        await session.commit()
        await session.refresh(db_record)

        return db_record


async def complete_chunked_upload(file_id: int, owner_id: int | None) -> StorageFile:
    record = await get_file(file_id, owner_id, require_complete=False)

    if record is None or record.completed_at is not None:
        return None

    if record.received_bytes != record.total_bytes:
        raise UploadIncomplete(f"{record.received_bytes}/{record.total_bytes}")

    _tmp_path(record.storage_key).rename(_storage_dir() / record.storage_key)

    async with get_session() as session:
        db_record = await session.get(StorageFile, record.id)
        db_record.completed_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(db_record)

        return db_record
