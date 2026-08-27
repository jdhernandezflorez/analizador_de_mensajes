"""Punto de entrada del bot: login, scrape de comentarios y análisis con Groq.

Uso:
    python main.py scrape --curso "Fundamentos De Python"
    python main.py analizar --curso "Fundamentos De Python"
    python main.py analizar --archivo comentarios/fundamentos_de_python.json
    python main.py run --curso "Fundamentos De Python"
    python main.py login
"""

from __future__ import annotations

import argparse
import sys

import analizar_comentarios
import entrar_curso
import login


def _cmd_login(args: argparse.Namespace) -> int:
    sys.argv = ["login.py"]
    if args.headless:
        sys.argv.append("--headless")
    if args.forzar_login:
        sys.argv.append("--forzar")
    return login.main()


def _cmd_scrape(args: argparse.Namespace) -> int:
    try:
        entrar_curso.recolectar_comentarios(
            args.curso,
            headless=args.headless,
            forzar_login=args.forzar_login,
            mantener_abierto=args.mantener_abierto,
        )
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc, file=sys.stderr)
            return 1 if not isinstance(exc.code, int) else exc.code
        raise
    return 0


def _cmd_analizar(args: argparse.Namespace) -> int:
    try:
        ruta = analizar_comentarios.resolver_archivo_comentarios(
            getattr(args, "archivo", None),
            args.curso,
        )
        analizar_comentarios.analizar_archivo(
            ruta,
            modelo=args.modelo,
            limite=args.limite,
        )
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc, file=sys.stderr)
            return 1 if not isinstance(exc.code, int) else exc.code
        raise
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    codigo = _cmd_scrape(args)
    if codigo != 0:
        return codigo
    return _cmd_analizar(args)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bot de comentarios: scrape y análisis de dudas con Groq."
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_login = sub.add_parser("login", help="inicia sesión y guarda el estado")
    p_login.add_argument("--headless", action="store_true")
    p_login.add_argument("--forzar-login", action="store_true")
    p_login.set_defaults(func=_cmd_login)

    p_scrape = sub.add_parser("scrape", help="recorre el curso y guarda comentarios")
    p_scrape.add_argument("--curso")
    p_scrape.add_argument("--headless", action="store_true")
    p_scrape.add_argument("--forzar-login", action="store_true")
    p_scrape.add_argument("--mantener-abierto", action="store_true")
    p_scrape.set_defaults(func=_cmd_scrape)

    p_analizar = sub.add_parser("analizar", help="categoriza dudas con Groq")
    p_analizar.add_argument("--curso")
    p_analizar.add_argument("--archivo")
    p_analizar.add_argument(
        "--modelo",
        default=analizar_comentarios.MODELO_POR_DEFECTO,
    )
    p_analizar.add_argument("--limite", type=int)
    p_analizar.set_defaults(func=_cmd_analizar)

    p_run = sub.add_parser("run", help="scrape + análisis")
    p_run.add_argument("--curso")
    p_run.add_argument("--headless", action="store_true")
    p_run.add_argument("--forzar-login", action="store_true")
    p_run.add_argument("--mantener-abierto", action="store_true")
    p_run.add_argument(
        "--modelo",
        default=analizar_comentarios.MODELO_POR_DEFECTO,
    )
    p_run.add_argument("--limite", type=int)
    p_run.set_defaults(func=_cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
