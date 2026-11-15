"""Сборка итогового отчёта: результаты этапов + приложения (сведения и источники, действия агента, расходы)."""
from __future__ import annotations

import re

from . import journal as jr
from .common import ID_RE, P, StrategError, now, read_json, read_jsonl, rel
from .evidence import TYPES
from .project import STAGES

PARTS = [("outputs/04-strategy.md", "Стратегия"), ("outputs/03-options.md", "Варианты"),
         ("outputs/02-situation.md", "Картина ситуации"), ("outputs/01-brief.md", "Постановка задачи")]


def _demote(text: str) -> str:
    return "\n".join(("#" + l) if l.startswith("#") else l for l in text.splitlines())


def build(p: P) -> str:
    t = read_json(p.task, {})
    out = [f"# Отчёт: {t.get('title', p.slug)}", "",
           f"Собран {now()[:16]} · проект `{p.slug}` · исходный запрос: {t.get('request') or '—'}", "",
           "> Как читать: каждая ссылка вида [E-012] ведёт к записи в приложении А — там тип утверждения "
           "(факт, гипотеза, прогноз, синтетика, вывод агента), источник и место в нём. [C-03] — вывод агента и его основания (приложение Б).", ""]
    cited = set()
    missing = []
    for fname, title in PARTS:
        f = p.root / fname
        if not f.exists():
            missing.append(fname)
            continue
        text = f.read_text(encoding="utf-8")
        cited |= set(ID_RE.findall(text))
        out += ["---", "", _demote(text).strip(), ""]
    src = {s["id"]: s for s in read_jsonl(p.sources_reg)}
    ev = [e for e in read_jsonl(p.evidence) if e["id"] in cited]
    out += ["---", "", "## Приложение А. Сведения и источники", "",
            "| № | Тип | Утверждение | Источник и место | Период | Уверенность |", "|---|---|---|---|---|---|"]
    for e in ev:
        s = src.get(e.get("source") or "")
        where = f"{s['id']}: {s['title'][:60]} ({s['origin']}; получен {s['retrieved_at'][:10]})" if s else "без источника"
        if e.get("loc"):
            where += f" · {e['loc']}"
        st = "" if e["status"] == "active" else " **(недействительно)**"
        out.append(f"| {e['id']} | {TYPES[e['type']]}{st} | {e['claim'].replace('|', '/')} | {where.replace('|', '/')} | {e.get('period') or '—'} | {e['confidence']} |")
    unused = [e["id"] for e in read_jsonl(p.evidence) if e["status"] == "active" and e["id"] not in cited]
    if unused:
        out += ["", f"Собраны, но не использованы в тексте: {', '.join(unused)}."]
    concl = [c for c in read_jsonl(p.conclusions) if c["id"] in cited]
    if concl:
        out += ["", "## Приложение Б. Выводы агента и их основания", "", "| № | Вывод | Основания | Сила | Состояние |", "|---|---|---|---|---|"]
        for c in concl:
            out.append(f"| {c['id']} | {c['text'].replace('|', '/')} | {', '.join(c['based_on'])} | {c['strength']} | {c['status']} |")
    out += ["", "## Приложение В. Что сделал агент", ""]
    names = {c: n for c, n, _g, _f in STAGES}
    for code, st in t.get("stages", {}).items():
        if st["status"] == "pending":
            continue
        human = f" — решение человека: «{st['human']}»" if st.get("human") else ""
        out.append(f"- **{names[code]}**: {st['status']}{human}")
    out += ["", "| Когда | Этап | Действие | Инструмент | Итог |", "|---|---|---|---|---|"]
    for j in read_jsonl(p.journal):
        out.append(f"| {j['ts'][5:16].replace('T', ' ')} | {j.get('stage', '')} | {j['action'][:140].replace('|', '/')} | {j.get('tool', '')} | "
                   f"{j['status']}{(': ' + j['error'][:80]) if j.get('error') else ''} |")
    decs = read_jsonl(p.decisions)
    if decs:
        out += ["", "## Приложение Г. Решения и обязательства", ""]
        for d in decs:
            out.append(f"- **{d['id']}** ({d['decided_at']}, {d['status']}): {d['decision']} — ответственный: {d['owner']}; "
                       f"показатель: {d['metric'] or '—'} ({d['baseline'] or '?'} → {d['target'] or '?'}), проверка {d['check_date'] or '—'}; "
                       f"пересмотреть, если: {'; '.join(d['review_conditions']) or '—'}")
            for c in d["commitments"]:
                out.append(f"  - [{'x' if c['status'] == 'done' else ' '}] {c['what']} — {c['owner']}, до {c['due']}")
    out += ["", jr.cost_report(p), ""]
    if missing:
        out += ["", f"> Отчёт неполный: нет файлов {', '.join(missing)}."]
    return "\n".join(out)


def cmd_report(a):
    p = P(a.project)
    text = build(p)
    f = p.outputs / "report.md"
    f.write_text(text + "\n", encoding="utf-8", newline="\n")
    jr.add(p, action="Собран итоговый отчёт outputs/report.md", tool="strateg report")
    print(f"Отчёт собран: {rel(f)} ({len(text.splitlines())} строк)")


def register(sub):
    s = sub.add_parser("report", help="собрать итоговый отчёт с приложениями и расходами"); s.set_defaults(fn=cmd_report)
