"""Rutas y nombres de archivo compartidos."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DIR_COMENTARIOS = RAIZ / "comentarios"
DIR_ANALISIS = RAIZ / "analisis"
DIR_INQUIETUDES = RAIZ / "inquietudes"


def normalizar(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def nombre_archivo_curso(nombre: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalizar(nombre)).strip("_")
    return f"{slug or 'curso'}.json"
