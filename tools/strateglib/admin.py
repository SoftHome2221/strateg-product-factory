"""Проверка окружения и репозитория: зависимости, структура, секреты, персональные данные."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys

from .common import CONFIG, KNOWLEDGE, PROJECTS, ROOT, StrategError, read_jsonl

SECRET_PATTERNS = [
    (r"sk-ant-[A-Za-z0-9_-]{20,}", "ключ Anthropic"), (r"\bsk-[A-Za-z0-9]{32,}", "ключ API (sk-…)"),
    (r"AKIA[0-9A-Z]{16}", "ключ AWS"), (r"ghp_[A-Za-z0-9]{36}", "токен GitHub"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "закрытый ключ"),
    (r"(?i)(api[_-]?key|secret|token|password|authorization)\s*[:=]\s*[\"'][A-Za-z0-9_\-+/=.]{16,}[\"']", "похоже на секрет в коде"),
]
PD_PATTERNS = [(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", "e-mail"), (r"(?:\+7|\b8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}\b", "телефон")]
CONFIG_FILES = [".mcp.json", ".cursor/mcp.json", ".cursor/hooks.json", ".claude/settings.json", ".codex/hooks.json", ".dsh/hooks.json"]
REQUIRED = ["AGENTS.md", "CLAUDE.md", "README.md", "knowledge/INDEX.md", "config/routing.json", "config/prices.json",
            "config/policy.json", "templates/outputs/01-brief.md", ".claude/settings.json", ".gitignore", ".env.example"]


def _text_files():
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}
    for f in ROOT.rglob("*"):
        if not f.is_file() or skip_dirs & set(f.relative_to(ROOT).parts):
            continue
        if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".xlsx", ".docx", ".mp3", ".mp4", ".zip", ".pyc"}:
            continue
        if f.stat().st_size > 3_000_000:
            continue
        yield f


def doctor() -> tuple[list[str], list[str], list[str]]:
    ok, warn, err = [], [], []
    v = sys.version_info
    (ok if v >= (3, 9) else err).append(f"Python {v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 9) else " — нужен 3.9+"))
    for r in REQUIRED:
        if not (ROOT / r).exists():
            err.append(f"нет файла {r}")
    if not err:
        ok.append("структура репозитория на месте")
    for c in CONFIG_FILES + ["config/routing.json", "config/prices.json", "config/policy.json"]:
        f = ROOT / c
        if f.exists():
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                err.append(f"{c}: некорректный JSON ({e})")
    py_cmds = set()
    for c in CONFIG_FILES:
        f = ROOT / c
        if f.exists():
            py_cmds |= set(re.findall(r'"(?:command)":\s*"(python3?|py)\b', f.read_text(encoding="utf-8")))
    for cmd in py_cmds:
        if not shutil.which(cmd):
            err.append(f"хуки и MCP вызывают «{cmd}», но такой команды нет в PATH. Исправить: {sys.executable} tools/strateg.py setup")
    if py_cmds and not any("нет в PATH" in e for e in err):
        ok.append(f"хуки и MCP вызывают: {', '.join(sorted(py_cmds))} — команда доступна")
    for mod, why in (("pypdf", "чтение PDF (pip install pypdf)"), ("truststore", "системные сертификаты для HTTPS (pip install truststore)")):
        if importlib.util.find_spec(mod):
            ok.append(f"необязательный пакет {mod} установлен")
        elif mod == "truststore" and importlib.util.find_spec("certifi"):
            ok.append("certifi установлен (сертификаты для HTTPS)")
        else:
            warn.append(f"необязательный пакет {mod} не установлен — {why}")
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    if ".env" not in gi:
        err.append(".gitignore не закрывает .env")
    found = 0
    for f in _text_files():
        rel = f.relative_to(ROOT).as_posix()
        if rel.startswith("tools/strateglib/admin.py") or rel == ".env":
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat, name in SECRET_PATTERNS:
            m = re.search(pat, text)
            if m:
                found += 1
                err.append(f"{rel}: {name} — уберите секрет из репозитория (значение начинается с «{m.group(0)[:8]}…»)")
    if not found:
        ok.append("секретов в файлах репозитория не найдено")
    for d in sorted(PROJECTS.iterdir()) if PROJECTS.exists() else []:
        reg = d / "sources" / "sources.jsonl"
        for s in read_jsonl(reg) if reg.exists() else []:
            if s.get("kind") != "interview":
                continue
            f = ROOT / s["text"]
            text = f.read_text(encoding="utf-8") if f.exists() else ""
            for pat, name in PD_PATTERNS:
                if re.search(pat, text):
                    err.append(f"{s['text']}: в интервью найден {name} — обезличьте запись")
            if not s.get("consent"):
                err.append(f"{d.name}/{s['id']}: интервью без отметки согласия")
    n_kb = len(list(KNOWLEDGE.glob("*.md")))
    ok.append(f"методических файлов в knowledge/: {n_kb}")
    return ok, warn, err


def cmd_doctor(a):
    ok, warn, err = doctor()
    for x in ok:
        print("OK       " + x)
    for x in warn:
        print("ВНИМАНИЕ " + x)
    for x in err:
        print("ОШИБКА   " + x)
    print(f"Итог: ошибок {len(err)}, замечаний {len(warn)}.")
    if err:
        raise StrategError("Есть ошибки окружения — исправьте их до начала работы.", 2)


def cmd_setup(a):
    """Одноразовая настройка: подставить в хуки и MCP ту команду Python, которая есть в системе."""
    target = a.python
    if not target:
        target = "python" if shutil.which("python") else ("python3" if shutil.which("python3") else None)
        if target == "python" and sys.platform != "win32":
            # на macOS/Linux «python» может быть Python 2 или отсутствовать у другого пользователя
            target = "python3" if shutil.which("python3") else "python"
    if not target:
        raise StrategError("Не найдена команда python/python3 в PATH. Укажите явно: setup --python <команда>")
    changed = []
    for c in CONFIG_FILES:
        f = ROOT / c
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        new = re.sub(r'("command":\s*")(python3?|py)(?=[\s"])', rf"\g<1>{target}", text)
        if new != text:
            f.write_text(new, encoding="utf-8", newline="\n")
            changed.append(c)
    print(f"Команда Python для хуков и MCP: {target}" + (f" (обновлены: {', '.join(changed)})" if changed else " (изменений не потребовалось)"))
    cmd_doctor(a)
    print("\nГотово. Откройте папку в своей среде (Claude Code, Cursor, Codex и др.) и напишите в чате: «Начни» или «Продолжи».")
    print("Проверить всё без модели: python tools/strateg.py selftest")


def register(sub):
    s = sub.add_parser("doctor", help="проверка окружения, структуры, секретов"); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("setup", help="первичная настройка (команда Python в хуках и MCP) + doctor")
    s.add_argument("--python"); s.set_defaults(fn=cmd_setup)
