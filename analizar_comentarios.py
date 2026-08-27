"""Categoriza las dudas de cada clase enviando solo los textos a Groq.

Lee un JSON de comentarios/, extrae el campo «texto» y pide a la IA que
agrupa las dudas de más a menos frecuentes.

Uso:
    python analizar_comentarios.py
    python analizar_comentarios.py --archivo comentarios/fundamentos_de_python.json
    python analizar_comentarios.py --curso "Fundamentos De Python" --limite 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from groq import Groq

from comentarios_io import extraer_textos, guardar_json, resolver_archivo_comentarios
from groq_cliente import (
    MODELO_POR_DEFECTO,
    cliente_groq,
    limpiar_para_prompt,
    llamar_groq,
    partir_en_lotes,
)
from rutas import DIR_ANALISIS


def categorizar_lote(
    cliente: Groq,
    modelo: str,
    titulo: str,
    textos: list[str],
) -> list[dict]:
    lineas = "\n".join(
        f"{i}. {limpiar_para_prompt(texto)}"
        for i, texto in enumerate(textos, start=1)
    )
    system = (
        "Eres un analista de comentarios de un curso online en español. "
        "Respondes únicamente con un objeto JSON válido. "
        "Sin markdown, sin etiquetas y sin texto fuera del JSON."
    )
    user = f"""Clase: {titulo}

Comentarios de estudiantes (solo texto):
{lineas}

Tarea:
- Extrae únicamente DUDAS, problemas o preguntas (errores, no me funciona, como hago, confusiones).
- Ignora saludos, agradecimientos, motivacion y comentarios que no sean una duda.
- Agrupa dudas equivalentes aunque esten escritas distinto.
- Ordena de la mas repetida a la menos repetida.
- En ejemplos usa parafrasis cortas, sin comillas dobles, sin emojis y de maximo 12 palabras.

Devuelve exactamente este esquema:
{{"categorias":[{{"duda":"resumen corto","frecuencia":3,"ejemplos":["parafrasis 1","parafrasis 2"]}}]}}

Si no hay dudas: {{"categorias":[]}}"""
    datos = llamar_groq(cliente, modelo, system, user)
    return _normalizar_categorias(datos.get("categorias", []))


def fusionar_categorias(
    cliente: Groq,
    modelo: str,
    titulo: str,
    grupos: list[list[dict]],
) -> list[dict]:
    if not grupos:
        return []
    if len(grupos) == 1:
        return sorted(grupos[0], key=lambda c: c["frecuencia"], reverse=True)

    payload = json.dumps(grupos, ensure_ascii=False, indent=2)
    system = (
        "Eres un analista de comentarios de un curso. "
        "Respondes únicamente con un objeto JSON válido, sin markdown."
    )
    user = f"""Clase: {titulo}

Estas listas son categorías de dudas extraídas de distintos lotes de la misma clase.
Fusiónalas: junta las que sean la misma duda, suma frecuencias y ordena de mayor a menor.

{payload}

JSON:
{{
  "categorias": [
    {{"duda": "...", "frecuencia": 10, "ejemplos": ["...", "..."]}}
  ]
}}"""
    datos = llamar_groq(cliente, modelo, system, user)
    return _normalizar_categorias(datos.get("categorias", []))


def _normalizar_categorias(categorias: object) -> list[dict]:
    if not isinstance(categorias, list):
        return []
    limpias = []
    for item in categorias:
        if not isinstance(item, dict):
            continue
        duda = str(
            item.get("duda") or item.get("name") or item.get("categoria") or ""
        ).strip()
        if not duda:
            continue
        try:
            frecuencia = int(
                item.get("frecuencia") or item.get("frequency") or 0
            )
        except (TypeError, ValueError):
            frecuencia = 0
        ejemplos = item.get("ejemplos") or item.get("examples") or []
        if not isinstance(ejemplos, list):
            ejemplos = [str(ejemplos)]
        ejemplos = [str(e).strip() for e in ejemplos if str(e).strip()][:3]
        limpias.append(
            {"duda": duda, "frecuencia": max(frecuencia, 1), "ejemplos": ejemplos}
        )
    limpias.sort(key=lambda c: c["frecuencia"], reverse=True)
    return limpias


def analizar_clase(
    cliente: Groq,
    modelo: str,
    clase: dict,
) -> dict:
    textos = clase["textos"]
    if not textos:
        return {
            "titulo": clase["titulo"],
            "url": clase["url"],
            "total_comentarios": 0,
            "categorias": [],
        }

    lotes = partir_en_lotes(textos)
    grupos = [categorizar_lote(cliente, modelo, clase["titulo"], lote) for lote in lotes]
    categorias = fusionar_categorias(cliente, modelo, clase["titulo"], grupos)
    return {
        "titulo": clase["titulo"],
        "url": clase["url"],
        "total_comentarios": len(textos),
        "categorias": categorias,
    }


def imprimir_clase(resultado: dict) -> None:
    print(f"\nClase: {resultado['titulo']}")
    print(f"  Comentarios analizados: {resultado['total_comentarios']}")
    if not resultado["categorias"]:
        print("  Sin dudas categorizadas")
        return
    for indice, cat in enumerate(resultado["categorias"], start=1):
        print(f"  {indice}. {cat['duda']}  ({cat['frecuencia']})")


def analizar_archivo(
    ruta_comentarios: Path,
    *,
    modelo: str = MODELO_POR_DEFECTO,
    limite: int | None = None,
) -> Path:
    datos = json.loads(ruta_comentarios.read_text(encoding="utf-8"))
    clases = extraer_textos(datos)
    if limite is not None:
        clases = clases[:limite]

    cliente = cliente_groq()
    ruta_salida = DIR_ANALISIS / ruta_comentarios.name
    resultado = {
        "curso": datos.get("curso") or ruta_comentarios.stem,
        "data_id": datos.get("data_id") or "",
        "modelo": modelo,
        "clases": [],
    }

    print(f"Analizando {len(clases)} clases de «{resultado['curso']}» con {modelo}")
    for indice, clase in enumerate(clases, start=1):
        print(
            f"\n[{indice}/{len(clases)}] {clase['titulo']} "
            f"({len(clase['textos'])} textos)"
        )
        analisis = analizar_clase(cliente, modelo, clase)
        resultado["clases"].append(analisis)
        guardar_json(ruta_salida, resultado)
        imprimir_clase(analisis)

    print(f"\nAnálisis guardado en {ruta_salida}")
    return ruta_salida


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Categoriza dudas de estudiantes con Groq."
    )
    parser.add_argument(
        "--archivo",
        help="JSON de comentarios (por defecto el de comentarios/)",
    )
    parser.add_argument(
        "--curso",
        help="nombre del curso para localizar comentarios/<curso>.json",
    )
    parser.add_argument(
        "--modelo",
        default=MODELO_POR_DEFECTO,
        help=f"modelo de Groq (por defecto {MODELO_POR_DEFECTO})",
    )
    parser.add_argument(
        "--limite",
        type=int,
        help="analiza solo las primeras N clases",
    )
    args = parser.parse_args()

    try:
        ruta = resolver_archivo_comentarios(args.archivo, args.curso)
        analizar_archivo(ruta, modelo=args.modelo, limite=args.limite)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc, file=sys.stderr)
            return 1 if not isinstance(exc.code, int) else exc.code
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
