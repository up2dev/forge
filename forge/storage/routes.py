"""
forge.storage.routes
=======================
Router fichiers prêt à l'emploi :

    from forge.storage.routes import files_router
    ALL_ROUTERS.append(files_router)
"""
from __future__ import annotations

from forge.routing import ControllerRouter
from forge.storage.controller import FileController
from forge.storage.schemas import FileRead

files_router = ControllerRouter(FileController, prefix="/files", tags=["files"])

files_router.post("/", "upload", authenticated_only=True)
files_router.post("/start", "start", authenticated_only=True)
files_router.get("/", "list", authenticated_only=True, response_model=list[FileRead])

files_router.get("/{uid}", "show", authenticated_only=True)
files_router.put("/{uid}", "append_chunk", authenticated_only=True)
files_router.post("/{uid}/complete", "complete", authenticated_only=True)
files_router.get("/{uid}/download", "download", authenticated_only=True)
files_router.delete("/{uid}", "remove", authenticated_only=True)
