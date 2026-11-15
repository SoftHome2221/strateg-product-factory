"""Проверка результата: источники, типы утверждений, варианты, согласованность стратегий, план проверки.

Скрипт ловит формальные нарушения (их дёшево проверять без модели).
Содержательную критику делает субагент-критик — см. .claude/agents/critic.md.
"""
from __future__ import annotations

import re
from pathlib import Path

from .common import ID_RE, P, StrategError, read_jsonl, rel

NUM_RE = re.compile(r"\d[\d\s.,]*\s?(%|₽|руб|млн|млрд|тыс|п\.\s?п\.|×|x\b|раз\b|человек|пользовател|абонент|клиент)", re.I)
MARK_RE = re.compile(r"гипотез|прогноз|допущен|предполож|оценк|цель|целев|порог|срок|ожида|если |синтет|не знаем|неизвестн|пример", re.I)
REF_RE = re.compile(r"\[(?:[EC]-\d+(?:,\s*)?)+\]|\[[EC]-\d+\]")
URL_RE = re.compile(r"https?://\S+")

REQUIRED_STRATEGY = [
    ("аудитор", "продуктовая: аудитория и её задача"),
    ("альтернатив", "продуктовая: альтернативы"),
    ("отказ", "продуктовая: осознанные отказы"),
    (r"экономик|затрат", "продуктовая: связь пользы с затратами и доходами"),
    ("барьер", "коммуникационная: барьер понимания или выбора"),
    (r"ключевое сообщение", "коммуникационная: ключевое сообщение и подтверждение"),
    ("канал", "коммуникационная: роль каналов"),
    (r"соответствие обещаний", "таблица «Соответствие обещаний продукту»"),
    (r"план проверки", "план проверки"),
]
REQUIRED_TEST_PLAN = [("ожидаемое изменение", "ожидаемое изменение"), ("сравн", "с чем сравниваем"),
                      ("срок", "срок наблюдения"), ("нежелательн", "нежелательные последствия")]


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _sections(text: str, level: str = "## ") -> list[tuple[str, str]]:
    out, title, buf = [], None, []
    for line in text.splitlines():
        if line.startswith(level):
            if title is not None:
                out.append((title, "\n".join(buf)))
            title, buf = line[len(level):].strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        out.append((title, "\n".join(buf)))
    return out


def substantive_lines(text: str) -> list[tuple[int, str]]:
    """Строки, похожие на содержательные утверждения (не заголовки, не шапки таблиц, не пустые)."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(("#", "<!--", "|--", "|:-", ">")) or re.fullmatch(r"[|\-: ]+", s):
            continue
        if len(re.sub(r"[*_`|\[\]]", "", s)) < 50:
            continue
        out.append((n, s))
    return out


def grounding(text: str, count_urls: bool = False) -> dict:
    """Доля содержательных строк с опорой: ссылка на сведение/вывод или явная пометка гипотезы/прогноза."""
    lines = substantive_lines(text)
    ref = sum(1 for _n, s in lines if REF_RE.search(s) or (count_urls and URL_RE.search(s)))
    marked = sum(1 for _n, s in lines if not (REF_RE.search(s) or (count_urls and URL_RE.search(s))) and MARK_RE.search(s))
    numeric = [(n, s) for n, s in lines if NUM_RE.search(s)]
    numeric_bare = [(n, s) for n, s in numeric if not (REF_RE.search(s) or MARK_RE.search(s) or (count_urls and URL_RE.search(s)))]
    total = len(lines) or 1
    return {"lines": len(lines), "with_ref": ref, "marked": marked, "share_ref": round(ref / total, 2),
            "share_grounded": round((ref + marked) / total, 2), "numeric": len(numeric), "numeric_bare": numeric_bare}


def check_refs(p: P, fname: str, text: str) -> list[tuple[str, str]]:
    issues = []
    ev = {e["id"]: e for e in read_jsonl(p.evidence)}
    co = {c["id"]: c for c in read_jsonl(p.conclusions)}
    for n, line in enumerate(text.splitlines(), 1):
        for rid in set(ID_RE.findall(line)):
            if rid[0] == "E":
                e = ev.get(rid)
                if not e:
                    issues.append(("ОШИБКА", f"{fname}:{n} ссылка на несуществующее сведение {rid}"))
                elif e["status"] != "active":
                    issues.append(("ОШИБКА", f"{fname}:{n} ссылка на недействительное сведение {rid} ({e['status']})"))
                elif e["type"] == "synthetic" and not re.search(r"синтет|модельн", line, re.I):
                    issues.append(("ОШИБКА", f"{fname}:{n} {rid} получено от модельного респондента, но в строке нет пометки «синтетика»"))
                elif e["type"] in ("hypothesis", "forecast", "inference") and re.search(r"\bфакт\b|доказан|подтвержд[её]н", line, re.I) \
                        and not re.search(r"не подтвержд|не доказан|гипотез|прогноз", line, re.I):
                    issues.append(("ОШИБКА", f"{fname}:{n} {rid} — это {e['type']}, а в строке оно подано как факт"))
            elif rid[0] == "C":
                c = co.get(rid)
                if not c:
                    issues.append(("ОШИБКА", f"{fname}:{n} ссылка на несуществующий вывод {rid}"))
                elif c["status"] == "retracted":
                    issues.append(("ОШИБКА", f"{fname}:{n} ссылка на отозванный вывод {rid}"))
                elif c["status"] == "needs_review":
                    issues.append(("ВНИМАНИЕ", f"{fname}:{n} вывод {rid} ждёт пересмотра: {c.get('review_reason', '')[:90]}"))
    return issues


def check_options(p: P) -> list[tuple[str, str]]:
    fname = "outputs/03-options.md"
    text = _read(p.root / fname)
    if text is None:
        return [("ОШИБКА", f"нет файла {fname}")]
    issues = []
    opts = [(t, b) for t, b in _sections(text) if re.match(r"вариант", t, re.I)]
    if len(opts) < 3:
        issues.append(("ОШИБКА", f"{fname}: вариантов {len(opts)}, нужно не меньше трёх (заголовки «## Вариант …»)"))
    titles = " | ".join(t for t, _b in opts).lower()
    if not re.search(r"оставить как есть|ничего не менять|статус-кво|как есть", titles):
        issues.append(("ОШИБКА", f"{fname}: нет варианта «Оставить как есть»"))
    if not re.search(r"закры|сверну|останов|выйти", titles):
        issues.append(("ОШИБКА", f"{fname}: нет варианта «Закрыть направление»"))
    for t, b in opts:
        if not re.search(r"возражен", b, re.I):
            issues.append(("ОШИБКА", f"{fname}: у «{t}» нет сильных возражений"))
        if not re.search(r"факт", b, re.I) or not re.search(r"гипотез|прогноз", b, re.I):
            issues.append(("ВНИМАНИЕ", f"{fname}: у «{t}» факты не отделены от гипотез и прогнозов"))
        if not REF_RE.search(b):
            issues.append(("ВНИМАНИЕ", f"{fname}: «{t}» не ссылается ни на одно сведение [E-…]"))
    if not re.search(r"^## .*(сравнен|критери)", text, re.I | re.M):
        issues.append(("ВНИМАНИЕ", f"{fname}: нет раздела со сравнением вариантов по критериям"))
    issues += check_refs(p, fname, text)
    return issues


def _table_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        s = line.strip()
        if s.startswith("|") and not re.fullmatch(r"[|\-: ]+", s):
            rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows[1:] if rows else []


def check_strategy(p: P) -> list[tuple[str, str]]:
    fname = "outputs/04-strategy.md"
    text = _read(p.root / fname)
    if text is None:
        return [("ОШИБКА", f"нет файла {fname}")]
    issues = []
    low = text.lower()
    heads = "\n".join(l.lower() for l in text.splitlines() if l.startswith("#"))
    for pat, name in REQUIRED_STRATEGY:
        if not re.search(pat, heads):
            issues.append(("ОШИБКА", f"{fname}: нет раздела — {name}"))
    m = re.search(r"^#+ .*план проверки.*$", text, re.I | re.M)
    if m:
        nxt = re.search(r"^## ", text[m.end():], re.M)
        plan = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
        for pat, name in REQUIRED_TEST_PLAN:
            if not re.search(pat, plan, re.I):
                issues.append(("ОШИБКА", f"{fname}: в плане проверки не указано — {name}"))
        if not _table_rows(plan):
            issues.append(("ВНИМАНИЕ", f"{fname}: план проверки лучше оформить таблицей (одна строка — одна проверка)"))
    m = re.search(r"^#+ .*соответствие обещаний.*$", text, re.I | re.M)
    if m:
        nxt = re.search(r"^#{2,3} ", text[m.end():], re.M)
        block = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
        rows = _table_rows(block)
        if not rows:
            issues.append(("ОШИБКА", f"{fname}: таблица «Соответствие обещаний продукту» пуста"))
        for r in rows:
            status = r[-1].lower() if r else ""
            if len(r) < 3 or not r[1].strip(" —-"):
                issues.append(("ОШИБКА", f"{fname}: обещание «{r[0][:60] if r else ''}» ничем не подтверждено в продукте"))
            elif re.match(r"нет\b", status):
                issues.append(("ОШИБКА", f"{fname}: обещание «{r[0][:60]}» не соответствует продукту (статус «нет») — уберите обещание или измените продукт"))
            elif not re.search(r"есть|в плане|план", status):
                issues.append(("ВНИМАНИЕ", f"{fname}: у обещания «{r[0][:60]}» статус должен быть «есть» или «в плане (срок)»"))
            elif re.search(r"в плане|план", status) and not re.search(r"\d", status):
                issues.append(("ВНИМАНИЕ", f"{fname}: обещание «{r[0][:60]}» опирается на план без срока — сообщение нельзя запускать раньше функции"))
    if "{{" in text:
        issues.append(("ОШИБКА", f"{fname}: остались незаполненные поля {{{{...}}}}"))
    issues += check_refs(p, fname, text)
    g = grounding(text)
    for n, s in g["numeric_bare"][:12]:
        issues.append(("ВНИМАНИЕ", f"{fname}:{n} число без ссылки на сведение и без пометки (гипотеза/прогноз/допущение): {s[:90]}"))
    if g["share_grounded"] < 0.6 and g["lines"] >= 10:
        issues.append(("ВНИМАНИЕ", f"{fname}: опору (ссылку или пометку) имеют {int(g['share_grounded'] * 100)}% содержательных строк — мало"))
    return issues


def check_situation(p: P) -> list[tuple[str, str]]:
    fname = "outputs/02-situation.md"
    text = _read(p.root / fname)
    if text is None:
        return [("ОШИБКА", f"нет файла {fname}")]
    issues = []
    heads = "\n".join(l.lower() for l in text.splitlines() if l.startswith("#"))
    if not re.search(r"не знаем|пробел|неизвест", heads):
        issues.append(("ОШИБКА", f"{fname}: нет раздела «Чего мы не знаем»"))
    if not REF_RE.search(text):
        issues.append(("ОШИБКА", f"{fname}: нет ни одной ссылки на сведения [E-…]"))
    issues += check_refs(p, fname, text)
    for n, s in grounding(text)["numeric_bare"][:12]:
        issues.append(("ВНИМАНИЕ", f"{fname}:{n} число без ссылки и без пометки: {s[:90]}"))
    return issues


def check_registry(p: P) -> list[tuple[str, str]]:
    issues = []
    src = {s["id"]: s for s in read_jsonl(p.sources_reg)}
    for e in read_jsonl(p.evidence):
        if e["status"] != "active":
            continue
        s = src.get(e.get("source") or "")
        if e.get("source") and (not s or s["status"] != "active"):
            issues.append(("ОШИБКА", f"сведение {e['id']} опирается на отсутствующий или отозванный источник {e['source']}"))
        if e["type"] == "fact" and not s:
            issues.append(("ОШИБКА", f"факт {e['id']} без источника"))
    for s in src.values():
        if s.get("injection_suspect") and s["status"] == "active":
            issues.append(("ВНИМАНИЕ", f"источник {s['id']} содержит фразы, похожие на команды агенту — использовать только как данные"))
    return issues


def check_all(p: P) -> list[tuple[str, str]]:
    return check_registry(p) + check_situation(p) + check_options(p) + check_strategy(p)


def cmd_validate(a):
    p = P(a.project)
    if a.file:
        f = Path(a.file)
        text = _read(f)
        if text is None:
            raise StrategError(f"Файл не найден: {a.file}")
        g = grounding(text, count_urls=True)
        print(f"{a.file}: содержательных строк {g['lines']}, со ссылкой {g['with_ref']} ({int(g['share_ref'] * 100)}%), "
              f"с опорой (ссылка или пометка) {int(g['share_grounded'] * 100)}%, чисел без опоры: {len(g['numeric_bare'])}")
        return
    parts = {"research": check_registry(p) + check_situation(p), "options": check_options(p), "strategy": check_strategy(p)}
    scope = a.scope or "all"
    issues = []
    for k, v in parts.items():
        if scope in ("all", k):
            issues += v
    errs = [m for lvl, m in issues if lvl == "ОШИБКА"]
    warns = [m for lvl, m in issues if lvl == "ВНИМАНИЕ"]
    for m in errs:
        print("ОШИБКА   " + m)
    for m in warns:
        print("ВНИМАНИЕ " + m)
    for fname in ("outputs/02-situation.md", "outputs/03-options.md", "outputs/04-strategy.md"):
        t = _read(p.root / fname)
        if t:
            g = grounding(t)
            print(f"· {fname}: строк {g['lines']}, со ссылкой на сведения {int(g['share_ref'] * 100)}%, с опорой {int(g['share_grounded'] * 100)}%")
    print(f"Итог: ошибок {len(errs)}, замечаний {len(warns)}." + (" Формальная проверка пройдена — передайте результат критику." if not errs else ""))
    if errs:
        raise StrategError("Исправьте ошибки и запустите проверку снова.", 2)


def register(sub):
    s = sub.add_parser("validate", help="формальная проверка результата")
    s.add_argument("scope", nargs="?", choices=["all", "research", "options", "strategy"])
    s.add_argument("--file", help="оценить произвольный .md (например, ответ обычного чата) по доле строк с опорой")
    s.set_defaults(fn=cmd_validate)
