"""Поддержка решений: журнал решений, обязательства, показатели, условия пересмотра, устаревание оснований."""
from __future__ import annotations

import datetime as dt

from . import journal as jr
from .common import CONFIG, P, StrategError, next_id, now, read_json, read_jsonl, split_ids, today, write_jsonl


def _date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        raise StrategError(f"Дата в формате ГГГГ-ММ-ДД, а не «{s}»")


def _find(rows, rid):
    for r in rows:
        if r["id"] == rid:
            return r
    raise StrategError(f"Решение {rid} не найдено")


def attention(p: P) -> list[str]:
    """Короткий список того, что требует внимания сейчас. Показывается в status."""
    out = []
    td = today()
    pol = read_json(CONFIG / "policy.json", {})
    fresh_days = pol.get("evidence_fresh_days", 365)
    ev = {e["id"]: e for e in read_jsonl(p.evidence)}
    concl = read_jsonl(p.conclusions)
    for c in concl:
        if c["status"] == "needs_review":
            out.append(f"вывод {c['id']} нужно пересмотреть: {c.get('review_reason', '')[:110]}")
    src = {s["id"]: s for s in read_jsonl(p.sources_reg)}
    for d in read_jsonl(p.decisions):
        if d.get("status") != "active":
            continue
        for fl in d.get("review_flags", []):
            if not fl.get("resolved"):
                out.append(f"решение {d['id']}: основания изменились — {fl['reason'][:110]}")
        cd = _date(d.get("check_date"))
        if cd and cd <= td:
            out.append(f"решение {d['id']}: наступил срок проверки показателя «{d.get('metric', '')}» ({d['check_date']})")
        for c in d.get("commitments", []):
            due = _date(c.get("due"))
            if c.get("status") == "open" and due:
                if due < td:
                    out.append(f"решение {d['id']}: ПРОСРОЧЕНО обязательство «{c['what']}» ({c['owner']}, срок {c['due']})")
                elif (due - td).days <= 7:
                    out.append(f"решение {d['id']}: скоро срок обязательства «{c['what']}» ({c['owner']}, {c['due']})")
        for b in d.get("based_on", []):
            e = ev.get(b)
            if not e:
                continue
            if e["status"] != "active":
                out.append(f"решение {d['id']} опирается на недействительное сведение {b} ({e['status']})")
            s = src.get(e.get("source") or "")
            if s:
                age = (td - dt.date.fromisoformat(s["retrieved_at"][:10])).days
                if age > fresh_days:
                    out.append(f"решение {d['id']}: основание {b} получено {age} дн. назад (порог {fresh_days}) — проверить актуальность {s['id']}")
    return out


def cmd_dec(a):
    p = P(a.project)
    rows = read_jsonl(p.decisions)
    if a.op == "add":
        if not (a.decision and a.owner):
            raise StrategError("Нужно минимум: dec add --decision \"...\" --owner \"роль\" [--based-on C-001,E-002] "
                               "[--metric ... --baseline ... --target ... --check-date ГГГГ-ММ-ДД] [--review-if \"условие; условие\"]")
        based = split_ids(a.based_on)
        known = {e["id"] for e in read_jsonl(p.evidence)} | {c["id"] for c in read_jsonl(p.conclusions)}
        for b in based:
            if b not in known:
                raise StrategError(f"Основание {b} не найдено")
        _date(a.check_date)
        rec = {"id": next_id(rows, "D"), "decided_at": a.date or today().isoformat(), "decision": a.decision.strip(),
               "option": a.option or "", "rationale": a.rationale or "", "based_on": based, "owner": a.owner,
               "metric": a.metric or "", "baseline": a.baseline or "", "target": a.target or "", "check_date": a.check_date or "",
               "review_conditions": [x.strip() for x in (a.review_if or "").split(";") if x.strip()],
               "commitments": [], "status": "active", "recorded_at": now()}
        rows.append(rec)
        write_jsonl(p.decisions, rows)
        jr.add(p, action=f"Решение {rec['id']} записано: {rec['decision'][:80]}", tool="strateg dec")
        print(f"{rec['id']} записано. Добавьте обязательства: dec commit {rec['id']} --what \"...\" --owner \"роль\" --due ГГГГ-ММ-ДД")
        if not rec["review_conditions"]:
            print("ВНИМАНИЕ: не заданы условия пересмотра (--review-if). Без них решение нельзя будет вовремя перепроверить.")
    elif a.op == "commit":
        d = _find(rows, a.id)
        if not (a.what and a.owner and a.due):
            raise StrategError("Нужно: dec commit D-001 --what \"...\" --owner \"роль\" --due ГГГГ-ММ-ДД")
        _date(a.due)
        d["commitments"].append({"n": len(d["commitments"]) + 1, "what": a.what, "owner": a.owner, "due": a.due, "status": "open"})
        write_jsonl(p.decisions, rows)
        print(f"Обязательство №{len(d['commitments'])} добавлено к {a.id}.")
    elif a.op == "fulfil":
        d = _find(rows, a.id)
        n = int(a.n or 0)
        for c in d["commitments"]:
            if c["n"] == n:
                c.update(status="done", done_at=now(), result=a.result or "")
                write_jsonl(p.decisions, rows)
                print(f"Обязательство №{n} по {a.id} выполнено.")
                return
        raise StrategError(f"У {a.id} нет обязательства №{n}")
    elif a.op == "result":
        d = _find(rows, a.id)
        if not a.result:
            raise StrategError("Нужно: dec result D-001 --result \"фактическое значение показателя и вывод\"")
        d.setdefault("results", []).append({"at": today().isoformat(), "result": a.result})
        if a.check_date:
            d["check_date"] = a.check_date
        else:
            d["check_date"] = ""
        write_jsonl(p.decisions, rows)
        print(f"Результат проверки по {a.id} записан. Если он меняет основания — запишите новое сведение (ev add) и проверьте impact.")
    elif a.op == "resolve":
        d = _find(rows, a.id)
        for fl in d.get("review_flags", []):
            if not fl.get("resolved"):
                fl.update(resolved=True, resolved_at=now(), outcome=a.result or "решение пересмотрено и оставлено в силе")
        write_jsonl(p.decisions, rows)
        jr.add(p, action=f"Решение {a.id} пересмотрено: {a.result or 'оставлено в силе'}", tool="strateg dec")
        print(f"Флаги пересмотра по {a.id} сняты.")
    elif a.op == "close":
        d = _find(rows, a.id)
        d.update(status=a.status or "closed", closed_at=now(), close_reason=a.result or "")
        write_jsonl(p.decisions, rows)
        print(f"{a.id}: {d['status']}")
    elif a.op == "list":
        if not rows:
            print("Решений нет. После выбора варианта: dec add ...")
        for d in rows:
            print(f"{d['id']} [{d['status']}] {d['decided_at']} · {d['decision']}")
            print(f"    ответственный: {d['owner']} · показатель: {d['metric'] or '—'} ({d['baseline'] or '?'} → {d['target'] or '?'}) · проверка: {d['check_date'] or '—'}")
            print(f"    основания: {', '.join(d['based_on']) or '—'}")
            for c in d["review_conditions"]:
                print(f"    пересмотреть, если: {c}")
            for c in d["commitments"]:
                print(f"    [{'x' if c['status'] == 'done' else ' '}] №{c['n']} {c['what']} — {c['owner']}, до {c['due']}")
    elif a.op == "due":
        flags = attention(p)
        print(f"На {today().isoformat()}:")
        if not flags:
            print("  Ничего срочного: просроченных обязательств, наступивших проверок и устаревших оснований нет.")
        for f in flags:
            print("  ! " + f)
        active = [d for d in rows if d.get("status") == "active"]
        upcoming = sorted((d["check_date"], d["id"], d["metric"]) for d in active if d.get("check_date") and _date(d["check_date"]) > today())
        for cd, did, metric in upcoming[:5]:
            print(f"  · {cd}: проверка по {did} — {metric}")


def register(sub):
    s = sub.add_parser("dec", help="решения: add / commit / fulfil / result / resolve / close / list / due")
    s.add_argument("op", choices=["add", "commit", "fulfil", "result", "resolve", "close", "list", "due"])
    s.add_argument("id", nargs="?"); s.add_argument("n", nargs="?")
    s.add_argument("--decision"); s.add_argument("--option"); s.add_argument("--rationale"); s.add_argument("--based-on")
    s.add_argument("--owner", help="роль, а не имя: «руководитель продукта»"); s.add_argument("--metric"); s.add_argument("--baseline")
    s.add_argument("--target"); s.add_argument("--check-date"); s.add_argument("--review-if", help="условия пересмотра через «;»")
    s.add_argument("--date"); s.add_argument("--what"); s.add_argument("--due"); s.add_argument("--result"); s.add_argument("--status")
    s.set_defaults(fn=cmd_dec)
