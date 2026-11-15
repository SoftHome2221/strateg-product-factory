"""Общие функции: пути, чтение/запись JSON(L), активный проект, идентификаторы."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ROOT / "projects"
KNOWLEDGE = ROOT / "knowledge"
CONFIG = ROOT / "config"
TEMPLATES = ROOT / "templates"

ID_RE = re.compile(r"\b([SECDJRQ]-\d{2,5})\b")


class StrategError(Exception):
    """Ожидаемая ошибка с понятным сообщением для человека и агента."""

    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> dt.date:
    """Сегодняшняя дата. STRATEG_TODAY позволяет воспроизводимо тестировать сроки."""
    v = os.environ.get("STRATEG_TODAY")
    return dt.date.fromisoformat(v) if v else dt.date.today()


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_json(path: Path, obj) -> None:
    _atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise StrategError(f"Повреждена строка {n} в {rel(path)}: {e}")
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    _atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def next_id(rows: list[dict], prefix: str, width: int = 3) -> str:
    mx = 0
    for r in rows:
        m = re.fullmatch(rf"{prefix}-(\d+)", str(r.get("id", "")))
        if m:
            mx = max(mx, int(m.group(1)))
    return f"{prefix}-{mx + 1:0{width}d}"


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def est_tokens(text: str) -> int:
    """Грубая оценка числа токенов (для русского текста ~3 символа на токен)."""
    return max(1, round(len(text) / 3))


def split_ids(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r"[,\s]+", value) if x.strip()]


# ---------- активный проект ----------

DOTENV_KEYS = ("STRATEG_ROUTER_CMD", "JEV_API_KEY", "JEV_API_URL", "JEV_MODEL", "JEV_TIMEOUT_S", "STRATEG_EMBED_MODEL")


def setting(name: str, path: Path | None = None) -> str | None:
    """Настройка: переменная окружения, иначе строка NAME=… из файла .env в корне (он закрыт от git).
    Читаются только имена из DOTENV_KEYS; значения никуда не выводятся. STRATEG_NO_DOTENV=1 отключает файл
    (самопроверка не должна вызывать настоящие сервисы)."""
    v = os.environ.get(name)
    if v or name not in DOTENV_KEYS or (path is None and os.environ.get("STRATEG_NO_DOTENV") == "1"):
        return v
    f = path or ROOT / ("." + "env")
    try:
        lines = f.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    for line in lines:
        k, sep, val = line.strip().partition("=")
        if sep and k.strip().removeprefix("export ").strip() == name:
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            return val or None
    return None


def active_slug(explicit: str | None = None, required: bool = True) -> str | None:
    slug = explicit or os.environ.get("STRATEG_PROJECT")
    if not slug:
        f = PROJECTS / ".active"
        if f.exists():
            slug = f.read_text(encoding="utf-8").strip()
    if not slug:
        if required:
            raise StrategError(
                "Нет активного проекта. Создайте: python tools/strateg.py new <slug> --title \"...\" "
                "или выберите: python tools/strateg.py use <slug>"
            )
        return None
    if not (PROJECTS / slug / "project.json").exists():
        if required:
            raise StrategError(f"Проект «{slug}» не найден в projects/. Список: python tools/strateg.py projects")
        return None
    return slug


def pdir(slug: str | None = None) -> Path:
    return PROJECTS / active_slug(slug)


class P:
    """Пути внутри проекта. Раздельно: материалы, сведения, состояние, результаты, решения."""

    def __init__(self, slug: str | None = None):
        self.root = pdir(slug)
        self.slug = self.root.name
        self.meta = self.root / "project.json"
        self.sources = self.root / "sources"
        self.sources_reg = self.sources / "sources.jsonl"
        self.evidence = self.root / "evidence" / "evidence.jsonl"
        self.conclusions = self.root / "evidence" / "conclusions.jsonl"
        self.state = self.root / "state"
        self.task = self.state / "task.json"
        self.journal = self.state / "journal.jsonl"
        self.sessions = self.state / "sessions.jsonl"
        self.routes = self.state / "routes.jsonl"
        self.handoff = self.state / "handoff.md"
        self.outputs = self.root / "outputs"
        self.analysis = self.root / "analysis"
        self.decisions = self.root / "decisions" / "decisions.jsonl"
