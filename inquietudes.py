"""Detecta las principales inquietudes e inconformidades de cada clase.

Lee un JSON de comentarios/, se queda solo con el campo «texto» y le pide a
Groq las 5 más repetidas por clase (menos si no hay tantas).

Uso:
    python inquietudes.py --curso "Fundamentos De Python"
    python inquietudes.py --archivo comentarios/fundamentos_de_python.json
    python inquietudes.py --curso "Fundamentos De Python" --limite 3
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
from rutas import DIR_INQUIETUDES

TOP_POR_CLASE = 5
GRUPOS_POR_FUSION = 4

SYSTEM = (
    "Eres un analista de la experiencia de estudiantes en una plataforma de "
    "cursos online en español. Escribes siempre en español. Respondes "
    "únicamente con un objeto JSON válido, sin markdown, sin etiquetas y sin "
    "texto fuera del JSON."
)


def _prompt_extraccion(titulo: str, textos: list[str], top: int) -> str:
    lineas = "\n".join(
        f"{i}. {limpiar_para_prompt(texto)}"
        for i, texto in enumerate(textos, start=1)
    )
    return f"""Clase: {titulo}

Comentarios de estudiantes (solo texto):
{lineas}

Tarea:
- Detecta INQUIETUDES (dudas, preguntas, preocupaciones) e INCONFORMIDADES
  (quejas, molestias, cosas que fallan o faltan) sobre la plataforma, el
  contenido, los videos, los materiales, el soporte o la forma de enseñar.
- Ignora saludos, agradecimientos, elogios y comentarios de motivacion.
- Agrupa las que signifiquen lo mismo aunque esten escritas distinto.
- Ordena de la mas repetida a la menos repetida.
- Devuelve como maximo {top}. Si hay menos, devuelve solo las que encuentres.
- Escribe tema y ejemplos en español, aunque el comentario venga en otro idioma.
- En ejemplos usa parafrasis cortas, sin comillas dobles, sin emojis y de
  maximo 12 palabras.

Devuelve exactamente este esquema:
{{"inquietudes":[{{"tema":"resumen corto","tipo":"inquietud","frecuencia":3,"ejemplos":["parafrasis 1"]}}]}}

El campo tipo solo puede ser inquietud o inconformidad.
Si no hay ninguna: {{"inquietudes":[]}}"""


def _prompt_fusion(titulo: str, grupos: list[list[dict]], top: int) -> str:
    payload = json.dumps(grupos, ensure_ascii=False)
    return f"""Clase: {titulo}

Cada lista viene de un lote distinto de comentarios de la misma clase.

{payload}

Tarea:
- Fusiona las entradas que signifiquen lo mismo y suma sus frecuencias.
- Ordena de la mas repetida a la menos repetida.
- Devuelve como maximo {top}.
- Escribe tema y ejemplos en español.

Devuelve exactamente este esquema:
{{"inquietudes":[{{"tema":"resumen corto","tipo":"inquietud","frecuencia":8,"ejemplos":["parafrasis 1"]}}]}}"""


def normalizar_inquietudes(valor: object) -> list[dict]:
    if not isinstance(valor, list):
        return []

    limpias: list[dict] = []
    for item in valor:
        if not isinstance(item, dict):
            continue
        tema = str(
            item.get("tema") or item.get("titulo") or item.get("name") or ""
        ).strip()
        if not tema:
            continue

        tipo = str(item.get("tipo") or item.get("type") or "").strip().lower()
        if tipo not in ("inquietud", "inconformidad"):
            tipo = "inquietud"

        try:
            frecuencia = int(item.get("frecuencia") or item.get("frequency") or 0)
        except (TypeError, ValueError):
            frecuencia = 0

        ejemplos = item.get("ejemplos") or item.get("examples") or []
        if not isinstance(ejemplos, list):
            ejemplos = [str(ejemplos)]
        ejemplos = [str(e).strip() for e in ejemplos if str(e).strip()][:3]

        limpias.append(
            {
                "tema": tema,
                "tipo": tipo,
                "frecuencia": max(frecuencia, 1),
                "ejemplos": ejemplos,
            }
        )

    limpias.sort(key=lambda item: item["frecuencia"], reverse=True)
    return limpias


def extraer_de_lote(
    cliente: Groq,
    modelo: str,
    titulo: str,
    textos: list[str],
    top: int,
) -> list[dict]:
    datos = llamar_groq(cliente, modelo, SYSTEM, _prompt_extraccion(titulo, textos, top))
    return normalizar_inquietudes(datos.get("inquietudes"))[:top]


def fusionar(
    cliente: Groq,
    modelo: str,
    titulo: str,
    grupos: list[list[dict]],
    top: int,
) -> list[dict]:
    """Une los resultados de cada lote por bloques, para no pasarse de tokens."""
    pendientes = [grupo for grupo in grupos if grupo]
    if not pendientes:
        return []

    while len(pendientes) > 1:
        ronda: list[list[dict]] = []
        for inicio in range(0, len(pendientes), GRUPOS_POR_FUSION):
            bloque = pendientes[inicio : inicio + GRUPOS_POR_FUSION]
            if len(bloque) == 1:
                ronda.append(bloque[0])
                continue
            datos = llamar_groq(
                cliente,
                modelo,
                SYSTEM,
                _prompt_fusion(titulo, bloque, top),
            )
            fusionado = normalizar_inquietudes(datos.get("inquietudes"))[:top]
            ronda.append(fusionado or [item for grupo in bloque for item in grupo][:top])
        pendientes = ronda

    return pendientes[0][:top]


def analizar_clase(
    cliente: Groq,
    modelo: str,
    clase: dict,
    top: int = TOP_POR_CLASE,
) -> dict:
    base = {
        "titulo": clase["titulo"],
        "url": clase["url"],
        "total_comentarios": len(clase["textos"]),
    }
    if not clase["textos"]:
        return {**base, "inquietudes": []}

    lotes = partir_en_lotes(clase["textos"])
    grupos = [
        extraer_de_lote(cliente, modelo, clase["titulo"], lote, top) for lote in lotes
    ]
    return {**base, "inquietudes": fusionar(cliente, modelo, clase["titulo"], grupos, top)}


def imprimir_clase(resultado: dict) -> None:
    print(f"\nClase: {resultado['titulo']}")
    print(f"  Comentarios analizados: {resultado['total_comentarios']}")
    if not resultado["inquietudes"]:
        print("  Sin inquietudes ni inconformidades")
        return
    for indice, item in enumerate(resultado["inquietudes"], start=1):
        print(
            f"  {indice}. [{item['tipo']}] {item['tema']}  "
            f"({item['frecuencia']})"
        )


def analizar_archivo(
    ruta_comentarios: Path,
    *,
    modelo: str = MODELO_POR_DEFECTO,
    limite: int | None = None,
    top: int = TOP_POR_CLASE,
) -> Path:
    datos = json.loads(ruta_comentarios.read_text(encoding="utf-8"))
    clases = extraer_textos(datos)
    if limite is not None:
        clases = clases[:limite]

    cliente = cliente_groq()
    ruta_salida = DIR_INQUIETUDES / ruta_comentarios.name
    resultado = {
        "curso": datos.get("curso") or ruta_comentarios.stem,
        "data_id": datos.get("data_id") or "",
        "modelo": modelo,
        "top_por_clase": top,
        "clases": [],
    }

    print(f"Revisando {len(clases)} clases de «{resultado['curso']}» con {modelo}")
    for indice, clase in enumerate(clases, start=1):
        print(
            f"\n[{indice}/{len(clases)}] {clase['titulo']} "
            f"({len(clase['textos'])} comentarios)"
        )
        analisis = analizar_clase(cliente, modelo, clase, top)
        resultado["clases"].append(analisis)
        guardar_json(ruta_salida, resultado)
        imprimir_clase(analisis)

    print(f"\nInquietudes guardadas en {ruta_salida}")
    return ruta_salida


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Top de inquietudes e inconformidades por clase, con Groq."
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
        help="revisa solo las primeras N clases",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=TOP_POR_CLASE,
        help=f"cuántas listar por clase (por defecto {TOP_POR_CLASE})",
    )
    args = parser.parse_args()

    try:
        ruta = resolver_archivo_comentarios(args.archivo, args.curso)
        analizar_archivo(
            ruta,
            modelo=args.modelo,
            limite=args.limite,
            top=args.top,
        )
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc, file=sys.stderr)
            return exc.code if isinstance(exc.code, int) else 1
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
