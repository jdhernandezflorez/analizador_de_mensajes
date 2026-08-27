"""Acceso compartido a Groq: credenciales, lotes, llamadas y parseo de JSON.

El plan gratuito limita los tokens por minuto y cuenta prompt + respuesta en
la misma petición, por eso los lotes son pequeños y la respuesta va acotada.
"""

from __future__ import annotations

import json
import re
import time

from dotenv import dotenv_values
from groq import Groq

from rutas import RAIZ

MODELO_POR_DEFECTO = "openai/gpt-oss-20b"
MAX_CHARS_LOTE = 3_500
MAX_TOKENS_RESPUESTA = 4_000
MAX_REINTENTOS = 5


def cargar_api_groq() -> str:
    archivo_env = RAIZ / ".env"
    if not archivo_env.exists():
        raise SystemExit(f"No se encontró el archivo {archivo_env}")

    valores = dotenv_values(archivo_env)
    clave = valores.get("API_GROQ")
    if not clave:
        raise SystemExit("Falta la variable API_GROQ en el .env")
    return clave


def cliente_groq() -> Groq:
    return Groq(api_key=cargar_api_groq())


def limpiar_para_prompt(texto: str) -> str:
    texto = texto.replace('"', "'").replace("\n", " ").replace("\r", " ")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:400]


def partir_en_lotes(
    textos: list[str],
    max_chars: int = MAX_CHARS_LOTE,
) -> list[list[str]]:
    lotes: list[list[str]] = []
    actual: list[str] = []
    chars = 0
    for texto in textos:
        extra = len(texto) + 8
        if actual and chars + extra > max_chars:
            lotes.append(actual)
            actual = []
            chars = 0
        actual.append(texto)
        chars += extra
    if actual:
        lotes.append(actual)
    return lotes


def parsear_json(contenido: str) -> dict:
    contenido = re.sub(r"<think>.*?</think>", "", contenido, flags=re.S | re.I).strip()
    if contenido.startswith("```"):
        contenido = re.sub(r"^```(?:json)?\s*", "", contenido)
        contenido = re.sub(r"\s*```$", "", contenido)
    try:
        return json.loads(contenido)
    except json.JSONDecodeError:
        inicio = contenido.find("{")
        fin = contenido.rfind("}")
        if inicio >= 0 and fin > inicio:
            return json.loads(contenido[inicio : fin + 1])
        raise


def llamar_groq(cliente: Groq, modelo: str, system: str, user: str) -> dict:
    ultimo_error: Exception | None = None
    espera = 2.0
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            respuesta = cliente.chat.completions.create(
                model=modelo,
                temperature=0.2,
                max_completion_tokens=MAX_TOKENS_RESPUESTA,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            mensaje = respuesta.choices[0].message
            contenido = mensaje.content or ""
            # Los modelos de razonamiento a veces dejan el JSON en «reasoning».
            if not contenido.strip():
                contenido = getattr(mensaje, "reasoning", None) or ""
            return parsear_json(contenido)
        except json.JSONDecodeError as exc:
            ultimo_error = exc
            print(f"  JSON inválido, reintento {intento}/{MAX_REINTENTOS}")
            time.sleep(1)
            continue
        except Exception as exc:
            ultimo_error = exc
            detalle = str(exc).lower()
            if (
                "rate limit" in detalle
                or "429" in detalle
                or "413" in detalle
                or "too many" in detalle
                or "rate_limit_exceeded" in detalle
                or "tokens per minute" in detalle
            ):
                print(
                    f"  Límite de Groq, reintento {intento}/{MAX_REINTENTOS} "
                    f"en {espera:.0f}s"
                )
                time.sleep(espera)
                espera = min(espera * 2, 60)
                continue
            raise
    raise SystemExit(f"Groq no respondió tras varios reintentos: {ultimo_error}")
