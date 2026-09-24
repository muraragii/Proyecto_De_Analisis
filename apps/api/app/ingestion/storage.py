"""Almacenamiento de archivos subidos.

Interfaz mínima para poder cambiar el disco local por S3 sin tocar el resto del código.
Las claves siempre van prefijadas por tenant para aislar los datos de cada cuenta.
"""

import uuid
from pathlib import Path
from typing import Protocol

from app.ingestion.parsers import file_extension


class Storage(Protocol):
    def save(self, tenant_id: str, filename: str, content: bytes) -> str: ...
    def put(self, key: str, content: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...  # FileNotFoundError si no existe


class LocalStorage:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def save(self, tenant_id: str, filename: str, content: bytes) -> str:
        key = f"{tenant_id}/{uuid.uuid4().hex}{file_extension(filename)}"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return key

    def put(self, key: str, content: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def _path(self, key: str) -> Path:
        path = (self.base_dir / key).resolve()
        if not path.is_relative_to(self.base_dir.resolve()):
            raise ValueError("Clave de almacenamiento inválida")
        return path
