"""Inicio de sesión en la plataforma usando las credenciales del archivo .env.

Uso:
    python login.py              # abre el navegador visible y deja la sesión guardada
    python login.py --headless   # sin interfaz gráfica
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

RAIZ = Path(__file__).resolve().parent
ARCHIVO_SESION = RAIZ / "estado_sesion.json"

SELECTOR_EMAIL = "#user_email, input[name='user[email]']"
SELECTOR_PASSWORD = "#user_password, input[name='user[password]']"
SELECTOR_SUBMIT = (
    "input[type='submit'], button[type='submit'], form button:not([type='button'])"
)


def cargar_credenciales() -> tuple[str, str, str]:
    archivo_env = RAIZ / ".env"
    if not archivo_env.exists():
        raise SystemExit(f"No se encontró el archivo {archivo_env}")

    # dotenv_values lee solo el archivo: evita que USER del sistema tape el del .env.
    valores = dotenv_values(archivo_env)

    faltantes = [clave for clave in ("URL", "USER", "PASSWORD") if not valores.get(clave)]
    if faltantes:
        raise SystemExit("Faltan variables en el .env: " + ", ".join(faltantes))

    return valores["URL"], valores["USER"], valores["PASSWORD"]


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Login en la plataforma de cursos.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="ejecuta el navegador sin interfaz gráfica",
    )
    parser.add_argument(
        "--mantener-abierto",
        action="store_true",
        help="espera un Enter antes de cerrar el navegador",
    )
    args = parser.parse_args()

    url, usuario, password = cargar_credenciales()

    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=args.headless)
        contexto = navegador.new_context()
        page = contexto.new_page()

        try:
            iniciar_sesion(page, url, usuario, password)

            if not sesion_activa(page):
                page.screenshot(path=str(RAIZ / "login_fallido.png"))
                print(
                    "No se pudo iniciar sesión. Revisa las credenciales del .env "
                    "y la captura login_fallido.png",
                    file=sys.stderr,
                )
                return 1

            contexto.storage_state(path=str(ARCHIVO_SESION))
            print("Sesión iniciada correctamente")
            print(f"URL actual: {page.url}")
            print(f"Sesión guardada en {ARCHIVO_SESION.name}")

            if args.mantener_abierto:
                input("Presiona Enter para cerrar el navegador...")
        finally:
            contexto.close()
            navegador.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
