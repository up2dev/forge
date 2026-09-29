"""
forge.storage.controller
===========================
Upload direct ou par chunks, vue en ligne, téléchargement, suppression
— un seul jeu d'actions sur /files/{id}, quel que soit le mode
d'upload. Chaque fichier appartient à celui qui l'a envoyé (même
principe que owner_column sur NoteRepository, appliqué à la main ici
puisque File n'est pas un Repository CRUD classique).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from forge.config import get_settings
from forge.security.dependencies import get_current_user
from forge.security.models import User
from forge.storage.models import StorageFile
from forge.storage.schemas import FileRead, StartUploadRequest
from forge.storage.service import (
    ChunkTooLarge,
    FileTooLarge,
    UnsupportedFileType,
    UploadIncomplete,
    append_chunk,
    complete_chunked_upload,
    delete_file,
    get_file,
    list_files,
    path_of,
    save_upload,
    start_chunked_upload,
)


def _to_file_read(record: StorageFile) -> FileRead:
    return FileRead(
        id=record.id,
        filename=record.filename,
        content_type=record.content_type,
        total_bytes=record.total_bytes,
        received_bytes=record.received_bytes,
        completed_at=record.completed_at,
        created_at=record.created_at,
        max_chunk_size=get_settings().storage_chunk_size,
    )


class FileController:
    async def upload(self, file: UploadFile, user: User = Depends(get_current_user)) -> FileRead:
        try:
            record = await save_upload(file, owner_id=user.id)
        except UnsupportedFileType as exc:
            raise HTTPException(415, f"Unsupported file type: {exc}")
        except FileTooLarge:
            raise HTTPException(413, "File too large")

        return _to_file_read(record)

    async def start(
        self, payload: StartUploadRequest, user: User = Depends(get_current_user)
    ) -> FileRead:
        """Ouvre un upload par chunks — l'id renvoyé reste le même
        jusqu'à la fin, PUT/complete s'y réfèrent."""
        try:
            record = await start_chunked_upload(
                payload.filename, payload.content_type, payload.total_bytes, owner_id=user.id
            )
        except UnsupportedFileType as exc:
            raise HTTPException(415, f"Unsupported file type: {exc}")
        except FileTooLarge:
            raise HTTPException(413, "File too large")

        return _to_file_read(record)

    async def list(self, user: User = Depends(get_current_user)) -> list[FileRead]:
        records = await list_files(user.id)

        return [_to_file_read(r) for r in records]

    async def show(self, uid: int, user: User = Depends(get_current_user)):
        """Un seul endpoint, deux réponses selon l'état : upload en
        cours -> statut JSON (received_bytes/total_bytes, pour savoir
        où reprendre) ; upload terminé -> contenu du fichier en ligne."""
        record = await get_file(uid, owner_id=user.id, require_complete=False)

        if record is None:
            raise HTTPException(404, "Not found")

        if record.completed_at is None:
            return _to_file_read(record)

        return FileResponse(
            path_of(record),
            media_type=record.content_type,
            headers={"Content-Disposition": f'inline; filename="{record.filename}"'},
        )

    async def append_chunk(
        self, uid: int, request: Request, user: User = Depends(get_current_user)
    ) -> FileRead:
        """Corps de la requête = les octets du chunk, bruts (pas de
        multipart) — appendés à la suite de ce qui est déjà reçu."""
        chunk = await request.body()

        try:
            record = await append_chunk(uid, owner_id=user.id, chunk=chunk)
        except ChunkTooLarge:
            raise HTTPException(
                413, f"Chunk too large — max {get_settings().storage_chunk_size} bytes"
            )
        except FileTooLarge:
            raise HTTPException(413, "File too large")

        if record is None:
            raise HTTPException(404, "Not found, or already completed")

        return _to_file_read(record)

    async def complete(self, uid: int, user: User = Depends(get_current_user)) -> FileRead:
        try:
            record = await complete_chunked_upload(uid, owner_id=user.id)
        except UploadIncomplete as exc:
            raise HTTPException(400, f"Upload incomplete: {exc} bytes received")

        if record is None:
            raise HTTPException(404, "Not found, or already completed")

        return _to_file_read(record)

    async def download(self, uid: int, user: User = Depends(get_current_user)):
        record = await get_file(uid, owner_id=user.id)

        if record is None:
            raise HTTPException(404, "Not found")

        return FileResponse(path_of(record), media_type=record.content_type, filename=record.filename)

    async def remove(self, uid: int, user: User = Depends(get_current_user)) -> dict:
        ok = await delete_file(uid, owner_id=user.id)

        if not ok:
            raise HTTPException(404, "Not found")

        return {"deleted": uid}
