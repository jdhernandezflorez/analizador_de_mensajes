"""Lectura de los JSON de comentarios y escritura de resultados."""

from __future__ import annotations

import json
from pathlib import Path

from rutas import DIR_COMENTARIOS, RAIZ, nombre_archivo_curso


def resolver_archivo_comentarios(
    archivo: str | None,
    curso: str | None,
) -> Path:
    if archivo:
        ruta = Path(archivo)
        if not ruta.is_absolute():
            ruta = RAIZ / ruta
        if not ruta.exists():
            raise SystemExit(f"No se encontró {ruta}")
        return ruta

    if curso:
        candidato = DIR_COMENTARIOS / nombre_archivo_curso(curso)
        if candidato.exists():
            return candidato

    jsons = sorted(DIR_COMENTARIOS.glob("*.json"))
    jsons = [p for p in jsons if not p.name.startswith("_")]
    if not jsons:
        raise SystemExit(f"No hay JSON de comentarios en {DIR_COMENTARIOS}")
    if len(jsons) == 1:
        return jsons[0]

    print("Archivos de comentarios:\n")
    for indice, ruta in enumerate(jsons, start=1):
        print(f"  {indice}. {ruta.name}")
    print()
    try:
        respuesta = input("Elige el número del archivo: ").strip()
    except EOFError:
        raise SystemExit("No se recibió un archivo") from None
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(jsons):
        return jsons[int(respuesta) - 1]
    raise SystemExit("Selección inválida")


def extraer_textos(datos: dict) -> list[dict]:
    """Deja solo el campo «texto» de cada comentario, agrupado por clase."""
    clases = []
    for clase in datos.get("clases", []):
        textos = [
            (comentario.get("texto") or "").strip()
            for comentario in clase.get("comentarios", [])
        ]
        textos = [texto for texto in textos if texto]
        clases.append(
            {
                "titulo": clase.get("titulo") or "",
                "url": clase.get("url") or "",
                "textos": textos,
            }
        )
    return clases


def guardar_json(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporal.replace(ruta)
