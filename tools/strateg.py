#!/usr/bin/env python3
"""Стратег — инструменты агента (только стандартная библиотека Python 3.9+).

  python tools/strateg.py status          где мы и что дальше
  python tools/strateg.py --help          все команды

Агент вызывает эти команды сам; человеку достаточно писать в чат.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from strateglib import admin, data, decisions, evidence, journal, project, report, route, search, sources, validate  # noqa: E402
from strateglib.common import StrategError  # noqa: E402

MODULES = [project, sources, evidence, search, data, route, validate, report, decisions, journal, admin]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="strateg", description="Инструменты агента «Стратег Фабрики продуктов»")
    ap.add_argument("--project", help="slug проекта (по умолчанию — активный)")
    sub = ap.add_subparsers(dest="cmd", metavar="команда")
    for m in MODULES:
        m.register(sub)
    s = sub.add_parser("hook", help="(служебное) обработчик хуков среды")
    s.add_argument("env"); s.add_argument("event", nargs="?", default="")
    s = sub.add_parser("selftest", help="сквозная самопроверка инструментов без модели (~5 секунд)")
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = build_parser()
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 0
    if args.cmd == "hook":
        from strateglib import hooks
        return hooks.main([args.env, args.event])
    if args.cmd == "selftest":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
        import selftest
        return selftest.main()
    try:
        args.fn(args)
        return 0
    except StrategError as e:
        print(str(e), file=sys.stderr)
        return e.code


def run_cli(argv: list[str]) -> tuple[str, bool]:
    """Вызов команды из кода (MCP-сервер, тесты). Возвращает (текст, была_ли_ошибка)."""
    buf = io.StringIO()
    code = 1
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            code = main(argv)
        except SystemExit as e:  # argparse
            code = int(e.code or 0)
        except Exception as e:
            print(f"Внутренняя ошибка инструмента: {type(e).__name__}: {e}")
            code = 1
    return buf.getvalue().strip(), code != 0


if __name__ == "__main__":
    sys.exit(main())
