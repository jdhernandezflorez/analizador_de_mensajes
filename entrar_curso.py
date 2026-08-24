"""Entra al curso que elija el usuario desde la página principal.

Reutiliza la sesión de login.py y solo vuelve a autenticar si expiró.

Uso:
    python entrar_curso.py
    python entrar_curso.py --curso "Fundamentos De Power Bi"
    python entrar_curso.py --curso 161029 --headless
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from login import RAIZ, abrir_contexto, asegurar_sesion

ARCHIVO_CURSOS = RAIZ / "id_cursos.json"
SELECTOR_BANNER = "div.poster[data-id]"


def normalizar(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def cargar_cursos() -> list[dict[str, str]]:
    if not ARCHIVO_CURSOS.exists():
        raise SystemExit(f"No se encontró {ARCHIVO_CURSOS.name}")

    datos = json.loads(ARCHIVO_CURSOS.read_text(encoding="utf-8"))
    cursos = datos.get("cursos")
    if not cursos:
        raise SystemExit(f"{ARCHIVO_CURSOS.name} no tiene cursos")
    return cursos


def mostrar_cursos(cursos: list[dict[str, str]]) -> None:
    ancho = len(str(len(cursos)))
    print("\nCursos disponibles:\n")
    for indice, curso in enumerate(cursos, start=1):
        print(f"  {indice:>{ancho}}. {curso['nombre_curso']}")
    print()


def coincidencias(cursos: list[dict[str, str]], consulta: str) -> list[dict[str, str]]:
    consulta = consulta.strip()
    if not consulta:
        return []

    if consulta.isdigit():
        numero = int(consulta)
        if 1 <= numero <= len(cursos):
            return [cursos[numero - 1]]
        por_id = [curso for curso in cursos if curso["data_id"] == consulta]
        if por_id:
            return por_id

    buscado = normalizar(consulta)
    exactas = [
        curso for curso in cursos if normalizar(curso["nombre_curso"]) == buscado
    ]
    if exactas:
        return exactas

    return [
        curso
        for curso in cursos
        if buscado in normalizar(curso["nombre_curso"])
        or buscado == curso["data_id"]
    ]


def elegir_curso(
    cursos: list[dict[str, str]],
    consulta: str | None = None,
) -> dict[str, str]:
    if consulta:
        hallados = coincidencias(cursos, consulta)
        if len(hallados) == 1:
            return hallados[0]
        if not hallados:
            raise SystemExit(f"No se encontró un curso que coincida con: {consulta}")
        print(f"Hay {len(hallados)} coincidencias para «{consulta}»:\n")
        cursos = hallados
        mostrar_cursos(cursos)
    else:
        mostrar_cursos(cursos)

    while True:
        try:
            respuesta = input(
                "Escribe el número, parte del nombre o el data-id del curso: "
            ).strip()
        except EOFError:
            raise SystemExit("No se recibió un curso") from None

        hallados = coincidencias(cursos, respuesta)
        if len(hallados) == 1:
            return hallados[0]
        if not hallados:
            print("No hay coincidencias. Intenta de nuevo.")
            continue

        print(f"\nHay {len(hallados)} coincidencias:\n")
        cursos = hallados
        mostrar_cursos(cursos)


def esperar_banners(page: Page) -> None:
    page.wait_for_selector(SELECTOR_BANNER, timeout=20_000)


def entrar_al_banner(page: Page, curso: dict[str, str]) -> None:
    data_id = curso["data_id"]
    banner = page.locator(f"{SELECTOR_BANNER}[data-id='{data_id}'] a").first

    try:
        banner.wait_for(state="attached", timeout=10_000)
    except PlaywrightTimeoutError:
        raise SystemExit(
            f"No apareció el banner del curso «{curso['nombre_curso']}» "
            f"(data-id {data_id})"
        ) from None

    banner.scroll_into_view_if_needed()
    banner.click()

    try:
        page.wait_for_url(f"**/{data_id}-**", timeout=20_000)
    except PlaywrightTimeoutError:
        if data_id not in page.url:
            page.screenshot(path=str(RAIZ / "entrada_curso_fallida.png"))
            raise SystemExit(
                "Se hizo clic en el banner pero no se abrió el curso. "
                "Revisa la captura entrada_curso_fallida.png"
            ) from None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Entra a un curso de la página principal."
    )
    parser.add_argument(
        "--curso",
        help="número, nombre (o parte) o data-id del curso",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="ejecuta el navegador sin interfaz gráfica",
    )
    parser.add_argument(
        "--forzar-login",
        action="store_true",
        help="ignora la sesión guardada y vuelve a usar las credenciales",
    )
    parser.add_argument(
        "--mantener-abierto",
        action="store_true",
        help="espera un Enter antes de cerrar el navegador",
    )
    args = parser.parse_args()

    cursos = cargar_cursos()
    curso = elegir_curso(cursos, args.curso)
    print(f"Entrando a: {curso['nombre_curso']} (data-id {curso['data_id']})")

    with sync_playwright() as p:
        navegador, contexto = abrir_contexto(
            p,
            headless=args.headless,
            usar_sesion_guardada=not args.forzar_login,
        )
        page = contexto.new_page()

        try:
            asegurar_sesion(page, contexto, forzar=args.forzar_login)
            esperar_banners(page)
            entrar_al_banner(page, curso)

            print("Curso abierto")
            print(f"URL actual: {page.url}")

            if args.mantener_abierto:
                input("Presiona Enter para cerrar el navegador...")
        except SystemExit as exc:
            if exc.code not in (None, 0):
                print(exc, file=sys.stderr)
                return 1
            raise
        finally:
            contexto.close()
            navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
