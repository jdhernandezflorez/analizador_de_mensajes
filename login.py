"""Inicio de sesión en la plataforma usando las credenciales del archivo .env.

Reutiliza estado_sesion.json si sigue vigente. Solo completa el formulario
cuando no hay sesión o cuando ya expiró.

Uso:
    python login.py              # reutiliza la sesión guardada si es válida
    python login.py --forzar     # vuelve a autenticar con el .env
    python login.py --headless   # sin interfaz gráfica
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

RAIZ = Path(__file__).resolve().parent
ARCHIVO_SESION = RAIZ / "estado_sesion.json"

SELECTOR_EMAIL = "#user_email, input[name='user[email]']"
SELECTOR_PASSWORD = "#user_password, input[name='user[password]']"
SELECTOR_SUBMIT = (
    "input[type='submit'], button[type='submit'], form button:not([type='button'])"
)


def _valores_env() -> dict[str, str | None]:
    archivo_env = RAIZ / ".env"
    if not archivo_env.exists():
        raise SystemExit(f"No se encontró el archivo {archivo_env}")

    # dotenv_values lee solo el archivo: evita que USER del sistema tape el del .env.
    return dotenv_values(archivo_env)


def cargar_url() -> str:
    valores = _valores_env()
    url = valores.get("URL")
    if not url:
        raise SystemExit("Falta la variable URL en el .env")
    return url


def cargar_credenciales() -> tuple[str, str, str]:
    valores = _valores_env()

    faltantes = [clave for clave in ("URL", "USER", "PASSWORD") if not valores.get(clave)]
    if faltantes:
        raise SystemExit("Faltan variables en el .env: " + ", ".join(faltantes))

    return valores["URL"], valores["USER"], valores["PASSWORD"]


def pagina_pide_login(page: Page) -> bool:
    return page.locator(SELECTOR_PASSWORD).count() > 0


def abrir_formulario(page: Page, url: str) -> None:
    """Abre la URL del .env y, si no trae el formulario, prueba la ruta de login."""
    page.goto(url, wait_until="load")
    try:
        page.wait_for_selector(SELECTOR_EMAIL, timeout=15_000)
        return
    except PlaywrightTimeoutError:
        pass

    url_login = url.rstrip("/") + "/users/sign_in"
    page.goto(url_login, wait_until="load")
    page.wait_for_selector(SELECTOR_EMAIL, timeout=15_000)


def iniciar_sesion(page: Page, url: str, usuario: str, password: str) -> None:
    if page.locator(SELECTOR_EMAIL).count() == 0:
        abrir_formulario(page, url)

    page.fill(SELECTOR_EMAIL, usuario)
    page.fill(SELECTOR_PASSWORD, password)

    if page.query_selector(SELECTOR_SUBMIT):
        page.click(SELECTOR_SUBMIT)
    else:
        page.press(SELECTOR_PASSWORD, "Enter")

    page.wait_for_load_state("networkidle")


def sesion_activa(page: Page) -> bool:
    """La sesión es válida si el campo de contraseña ya no está en la página."""
    try:
        page.wait_for_selector(SELECTOR_PASSWORD, state="detached", timeout=15_000)
    except PlaywrightTimeoutError:
        return False
    return True


def guardar_sesion(contexto: BrowserContext) -> None:
    contexto.storage_state(path=str(ARCHIVO_SESION))


def abrir_contexto(
    playwright: Playwright,
    *,
    headless: bool = False,
    usar_sesion_guardada: bool = True,
) -> tuple[Browser, BrowserContext]:
    """Abre Chromium reutilizando la sesión guardada, si existe."""
    navegador = playwright.chromium.launch(headless=headless)
    opciones: dict = {}
    if usar_sesion_guardada and ARCHIVO_SESION.exists():
        opciones["storage_state"] = str(ARCHIVO_SESION)
    contexto = navegador.new_context(**opciones)
    return navegador, contexto


def _login_con_credenciales(page: Page, contexto: BrowserContext, url: str) -> None:
    _, usuario, password = cargar_credenciales()
    iniciar_sesion(page, url, usuario, password)

    if not sesion_activa(page):
        page.screenshot(path=str(RAIZ / "login_fallido.png"))
        raise SystemExit(
            "No se pudo iniciar sesión. Revisa las credenciales del .env "
            "y la captura login_fallido.png"
        )

    guardar_sesion(contexto)
    print("Sesión iniciada con credenciales")
    print(f"Sesión guardada en {ARCHIVO_SESION.name}")


def asegurar_sesion(
    page: Page,
    contexto: BrowserContext,
    *,
    url: str | None = None,
    forzar: bool = False,
) -> str:
    """Deja la página autenticada. Solo usa USER/PASSWORD si hace falta.

    Returns:
        La URL base de la plataforma.
    """
    if url is None:
        url = cargar_url()

    page.goto(url, wait_until="load")

    if forzar or pagina_pide_login(page):
        _login_con_credenciales(page, contexto, url)
    else:
        guardar_sesion(contexto)
        print("Sesión guardada vigente; no hace falta volver a autenticar")

    return url


def main() -> int:
    parser = argparse.ArgumentParser(description="Login en la plataforma de cursos.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="ejecuta el navegador sin interfaz gráfica",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="ignora la sesión guardada y vuelve a usar las credenciales",
    )
    parser.add_argument(
        "--mantener-abierto",
        action="store_true",
        help="espera un Enter antes de cerrar el navegador",
    )
    args = parser.parse_args()

    with sync_playwright() as p:
        navegador, contexto = abrir_contexto(
            p,
            headless=args.headless,
            usar_sesion_guardada=not args.forzar,
        )
        page = contexto.new_page()

        try:
            asegurar_sesion(page, contexto, forzar=args.forzar)
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
