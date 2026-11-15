#!/usr/bin/env python3
"""MCP-сервер «Стратега» (stdio, JSON-RPC 2.0, только стандартная библиотека).

Даёт те же инструменты, что и CLI, средам, где агенту удобнее или безопаснее вызывать типизированные
инструменты, чем терминал (Claude Desktop, Cursor без доступа к shell и т.п.).
Подключение: .mcp.json (Claude Code) и .cursor/mcp.json (Cursor) уже лежат в репозитории.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from strateg import run_cli  # noqa: E402

SUPPORTED = ["2025-06-18", "2025-03-26", "2024-11-05"]


def _s(desc, **props):
    req = [k for k, v in props.items() if v.pop("_req", False)]
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}, desc


def _str(d, req=False, enum=None):
    o = {"type": "string", "description": d, "_req": req}
    if enum:
        o["enum"] = enum
    return o


TOOLS = {
    "strateg_status": (_s("Где мы и что дальше: этап, следующее действие, открытые вопросы, незавершённые действия, расходы. "
                          "Вызывать в начале каждого сеанса."), lambda a: ["status"]),
    "strateg_search": (_s("Поиск по методике (knowledge/) и материалам проекта: сведения, выводы, источники, решения.",
                          query=_str("запрос", True), scope=_str("где искать", enum=["kb", "project", "all"])),
                       lambda a: ["search", a["query"], "--scope", a.get("scope", "all")]),
    "strateg_ingest": (_s("Загрузить материал (файл или URL из разрешённых источников) в реестр источников. "
                          "Для веб-страниц это путь с обязательным журналом и сохранённым источником; "
                          "используйте его, если нативный WebFetch клиента не вызывает хуки.",
                          target=_str("путь к файлу или URL", True), kind=_str("вид материала"), title=_str("название")),
                       lambda a: ["ingest", a["target"]] + (["--kind", a["kind"]] if a.get("kind") else []) + (["--title", a["title"]] if a.get("title") else [])),
    "strateg_evidence_add": (_s("Записать сведение в реестр. Факт требует источника и места в нём.",
                                type=_str("тип", True, ["fact", "hypothesis", "forecast", "synthetic", "inference"]),
                                claim=_str("утверждение одной фразой", True), source=_str("id источника S-…"),
                                loc=_str("место в источнике"), quote=_str("короткая цитата"), period=_str("период данных"),
                                conf=_str("уверенность", enum=["high", "medium", "low"]), q=_str("вопрос исследования, напр. Q2")),
                             lambda a: ["ev", "add"] + [x for k in ("type", "claim", "source", "loc", "quote", "period", "conf", "q") if a.get(k) for x in (f"--{k}", a[k])]),
    "strateg_evidence_list": (_s("Список действующих сведений.", type=_str("фильтр по типу")),
                              lambda a: ["ev", "list"] + (["--type", a["type"]] if a.get("type") else [])),
    "strateg_impact": (_s("Что затронуто, если запись изменилась: зависимые выводы, решения, места в документах.",
                          id=_str("id сведения, вывода или источника", True)), lambda a: ["impact", a["id"]]),
    "strateg_validate": (_s("Формальная проверка результата: ссылки, типы утверждений, варианты, обещания, план проверки.",
                            scope=_str("что проверять", enum=["all", "research", "options", "strategy"])),
                         lambda a: ["validate"] + ([a["scope"]] if a.get("scope") else [])),
    "strateg_decisions_due": (_s("Что решать и проверять сейчас: сроки обязательств, проверки показателей, устаревшие основания."),
                              lambda a: ["dec", "due"]),
    "strateg_route": (_s("Выбрать процесс, уровень модели и инструмент для подзадачи.", text=_str("описание подзадачи", True)),
                      lambda a: ["route", "pick", a["text"]]),
    "strateg_cli": (({"type": "object", "properties": {"args": {"type": "array", "items": {"type": "string"},
                                                                  "description": "аргументы CLI, напр. [\"data\",\"profile\",\"путь.csv\"]"}},
                      "required": ["args"], "additionalProperties": False},
                     "Любая другая команда CLI «Стратега» (stage, log, concl, dec, data, report, cost, sources, ask, answer, handoff). "
                     "Список команд: args=[\"--help\"]."), lambda a: [str(x) for x in a["args"]]),
}


def handle(msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
    if method == "initialize":
        ver = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": ver if ver in SUPPORTED else SUPPORTED[0], "capabilities": {"tools": {}},
            "serverInfo": {"name": "strateg", "version": "1.0.0"},
            "instructions": "Инструменты агента «Стратег». Начинайте сеанс со strateg_status: это надёжный источник состояния, "
                            "даже если асинхронный sessionStart клиента не подставил контекст. Веб-страницы загружайте через "
                            "strateg_ingest с URL: источник и действие сохраняются сервером независимо от нативного WebFetch. "
                            "Правила работы — AGENTS.md."}}
    if method.startswith("notifications/"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": n, "description": d, "inputSchema": schema} for n, ((schema, d), _f) in TOOLS.items()]}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Неизвестный инструмент: {name}"}}
        try:
            argv = TOOLS[name][1](args)
        except KeyError as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"Не хватает аргумента {e}"}], "isError": True}}
        if argv and argv[0] in ("hook", "selftest", "setup"):
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "Эта команда недоступна через MCP."}], "isError": True}}
        text, is_err = run_cli(argv)
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text or "(пустой вывод)"}], "isError": is_err}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Метод не поддерживается: {method}"}}


def main() -> int:
    out = sys.stdout.buffer
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            try:
                resp = handle(msg)
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": f"{type(e).__name__}: {e}"}}
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
