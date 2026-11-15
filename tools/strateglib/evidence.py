"""Реестр сведений (E-…) и выводов (C-…): откуда известно, что это за утверждение, что от него зависит.

Типы сведений:
  fact       — наблюдение из источника (нужны источник и место в нём);
  hypothesis — предположение, которое ещё предстоит проверить;
  forecast   — утверждение о будущем;
  synthetic  — получено от модельного (ИИ) респондента: годится для поиска гипотез, не доказывает спрос;
  inference  — рассуждение агента (в т.ч. из прошлых сеансов): никогда не становится фактом само по себе.
"""
from __future__ import annotations

import re

from . import journal as jr
from .common import ID_RE, P, StrategError, next_id, now, read_jsonl, rel, split_ids, write_jsonl

TYPES = {"fact": "ФАКТ", "hypothesis": "ГИПОТЕЗА", "forecast": "ПРОГНОЗ", "synthetic": "СИНТЕТИКА", "inference": "ВЫВОД АГЕНТА"}
NON_FACT_SOURCES = {"synthetic_interview"}


def _find(rows, rid):
    for r in rows:
        if r["id"] == rid:
            return r
    return None


def add_evidence(p: P, type_: str, claim: str, source: str | None = None, loc: str = "", quote: str = "",
                 period: str = "", conf: str = "medium", question: str = "", by: str = "agent", note: str = "") -> dict:
    if type_ not in TYPES:
        raise StrategError(f"Тип сведения: {', '.join(TYPES)}")
    rows = read_jsonl(p.evidence)
    src = None
    if source:
        src = _find(read_jsonl(p.sources_reg), source)
        if not src:
            raise StrategError(f"Источник {source} не найден в реестре. Сначала: python tools/strateg.py ingest ...")
        if src["status"] != "active":
            raise StrategError(f"Источник {source} отозван — на него нельзя опираться.")
    if type_ == "fact":
        if not src:
            raise StrategError("Факт требует источника (--source S-…). Без источника это гипотеза или вывод агента.")
        if src["kind"] in NON_FACT_SOURCES:
            raise StrategError("Ответ модельного респондента не может быть фактом. Используйте --type synthetic.")
        if not (loc or quote):
            raise StrategError("Для факта укажите место в источнике (--loc «стр. 3», «строка 14», «раздел …») или цитату (--quote).")
        if src.get("needs_transcript") or (src.get("needs_description") and not quote):
            raise StrategError(f"Содержание {source} агенту не известно (нет расшифровки/описания) — факт из него записать нельзя.")
    if type_ == "synthetic" and (not src or src["kind"] != "synthetic_interview"):
        raise StrategError("Тип synthetic требует источника вида synthetic_interview (запись беседы с модельным респондентом).")
    if src and src["kind"] == "synthetic_interview" and type_ != "synthetic":
        if type_ != "hypothesis":
            raise StrategError("Из беседы с модельным респондентом можно записать только synthetic или hypothesis.")
    dup = [e for e in rows if e["claim"].strip().lower() == claim.strip().lower() and e["status"] == "active"]
    if dup:
        raise StrategError(f"Такое сведение уже есть: {dup[0]['id']}", 3)
    rec = {"id": next_id(rows, "E"), "type": type_, "claim": claim.strip(), "source": source, "loc": loc, "quote": quote.strip(),
           "period": period, "confidence": conf, "question": question, "status": "active", "added_at": now(), "added_by": by}
    if note:
        rec["note"] = note
    rows.append(rec)
    write_jsonl(p.evidence, rows)
    return rec


def downstream(p: P, rid: str) -> dict:
    """Что зависит от записи rid: выводы (транзитивно), решения, места в документах."""
    concl = read_jsonl(p.conclusions)
    hit_ids, frontier = set(), {rid}
    while frontier:
        nxt = set()
        for c in concl:
            if c["id"] not in hit_ids and frontier & set(c.get("based_on", [])):
                hit_ids.add(c["id"])
                nxt.add(c["id"])
        frontier = nxt
    affected = {rid} | hit_ids
    decs = [d for d in read_jsonl(p.decisions) if affected & set(d.get("based_on", []))]
    mentions = []
    for folder in (p.outputs, p.state):
        for f in sorted(folder.glob("*.md")) if folder.exists() else []:
            if f.name == "report.md":
                continue
            heading = ""
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if line.startswith("#"):
                    heading = line.lstrip("# ").strip()
                found = affected & set(ID_RE.findall(line))
                if found and not line.startswith("#"):
                    mentions.append({"file": rel(f), "line": n, "section": heading, "ids": sorted(found), "text": line.strip()[:140]})
    return {"conclusions": [c for c in concl if c["id"] in hit_ids], "decisions": decs, "mentions": mentions}


def _flag_downstream(p: P, rid: str, reason: str) -> dict:
    d = downstream(p, rid)
    concl = read_jsonl(p.conclusions)
    ids = {c["id"] for c in d["conclusions"]}
    for c in concl:
        if c["id"] in ids and c["status"] == "active":
            c.update(status="needs_review", review_reason=reason, flagged_at=now())
    write_jsonl(p.conclusions, concl)
    decs = read_jsonl(p.decisions)
    dids = {x["id"] for x in d["decisions"]}
    for x in decs:
        if x["id"] in dids and x.get("status") == "active":
            x.setdefault("review_flags", []).append({"at": now(), "reason": reason})
    if dids:
        write_jsonl(p.decisions, decs)
    return d


def print_impact(d: dict, rid: str):
    if not (d["conclusions"] or d["decisions"] or d["mentions"]):
        print(f"От {rid} ничего не зависит: выводы, решения и документы на неё не ссылаются.")
        return
    if d["conclusions"]:
        print("Затронутые выводы:")
        for c in d["conclusions"]:
            print(f"  {c['id']} [{c['status']}] {c['text'][:120]}  ← {', '.join(c['based_on'])}")
    if d["decisions"]:
        print("Затронутые решения:")
        for x in d["decisions"]:
            print(f"  {x['id']} [{x['status']}] {x['decision'][:120]} · ответственный: {x.get('owner', '—')}")
    if d["mentions"]:
        print("Места в документах, которые нужно перечитать:")
        for m in d["mentions"]:
            print(f"  {m['file']}:{m['line']} · «{m['section']}» · {', '.join(m['ids'])}: {m['text']}")


def retract(p: P, rid: str, why: str, by: str | None = None) -> dict:
    rows = read_jsonl(p.evidence)
    e = _find(rows, rid)
    if not e:
        raise StrategError(f"Сведение {rid} не найдено")
    e.update(status="superseded" if by else "retracted", status_reason=why, status_at=now())
    if by:
        if not _find(rows, by):
            raise StrategError(f"Сведение {by} не найдено")
        e["superseded_by"] = by
    write_jsonl(p.evidence, rows)
    reason = f"{rid} {'заменено на ' + by if by else 'отозвано'}: {why}"
    d = _flag_downstream(p, rid, reason)
    jr.add(p, action=f"Сведение {reason}", tool="strateg ev")
    print(f"{rid}: {'заменено на ' + by if by else 'отозвано'}. Зависимые выводы помечены «нужен пересмотр».")
    print_impact(d, rid)
    return d


# ---------- команды ----------

def _fmt(e: dict, src_titles: dict) -> str:
    st = "" if e["status"] == "active" else f" [{'ОТОЗВАНО' if e['status'] == 'retracted' else 'ЗАМЕНЕНО → ' + e.get('superseded_by', '')}]"
    src = f" ← {e['source']}" + (f", {e['loc']}" if e.get("loc") else "") if e.get("source") else " ← без источника"
    per = f" · период: {e['period']}" if e.get("period") else ""
    return f"{e['id']} {TYPES[e['type']]:12} ({e['confidence']}){st} {e['claim']}{src}{per}"


def cmd_ev(a):
    p = P(a.project)
    rows = read_jsonl(p.evidence)
    if a.op == "add":
        if not a.claim:
            raise StrategError("Укажите утверждение: --claim \"...\"")
        rec = add_evidence(p, a.type, a.claim, a.source, a.loc or "", a.quote or "", a.period or "", a.conf, a.q or "", a.by, a.note or "")
        print(f"{rec['id']} записано как {TYPES[rec['type']]}. В тексте ссылайтесь так: [{rec['id']}]")
    elif a.op == "list":
        titles = {s["id"]: s["title"] for s in read_jsonl(p.sources_reg)}
        shown = 0
        for e in rows:
            if a.type and e["type"] != a.type:
                continue
            if a.q and e.get("question") != a.q:
                continue
            if not a.all and e["status"] != "active":
                continue
            print(_fmt(e, titles))
            shown += 1
        if not shown:
            print("Записей нет.")
        by_type = {}
        for e in rows:
            if e["status"] == "active":
                by_type[e["type"]] = by_type.get(e["type"], 0) + 1
        print("Итого действующих: " + (", ".join(f"{TYPES[k]} — {v}" for k, v in by_type.items()) or "0"))
    elif a.op == "show":
        e = _find(rows, a.id)
        if not e:
            raise StrategError(f"Сведение {a.id} не найдено")
        for k, v in e.items():
            print(f"{k}: {v}")
        s = _find(read_jsonl(p.sources_reg), e.get("source") or "")
        if s:
            print(f"источник: {s['title']} · {s['origin']} · получен {s['retrieved_at'][:10]} · текст: {s['text']}")
    elif a.op == "retract":
        if not a.why:
            raise StrategError("Укажите причину: --why \"...\"")
        retract(p, a.id, a.why)
    elif a.op == "supersede":
        if not (a.why and a.by_id):
            raise StrategError("Нужно: ev supersede E-001 --by-id E-010 --why \"...\"")
        retract(p, a.id, a.why, by=a.by_id)
    elif a.op == "edit":
        e = _find(rows, a.id)
        if not e:
            raise StrategError(f"Сведение {a.id} не найдено")
        if a.conf:
            e["confidence"] = a.conf
        if a.note:
            e["note"] = a.note
        if a.period:
            e["period"] = a.period
        e["edited_at"] = now()
        write_jsonl(p.evidence, rows)
        print(f"{a.id} обновлено. (Смысл утверждения не правится: отзовите и запишите новое.)")


def cmd_concl(a):
    p = P(a.project)
    rows = read_jsonl(p.conclusions)
    if a.op == "add":
        based = split_ids(a.based_on)
        if not (a.text and based):
            raise StrategError("Нужно: concl add --text \"...\" --based-on E-001,E-002")
        known = {e["id"]: e for e in read_jsonl(p.evidence)} | {c["id"]: c for c in rows}
        for b in based:
            if b not in known:
                raise StrategError(f"Основание {b} не найдено")
            if known[b]["status"] not in ("active",):
                raise StrategError(f"Основание {b} недействительно ({known[b]['status']}) — на него нельзя опираться.")
        types = {known[b].get("type") for b in based if b.startswith("E-")}
        strength = "опирается на факты" if types == {"fact"} else (
            "опирается только на гипотезы/синтетику — это предположение" if not ("fact" in types) else "смешанные основания")
        rec = {"id": next_id(rows, "C"), "text": a.text.strip(), "based_on": based, "kind": a.kind, "strength": strength,
               "status": "active", "added_at": now()}
        rows.append(rec)
        write_jsonl(p.conclusions, rows)
        print(f"{rec['id']} записан ({strength}). В тексте ссылайтесь так: [{rec['id']}]")
    elif a.op == "list":
        for c in rows:
            flag = "" if c["status"] == "active" else f" [{c['status'].upper()}: {c.get('review_reason', '')}]"
            print(f"{c['id']} ({c['strength']}){flag} {c['text']}  ← {', '.join(c['based_on'])}")
        if not rows:
            print("Выводов нет.")
    elif a.op in ("confirm", "retract"):
        c = _find(rows, a.id)
        if not c:
            raise StrategError(f"Вывод {a.id} не найден")
        if a.op == "confirm":
            if a.based_on:
                c["based_on"] = split_ids(a.based_on)
            if a.text:
                c["text"] = a.text.strip()
            c.update(status="active", reviewed_at=now(), review_note=a.why or "")
            c.pop("review_reason", None)
            print(f"{a.id} пересмотрен и подтверждён.")
        else:
            c.update(status="retracted", reviewed_at=now(), review_note=a.why or "")
            print(f"{a.id} отозван.")
        write_jsonl(p.conclusions, rows)
        if a.op == "retract":
            print_impact(_flag_downstream(p, a.id, f"вывод {a.id} отозван: {a.why or ''}"), a.id)
        jr.add(p, action=f"Вывод {a.id}: {'подтверждён после пересмотра' if a.op == 'confirm' else 'отозван'}. {a.why or ''}", tool="strateg concl")


def cmd_impact(a):
    p = P(a.project)
    rid = a.id
    if rid.startswith("S-"):
        evs = [e for e in read_jsonl(p.evidence) if e.get("source") == rid]
        print(f"Сведения из источника {rid}: {', '.join(e['id'] for e in evs) or '—'}")
        for e in evs:
            print(f"--- {e['id']}: {e['claim'][:100]}")
            print_impact(downstream(p, e["id"]), e["id"])
        return
    if not re.fullmatch(r"[EC]-\d+", rid):
        raise StrategError("Укажите id сведения (E-…), вывода (C-…) или источника (S-…)")
    print_impact(downstream(p, rid), rid)


def register(sub):
    s = sub.add_parser("ev", help="реестр сведений: add / list / show / retract / supersede / edit")
    s.add_argument("op", choices=["add", "list", "show", "retract", "supersede", "edit"])
    s.add_argument("id", nargs="?")
    s.add_argument("--type", choices=list(TYPES)); s.add_argument("--claim"); s.add_argument("--source")
    s.add_argument("--loc", help="место в источнике: страница, строка, раздел, тайм-код"); s.add_argument("--quote")
    s.add_argument("--period", help="к какому периоду относятся данные"); s.add_argument("--conf", choices=["high", "medium", "low"], default=None)
    s.add_argument("--q", help="номер вопроса исследования, напр. Q2"); s.add_argument("--by", default="agent")
    s.add_argument("--note"); s.add_argument("--why"); s.add_argument("--by-id"); s.add_argument("--all", action="store_true")
    s.set_defaults(fn=_ev_defaults)
    s = sub.add_parser("concl", help="выводы: add / list / confirm / retract")
    s.add_argument("op", choices=["add", "list", "confirm", "retract"]); s.add_argument("id", nargs="?")
    s.add_argument("--text"); s.add_argument("--based-on"); s.add_argument("--kind", default="conclusion", choices=["conclusion", "assumption"])
    s.add_argument("--why")
    s.set_defaults(fn=cmd_concl)
    s = sub.add_parser("impact", help="что затронуто, если сведение/вывод/источник изменились"); s.add_argument("id"); s.set_defaults(fn=cmd_impact)


def _ev_defaults(a):
    if a.op == "add":
        a.conf = a.conf or "medium"
        if not a.type:
            raise StrategError("Укажите тип: --type fact|hypothesis|forecast|synthetic|inference")
    cmd_ev(a)
