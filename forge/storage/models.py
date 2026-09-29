"""
forge.storage.models
======================
Un fichier = une ligne, direct ou par chunks. `storage_key` (uuid4,
opaque) est le nom réel sur disque — nom d'origine et type ne servent
qu'à la réponse HTTP, jamais au chemin disque. Élimine toute la classe
de bugs "path traversal via le nom de fichier client".

Un seul modèle pour les deux modes d'upload : `completed_at` distingue
un fichier prêt (upload direct : mis à `now()` immédiatement) d'un
upload par chunks en cours (`None` jusqu'à `/complete`). Le fichier
garde le même id du début à la fin — pas de bascule vers une autre
table à la fin.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from forge.models.base import Base, TimestampMixin


class StorageFile(Base, TimestampMixin):
    __tablename__ = "storage_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    total_bytes: Mapped[int] = mapped_column(Integer)
    received_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
