"""Entra al curso que elija el usuario y luego a una de sus lecciones.

Reutiliza la sesión de login.py y solo vuelve a autenticar si expiró.

Uso:
    python entrar_curso.py
    python entrar_curso.py --curso "Fundamentos De Power Bi"
    python entrar_curso.py --curso 161029 --leccion "¿Qué es Power BI?"
    python entrar_curso.py --curso 161029 --leccion 6 --headless
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
SELECTOR_SECCION = (
    "div.section.group.mb-6.w-full.rounded-lg.border.border-border.bg-card.shadow-subtle"
)
SELECTOR_LISTA = "div.overflow-hidden.rounded-b-lg.transition-height.duration-300"
SELECTOR_LECCION = "li[data-id]"


def normalizar(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def coincidencias(
    items: list[dict[str, str]],
    consulta: str,
    campo_nombre: str,
) -> list[dict[str, str]]:
    consulta = consulta.strip()
    if not consulta:
        return []

    if consulta.isdigit():
        numero = int(consulta)
        if 1 <= numero <= len(items):
            return [items[numero - 1]]
        por_id = [item for item in items if item["data_id"] == consulta]
        if por_id:
            return por_id

    buscado = normalizar(consulta)
    exactas = [
        item for item in items if normalizar(item[campo_nombre]) == buscado
    ]
    if exactas:
        return exactas

    return [
        item
        for item in items
        if buscado in normalizar(item[campo_nombre]) or buscado == item["data_id"]
    ]


def elegir_item(
    items: list[dict[str, str]],
    consulta: str | None,
    campo_nombre: str,
    etiqueta: str,
    mostrar,
) -> dict[str, str]:
    if consulta:
        hallados = coincidencias(items, consulta, campo_nombre)
        if len(hallados) == 1:
            return hallados[0]
        if not hallados:
            raise SystemExit(f"No se encontró {etiqueta} que coincida con: {consulta}")
        print(f"Hay {len(hallados)} coincidencias para «{consulta}»:\n")
        items = hallados
        mostrar(items)
    else:
        mostrar(items)

    while True:
        try:
            respuesta = input(
                f"Escribe el número, parte del nombre o el data-id de {etiqueta}: "
            ).strip()
        except EOFError:
            raise SystemExit(f"No se recibió {etiqueta}") from None

        hallados = coincidencias(items, respuesta, campo_nombre)
        if len(hallados) == 1:
            return hallados[0]
        if not hallados:
            print("No hay coincidencias. Intenta de nuevo.")
            continue

        print(f"\nHay {len(hallados)} coincidencias:\n")
        items = hallados
        mostrar(items)


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


def esperar_secciones(page: Page) -> None:
    try:
        page.wait_for_selector(SELECTOR_SECCION, timeout=20_000)
    except PlaywrightTimeoutError:
        page.screenshot(path=str(RAIZ / "secciones_no_encontradas.png"))
        raise SystemExit(
            "No aparecieron las secciones del curso. "
            "Revisa la captura secciones_no_encontradas.png"
        ) from None


def extraer_lecciones(page: Page) -> list[dict[str, str]]:
    lecciones = page.evaluate(
        """([selectorSeccion, selectorLista]) => {
          const secciones = [...document.querySelectorAll(selectorSeccion)];
          const resultado = [];
          for (const seccion of secciones) {
            const h4 = seccion.querySelector("h4");
            const tituloSeccion = (h4?.innerText || "")
              .split("\\n")
              .map((s) => s.trim())
              .find(Boolean) || "Sin sección";
            const lista = seccion.querySelector(selectorLista) || seccion;
            for (const li of lista.querySelectorAll("li[data-id]")) {
              const enlace = li.querySelector("a.lesson__title, a[href]");
              const duracion = (li.querySelector("small")?.innerText || "")
                .replace(/^\\s*-\\s*/, "")
                .trim();
              resultado.push({
                data_id: li.getAttribute("data-id") || "",
                titulo: (enlace?.innerText || li.innerText || "").trim(),
                duracion,
                seccion: tituloSeccion,
                href: enlace?.getAttribute("href") || "",
              });
            }
          }
          return resultado;
        }""",
        [SELECTOR_SECCION, SELECTOR_LISTA],
    )
    if not lecciones:
        raise SystemExit("El curso no tiene lecciones visibles en las secciones")
    return lecciones


def mostrar_lecciones(lecciones: list[dict[str, str]]) -> None:
    ancho = len(str(len(lecciones)))
    seccion_actual = None
    print("\nLecciones del curso:\n")
    for indice, leccion in enumerate(lecciones, start=1):
        if leccion["seccion"] != seccion_actual:
            seccion_actual = leccion["seccion"]
            print(f"  {seccion_actual}")
        extra = f"  ({leccion['duracion']})" if leccion.get("duracion") else ""
        print(f"  {indice:>{ancho}}. {leccion['titulo']}{extra}")
    print()


def expandir_seccion(page: Page, data_id: str) -> None:
    seccion = page.locator(SELECTOR_SECCION).filter(
        has=page.locator(f"{SELECTOR_LECCION}[data-id='{data_id}']")
    ).first
    encabezado = seccion.locator("h4").first
    if encabezado.count() == 0:
        return
    if encabezado.get_attribute("aria-expanded") == "false":
        encabezado.click()
        seccion.locator(
            f"{SELECTOR_LISTA} {SELECTOR_LECCION}[data-id='{data_id}']"
        ).first.wait_for(state="visible", timeout=10_000)


def entrar_a_leccion(page: Page, leccion: dict[str, str]) -> None:
    data_id = leccion["data_id"]
    expandir_seccion(page, data_id)

    item = page.locator(f"{SELECTOR_LISTA} {SELECTOR_LECCION}[data-id='{data_id}']").first
    try:
        item.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError:
        raise SystemExit(
            f"No apareció la lección «{leccion['titulo']}» (data-id {data_id})"
        ) from None

    item.scroll_into_view_if_needed()
    enlace = item.locator("a.lesson__title")
    if enlace.count():
        enlace.first.click()
    else:
        item.click()

    try:
        page.wait_for_url(f"**/{data_id}-**", timeout=20_000)
    except PlaywrightTimeoutError:
        if data_id not in page.url:
            page.screenshot(path=str(RAIZ / "entrada_leccion_fallida.png"))
            raise SystemExit(
                "Se hizo clic en la lección pero no se abrió el vídeo. "
                "Revisa la captura entrada_leccion_fallida.png"
            ) from None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Entra a un curso y a una de sus lecciones."
    )
    parser.add_argument(
        "--curso",
        help="número, nombre (o parte) o data-id del curso",
    )
    parser.add_argument(
        "--leccion",
        help="número, nombre (o parte) o data-id de la lección",
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
    curso = elegir_item(
        cursos,
        args.curso,
        "nombre_curso",
        "el curso",
        mostrar_cursos,
    )
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

            esperar_secciones(page)
            lecciones = extraer_lecciones(page)
            leccion = elegir_item(
                lecciones,
                args.leccion,
                "titulo",
                "la lección",
                mostrar_lecciones,
            )
            print(
                f"Entrando a: {leccion['titulo']} "
                f"[{leccion['seccion']}] (data-id {leccion['data_id']})"
            )
            entrar_a_leccion(page, leccion)

            print("Lección abierta")
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
