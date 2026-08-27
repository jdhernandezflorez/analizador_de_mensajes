"""Entra al curso que elija el usuario, recorre las lecciones y guarda comentarios.

Reutiliza la sesión de login.py y solo vuelve a autenticar si expiró.
Entra a la primera lección, pulsa «Siguiente» hasta «Felicidades! ¡Has
completado el curso!» y en cada clase junta los comentarios con
data-depth="0" (incluye pulsar «Ver más»).

El resultado queda en comentarios/<nombre_del_curso>.json, pensado para
enviarlo después a una IA.

Uso:
    python entrar_curso.py
    python entrar_curso.py --curso "Fundamentos De Power Bi"
    python entrar_curso.py --curso 161029 --headless
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from login import abrir_contexto, asegurar_sesion
from rutas import DIR_COMENTARIOS, RAIZ, nombre_archivo_curso, normalizar

ARCHIVO_CURSOS = RAIZ / "id_cursos.json"
SELECTOR_BANNER = "div.poster[data-id]"
SELECTOR_SECCION = (
    "div.section.group.mb-6.w-full.rounded-lg.border.border-border.bg-card.shadow-subtle"
)
SELECTOR_LISTA = "div.overflow-hidden.rounded-b-lg.transition-height.duration-300"
SELECTOR_LECCION = "li[data-id]"
SELECTOR_TITULO = "h2.content__title"
SELECTOR_SIGUIENTE = 'a[data-tippy-content="Siguiente"]'
SELECTOR_COMENTARIO_RAIZ = 'div.comment[data-depth="0"]'
SELECTOR_VER_MAS = "#comments__paginate"
TITULO_FINAL = "Felicidades! ¡Has completado el curso!"
MAX_CLASES = 500
MAX_VER_MAS = 500


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


def elegir_curso(
    cursos: list[dict[str, str]],
    consulta: str | None,
) -> dict[str, str]:
    if consulta:
        hallados = coincidencias(cursos, consulta, "nombre_curso")
        if len(hallados) == 1:
            return hallados[0]
        if not hallados:
            raise SystemExit(f"No se encontró el curso que coincida con: {consulta}")
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
            raise SystemExit("No se recibió el curso") from None

        hallados = coincidencias(cursos, respuesta, "nombre_curso")
        if len(hallados) == 1:
            return hallados[0]
        if not hallados:
            print("No hay coincidencias. Intenta de nuevo.")
            continue

        print(f"\nHay {len(hallados)} coincidencias:\n")
        cursos = hallados
        mostrar_cursos(cursos)


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
              resultado.push({
                data_id: li.getAttribute("data-id") || "",
                titulo: (enlace?.innerText || li.innerText || "").trim(),
                seccion: tituloSeccion,
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


def es_clase_final(titulo: str) -> bool:
    return normalizar(TITULO_FINAL) in normalizar(titulo)


def leer_titulo_clase(page: Page) -> str:
    try:
        page.wait_for_selector(SELECTOR_TITULO, timeout=20_000)
    except PlaywrightTimeoutError:
        page.screenshot(path=str(RAIZ / "titulo_clase_no_encontrado.png"))
        raise SystemExit(
            "No apareció el título de la clase. "
            "Revisa la captura titulo_clase_no_encontrado.png"
        ) from None
    return page.locator(SELECTOR_TITULO).inner_text().strip()


def guardar_json(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".json.tmp")
    temporal.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporal.replace(ruta)


def expandir_comentarios(page: Page) -> None:
    """Pulsa «Ver más» hasta que el botón desaparezca."""
    try:
        page.wait_for_selector("#comments", timeout=15_000)
    except PlaywrightTimeoutError:
        return

    clics = 0
    while clics < MAX_VER_MAS:
        boton = page.locator(SELECTOR_VER_MAS)
        if boton.count() == 0 or not boton.first.is_visible():
            return

        n_antes = page.locator(SELECTOR_COMENTARIO_RAIZ).count()
        href_antes = boton.first.get_attribute("href") or ""
        boton.first.scroll_into_view_if_needed()
        boton.first.click()
        clics += 1
        try:
            page.wait_for_function(
                """([selector, n, href, selectorBoton]) => {
                  const boton = document.querySelector(selectorBoton);
                  const cantidad = document.querySelectorAll(selector).length;
                  const hrefAhora = boton ? boton.getAttribute("href") || "" : "";
                  return cantidad > n || !boton || hrefAhora !== href;
                }""",
                arg=[SELECTOR_COMENTARIO_RAIZ, n_antes, href_antes, SELECTOR_VER_MAS],
                timeout=20_000,
            )
        except PlaywrightTimeoutError:
            if page.locator(SELECTOR_VER_MAS).count() == 0:
                return
            print(
                "El botón «Ver más» no cargó más comentarios; se continúa con lo visible",
                file=sys.stderr,
            )
            return


def extraer_comentarios_raiz(page: Page) -> list[dict[str, str]]:
    comentarios = page.evaluate(
        """(selector) => {
          return [...document.querySelectorAll(selector)].map((el) => ({
            id: (el.id || "").replace(/^comment_/, ""),
            autor: el.querySelector(".comment__user span.font-semibold")
              ?.innerText?.trim() || "",
            fecha: el.querySelector("time")?.getAttribute("datetime") || "",
            texto: (el.querySelector(".comment__content")?.innerText || "").trim(),
          }));
        }""",
        SELECTOR_COMENTARIO_RAIZ,
    )
    unicos: list[dict[str, str]] = []
    vistos: set[str] = set()
    for comentario in comentarios:
        clave = comentario.get("id") or ""
        if clave and clave in vistos:
            continue
        if clave:
            vistos.add(clave)
        unicos.append(comentario)
    return unicos


def recoger_comentarios_clase(page: Page) -> list[dict[str, str]]:
    expandir_comentarios(page)
    return extraer_comentarios_raiz(page)


def ir_a_siguiente_clase(page: Page) -> bool:
    boton = page.locator(SELECTOR_SIGUIENTE).first
    if boton.count() == 0:
        return False

    href = (boton.get_attribute("href") or "").strip()
    if href in ("", "#"):
        return False

    url_antes = page.url
    boton.click()
    try:
        page.wait_for_url(lambda url: url != url_antes, timeout=20_000)
    except PlaywrightTimeoutError:
        page.screenshot(path=str(RAIZ / "siguiente_clase_fallida.png"))
        raise SystemExit(
            "Se pulsó «Siguiente» pero no cambió la clase. "
            "Revisa la captura siguiente_clase_fallida.png"
        ) from None
    return True


def recorrer_clases(page: Page, datos: dict, ruta: Path) -> None:
    visitadas = 0
    while True:
        titulo = leer_titulo_clase(page)
        visitadas += 1
        print(f"Clase {visitadas}: {titulo}")
        print(f"URL actual: {page.url}")

        comentarios = recoger_comentarios_clase(page)
        datos["clases"].append(
            {
                "titulo": titulo,
                "url": page.url,
                "comentarios": comentarios,
            }
        )
        guardar_json(ruta, datos)
        print(f"  {len(comentarios)} comentarios raíz guardados en {ruta.name}")

        if es_clase_final(titulo):
            print("Llegó a la clase final del curso")
            return

        if visitadas >= MAX_CLASES:
            raise SystemExit(
                f"Se recorrieron {MAX_CLASES} clases sin encontrar "
                f"«{TITULO_FINAL}»"
            )

        if not ir_a_siguiente_clase(page):
            page.screenshot(path=str(RAIZ / "sin_boton_siguiente.png"))
            raise SystemExit(
                "No hay botón «Siguiente» y aún no es la clase final. "
                f"Último título: {titulo}. "
                "Revisa la captura sin_boton_siguiente.png"
            )


def recolectar_comentarios(
    curso: str | None = None,
    *,
    headless: bool = False,
    forzar_login: bool = False,
    mantener_abierto: bool = False,
) -> Path:
    """Recorre el curso y guarda los comentarios. Devuelve la ruta del JSON."""
    cursos = cargar_cursos()
    elegido = elegir_curso(cursos, curso)
    print(f"Entrando a: {elegido['nombre_curso']} (data-id {elegido['data_id']})")

    ruta_salida = DIR_COMENTARIOS / nombre_archivo_curso(elegido["nombre_curso"])
    datos = {
        "curso": elegido["nombre_curso"],
        "data_id": elegido["data_id"],
        "clases": [],
    }

    with sync_playwright() as p:
        navegador, contexto = abrir_contexto(
            p,
            headless=headless,
            usar_sesion_guardada=not forzar_login,
        )
        page = contexto.new_page()

        try:
            asegurar_sesion(page, contexto, forzar=forzar_login)
            esperar_banners(page)
            entrar_al_banner(page, elegido)
            print("Curso abierto")
            print(f"URL actual: {page.url}")

            esperar_secciones(page)
            lecciones = extraer_lecciones(page)
            primera = lecciones[0]
            print(
                f"Entrando a la primera lección: {primera['titulo']} "
                f"[{primera['seccion']}]"
            )
            entrar_a_leccion(page, primera)
            recorrer_clases(page, datos, ruta_salida)
            print(f"Comentarios guardados en {ruta_salida}")

            if mantener_abierto:
                input("Presiona Enter para cerrar el navegador...")
        except SystemExit as exc:
            if exc.code not in (None, 0):
                print(exc, file=sys.stderr)
                raise SystemExit(1) from exc
            raise
        finally:
            contexto.close()
            navegador.close()

    return ruta_salida


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Entra a un curso, recorre las lecciones y guarda comentarios."
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

    try:
        recolectar_comentarios(
            args.curso,
            headless=args.headless,
            forzar_login=args.forzar_login,
            mantener_abierto=args.mantener_abierto,
        )
    except SystemExit as exc:
        if exc.code not in (None, 0):
            return 1 if isinstance(exc.code, int) else 1
        raise

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
