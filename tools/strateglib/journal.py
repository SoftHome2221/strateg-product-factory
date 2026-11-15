"""Журнал действий и учёт стоимости: что сделано, чем, с каким итогом и сколько это стоило."""
from __future__ import annotations

import json
from pathlib import Path

from .common import CONFIG, P, StrategError, append_jsonl, next_id, now, read_json, read_jsonl, write_jsonl


def _prices() -> dict:
    return read_json(CONFIG / "prices.json", {"models": []})


def price_for(model: str | None) -> dict | None:
    if not model:
        return None
    m = model.lower()
    for row in _prices().get("models", []):
        if row["match"].lower() in m:
            return row
    return None


def cost_usd(model, tin=0, tout=0, cache_read=0, cache_write=0) -> float | None:
    pr = price_for(model)
    if not pr:
        return None
    return round((tin * pr["in"] + tout * pr["out"] + cache_read * pr.get("cache_read", pr["in"] * 0.1)
                  + cache_write * pr.get("cache_write", pr["in"] * 1.25)) / 1_000_000, 4)


def _stage_of(p: P) -> str:
    t = read_json(p.task, {})
    return t.get("stage", "")


def find_done(p: P, key: str) -> dict | None:
    for j in read_jsonl(p.journal):
        if j.get("key") == key and j.get("status") == "done":
            return j
    return None


def add(p: P, action: str, tool: str = "", stage: str | None = None, status: str = "done", key: str | None = None,
        model: str | None = None, tokens_in: int = 0, tokens_out: int = 0, minutes: float = 0,
        human_minutes: float = 0, note: str = "", error: str = "", auto: bool = False) -> dict:
    rows = read_jsonl(p.journal)
    row = {"id": next_id(rows, "J", 4), "ts": now(), "stage": stage or _stage_of(p), "action": action,
           "tool": tool, "status": status}
    if key:
        row["key"] = key
    if model or tokens_in or tokens_out:
        row.update(model=model or "", tokens_in=tokens_in, tokens_out=tokens_out, measured=False)
        c = cost_usd(model, tokens_in, tokens_out)
        if c is not None:
            row["cost_usd"] = c
    if minutes:
        row["minutes"] = minutes
    if human_minutes:
        row["human_minutes"] = human_minutes
    if note:
        row["note"] = note
    if error:
        row["error"] = error
    if auto:
        row["auto"] = True
    append_jsonl(p.journal, row)
    return row


def unfinished(p: P) -> list[dict]:
    return [j for j in read_jsonl(p.journal) if j.get("status") == "started"]


# ---------- измеренные расходы сессий (из транскрипта среды) ----------

def _parse_claude(tp: Path):
    """Транскрипт Claude Code: usage в сообщениях ассистента, повтор по id не считается дважды."""
    files = [tp]
    sub = tp.with_suffix("") / "subagents"
    if sub.is_dir():
        files += sorted(sub.glob("*.jsonl"))
    seen, by_model = set(), {}
    first = last = None
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(o, dict):
                continue
            ts = o.get("timestamp")
            if ts:
                first = first or ts
                last = ts
            msg = o.get("message") or {}
            u = msg.get("usage") if isinstance(msg, dict) else None
            if o.get("type") != "assistant" or not u:
                continue
            mid = msg.get("id") or o.get("uuid")
            if mid in seen:
                continue
            seen.add(mid)
            m = by_model.setdefault(msg.get("model", "unknown"), {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0})
            m["in"] += u.get("input_tokens", 0) or 0
            m["out"] += u.get("output_tokens", 0) or 0
            m["cache_read"] += u.get("cache_read_input_tokens", 0) or 0
            m["cache_write"] += u.get("cache_creation_input_tokens", 0) or 0
            m["calls"] += 1
    return by_model, first, last


def _codex_first(f: Path) -> dict:
    try:
        with f.open(encoding="utf-8", errors="replace") as fh:
            o = json.loads(fh.readline())
        return (o.get("payload") or {}) if o.get("type") == "session_meta" else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _parse_codex(tp: Path):
    """Транскрипт Codex (rollout-*.jsonl): нарастающий счётчик token_count, модель из turn_context.
    Потоки субагентов лежат отдельными файлами рядом и находятся по идентификатору родителя."""
    meta = _codex_first(tp)
    ids = {x for x in (meta.get("id"), meta.get("session_id")) if x}
    files = [tp]
    if ids:
        for f in sorted(tp.parent.glob("rollout-*.jsonl")):
            if f != tp:
                m = _codex_first(f)
                if {m.get("session_id"), m.get("parent_thread_id")} & ids:
                    files.append(f)
    by_model = {}
    first = last = None
    for f in files:
        model, prev = "unknown", {}
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(o, dict):
                continue
            ts = o.get("timestamp")
            if ts:
                first = min(first, ts) if first else ts
                last = max(last, ts) if last else ts
            pl = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            if o.get("type") == "turn_context" and pl.get("model"):
                model = pl["model"]
            if o.get("type") == "event_msg" and pl.get("type") == "token_count":
                tot = (pl.get("info") or {}).get("total_token_usage") or {}
                if not tot:
                    continue
                # счётчик нарастающий: модели достаётся прирост с прошлой отметки
                d = {k: max(0, (tot.get(k) or 0) - (prev.get(k) or 0)) for k in
                     ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")}
                prev = tot
                if not any(d.values()):
                    continue
                m = by_model.setdefault(model, {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0})
                m["in"] += max(0, d["input_tokens"] - d["cached_input_tokens"] - d["cache_write_input_tokens"])
                m["cache_read"] += d["cached_input_tokens"]
                m["cache_write"] += d["cache_write_input_tokens"]
                m["out"] += d["output_tokens"]
                m["calls"] += 1
    return by_model, first, last


def _transcript_kind(tp: Path) -> str:
    try:
        with tp.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        return ""
    return "codex" if '"session_meta"' in head or tp.name.startswith("rollout-") else "claude"


def _excluded_path(p: P) -> Path:
    return p.state / "sessions_excluded.jsonl"


def excluded_sessions() -> set:
    """Сеансы, исключённые из расхода (например, разработка репозитория), — по всем проектам: такой сеанс
    не записывается заново ни в один проект, даже если активный проект сменился."""
    from .common import PROJECTS
    ids = set()
    for d in PROJECTS.iterdir() if PROJECTS.exists() else []:
        f = d / "state" / "sessions_excluded.jsonl"
        if f.exists():
            ids |= {r.get("session_id") for r in read_jsonl(f)}
    return ids


def _save_session(p: P, rec: dict) -> dict:
    if rec["session_id"] in excluded_sessions():
        return rec
    rows = [r for r in read_jsonl(p.sessions) if r.get("session_id") != rec["session_id"]] + [rec]
    write_jsonl(p.sessions, rows)
    return rec


def record_session(p: P, session_id: str, transcript_path: str, env: str = "claude-code") -> dict | None:
    """Считает токены по транскрипту среды (Claude Code или Codex) и сохраняет итог сеанса. Идемпотентно."""
    tp = Path(transcript_path)
    if not tp.exists():
        return None
    by_model, first, last = (_parse_codex if _transcript_kind(tp) == "codex" else _parse_claude)(tp)
    if not by_model:
        return None
    total, unknown = 0.0, []
    for model, m in by_model.items():
        c = cost_usd(model, m["in"], m["out"], m["cache_read"], m["cache_write"])
        m["cost_usd"] = c
        if c is None:
            unknown.append(model)
        else:
            total += c
    return _save_session(p, {"session_id": session_id, "env": env, "first_ts": first, "last_ts": last, "models": by_model,
                             "cost_usd": round(total, 4), "unpriced_models": unknown, "measured": True, "updated_at": now()})


def record_time(p: P, session_id: str, first_ts: str, last_ts: str, env: str) -> dict | None:
    """Среда не отдаёт транскрипт: сохраняется только время сеанса по часам хука, токены остаются неизвестными.
    Запись с измеренными токенами этим не затирается."""
    old = next((r for r in read_jsonl(p.sessions) if r.get("session_id") == session_id), None)
    if old and old.get("models"):
        return old
    return _save_session(p, {"session_id": session_id, "env": env, "first_ts": (old or {}).get("first_ts") or first_ts,
                             "last_ts": last_ts, "models": {}, "cost_usd": 0, "unpriced_models": [], "measured": False,
                             "time_only": True, "updated_at": now()})


def _minutes_between(a: str | None, b: str | None) -> float:
    import datetime as dt
    if not a or not b:
        return 0.0
    try:
        da = dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
        db = dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
        return max(0.0, (db - da).total_seconds() / 60)
    except ValueError:
        return 0.0


def _sessions(p: P) -> list[dict]:
    """Сеансы проекта; модели, у которых при записи не было цены, пересчитываются по текущему config/prices.json."""
    ses = read_jsonl(p.sessions)
    for s in ses:
        if not s.get("unpriced_models"):
            continue
        still = []
        for model in s["unpriced_models"]:
            m = s["models"].get(model)
            c = cost_usd(model, m["in"], m["out"], m["cache_read"], m["cache_write"]) if m else None
            if c is None:
                still.append(model)
            else:
                m["cost_usd"] = c
                s["cost_usd"] = round((s.get("cost_usd") or 0) + c, 4)
        s["unpriced_models"] = still
    return ses


def totals(p: P) -> dict:
    ses = _sessions(p)
    jr = read_jsonl(p.journal)
    meas_cost = sum(s.get("cost_usd") or 0 for s in ses)
    meas_tok = sum(m["in"] + m["out"] + m["cache_read"] + m["cache_write"] for s in ses for m in s["models"].values())
    est_cost = sum(j.get("cost_usd") or 0 for j in jr if not j.get("measured", True))
    est_tok = sum((j.get("tokens_in") or 0) + (j.get("tokens_out") or 0) for j in jr)
    return {
        "sessions": len(ses), "time_only": sum(1 for s in ses if not s.get("models")), "measured_cost_usd": round(meas_cost, 2), "measured_tokens": meas_tok,
        "estimated_cost_usd": round(est_cost, 2), "estimated_tokens": est_tok,
        "session_minutes": round(sum(_minutes_between(s.get("first_ts"), s.get("last_ts")) for s in ses)),
        "tool_minutes": round(sum(j.get("minutes") or 0 for j in jr), 1),
        "human_minutes": round(sum(j.get("human_minutes") or 0 for j in jr), 1),
        "human_time_recorded": any("human_minutes" in j for j in jr),
        "actions": len(jr), "failed": sum(1 for j in jr if j.get("status") == "failed"),
        "unpriced": sorted({m for s in ses for m in s.get("unpriced_models", [])}),
    }


def cost_line(p: P) -> str:
    t = totals(p)
    parts = [f"действий в журнале: {t['actions']}"]
    if t["sessions"]:
        if t["sessions"] == t["time_only"]:
            parts.append(f"только время {t['sessions']} сеансов: ~{t['session_minutes']} мин; токены и деньги неизвестны")
        else:
            parts.append(f"измерено по {t['sessions'] - t['time_only']} сеансам: ${t['measured_cost_usd']}; интервал ~{t['session_minutes']} мин"
                         + (f"; ещё {t['time_only']} сеансов без счётчиков, сумма неполная" if t["time_only"] else "")
                         + (f"; нет цены для: {', '.join(t['unpriced'])}" if t["unpriced"] else ""))
    if t["estimated_cost_usd"]:
        parts.append(f"оценка вручную: ${t['estimated_cost_usd']}")
    if t["human_time_recorded"]:
        parts.append(f"время человека: {t['human_minutes']} мин")
    else:
        parts.append("время человека не записано")
    return "Расходы: " + " · ".join(parts) + " (подробно: python tools/strateg.py cost)"


def cost_report(p: P) -> str:
    t = totals(p)
    pr = _prices()
    rub = pr.get("usd_rub")
    hr = pr.get("human_hour_rub")
    out = ["## Сколько это стоило", ""]
    out.append("| Статья | Значение | Как получено |")
    out.append("|---|---|---|")
    if t["sessions"]:
        known = t["sessions"] - t["time_only"]
        if known:
            label = "известная часть" if t["time_only"] or t["unpriced"] else "измерено"
            out.append(f"| Модели ({label}) | ${t['measured_cost_usd']} · {t['measured_tokens']:,} токенов | "
                       f"счётчики токенов {known} сеансов × цены из config/prices.json; сеансы без счётчиков в сумму не входят |".replace(",", " "))
        else:
            out.append("| Модели (измерено) | нет данных о токенах и деньгах | записи только времени не означают нулевой расход |")
        out.append(f"| Время сеансов | ~{t['session_minutes']} мин | календарный интервал от первого до последнего сообщения, включая ожидание человека; не рабочее время |")
        if t["time_only"]:
            out.append(f"| Сеансы без счётчика токенов | {t['time_only']} | среда не отдаёт транскрипт, измерено только время; "
                       f"расход внесите вручную: `log add ... --model --tokens-in --tokens-out` |")
    else:
        out.append("| Модели (измерено) | нет данных | среда не передаёт транскрипт; внесите расход из счётчика среды: `log add ... --model --tokens-in --tokens-out` |")
    if t["estimated_tokens"]:
        out.append(f"| Модели (внесено вручную) | ${t['estimated_cost_usd']} · {t['estimated_tokens']:,} токенов | записи журнала с --tokens-in/--tokens-out |".replace(",", " "))
    out.append(f"| Действия | {t['actions']} (сбоев: {t['failed']}) | журнал state/journal.jsonl |")
    if t["tool_minutes"]:
        out.append(f"| Время инструментов | {t['tool_minutes']} мин | записи журнала |")
    hm = t["human_minutes"]
    human_cost = f" ≈ {round(hm / 60 * hr)} ₽" if (hr and hm) else ""
    human_value = f"{hm} мин{human_cost}" if t["human_time_recorded"] else "не записано"
    out.append(f"| Время человека (ответы, правки) | {human_value} | записи журнала с --human-minutes |")
    total_usd = t["measured_cost_usd"] + t["estimated_cost_usd"]
    if rub:
        if t["sessions"] > t["time_only"] or t["estimated_tokens"]:
            label = "Итого модели (известная часть)" if t["time_only"] or t["unpriced"] else "Итого модели"
            out.append(f"| {label} | ${round(total_usd, 2)} ≈ {round(total_usd * rub)} ₽ | курс {rub} ₽/$ из config/prices.json |")
        else:
            out.append("| Итого модели | нет данных | расход без счётчиков не оценён |")
    excl = read_jsonl(_excluded_path(p)) if _excluded_path(p).exists() else []
    if excl:
        out.append("")
        out.append(f"Исключено из расхода сеансов: {len(excl)} — " + "; ".join(
            f"{e['session_id'][:8]}… ({(e.get('record') or {}).get('cost_usd', 0)} $): {e.get('why', '')}" for e in excl))
    if t["unpriced"]:
        out.append("")
        out.append(f"Нет цены для моделей: {', '.join(t['unpriced'])} — добавьте их в config/prices.json, иначе сумма занижена.")
    ses = _sessions(p)
    if any(s.get("models") for s in ses):
        out += ["", "| Модель | Вызовов | Вход | Выход | Кэш (чтение) | Кэш (запись) | $ |", "|---|---|---|---|---|---|---|"]
        agg = {}
        for s in ses:
            for model, m in s["models"].items():
                a = agg.setdefault(model, {"calls": 0, "in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0})
                for k in ("calls", "in", "out", "cache_read", "cache_write"):
                    a[k] += m[k]
                a["cost"] += m.get("cost_usd") or 0
        for model, a in sorted(agg.items()):
            out.append(f"| {model} | {a['calls']} | {a['in']} | {a['out']} | {a['cache_read']} | {a['cache_write']} | {round(a['cost'], 2)} |")
    by_stage = {}
    for j in read_jsonl(p.journal):
        by_stage[j.get("stage") or "—"] = by_stage.get(j.get("stage") or "—", 0) + 1
    if by_stage:
        out += ["", "Действий по этапам: " + ", ".join(f"{k} — {v}" for k, v in by_stage.items())]
    return "\n".join(out)


# ---------- команды ----------

def cmd_log(a):
    p = P(a.project)
    if a.op == "add":
        if a.key and not a.force:
            d = find_done(p, a.key)
            if d:
                raise StrategError(f"УЖЕ ВЫПОЛНЕНО: {d['id']} от {d['ts'][:16]} — {d['action']}. "
                                   f"Повтор не нужен; для осознанного повтора добавьте --force.", 3)
        row = add(p, a.text, tool=a.tool or "", status=a.status, key=a.key, model=a.model, tokens_in=a.tokens_in,
                  tokens_out=a.tokens_out, minutes=a.minutes, human_minutes=a.human_minutes, note=a.note or "",
                  error=a.error or "")
        print(f"{row['id']} записано ({row['status']}).")
    elif a.op == "start":
        if a.key and not a.force:
            d = find_done(p, a.key)
            if d:
                raise StrategError(f"УЖЕ ВЫПОЛНЕНО: {d['id']} от {d['ts'][:16]} — {d['action']}. "
                                   f"Возьмите готовый результат; для осознанного повтора добавьте --force.", 3)
        row = add(p, a.text, tool=a.tool or "", status="started", key=a.key)
        print(f"{row['id']} начато. По завершении: log done {row['id']}  |  при сбое: log fail {row['id']} --error \"...\"")
    elif a.op in ("done", "fail"):
        rows = read_jsonl(p.journal)
        for r in rows:
            if r["id"] == a.text:
                r["status"] = "done" if a.op == "done" else "failed"
                r["finished_at"] = now()
                if a.note:
                    r["note"] = a.note
                if a.error:
                    r["error"] = a.error
                write_jsonl(p.journal, rows)
                print(f"{r['id']}: {r['status']}")
                return
        raise StrategError(f"Запись {a.text} не найдена в журнале")
    elif a.op == "list":
        rows = read_jsonl(p.journal)[-(a.last or 20):]
        for r in rows:
            extra = f" [{r['tool']}]" if r.get("tool") else ""
            err = f" — ОШИБКА: {r['error'][:100]}" if r.get("error") else ""
            print(f"{r['id']} {r['ts'][:16]} {r.get('stage', ''):9} {r['status']:8} {r['action'][:110]}{extra}{err}")


def cmd_cost(a):
    p = P(a.project)
    if a.exclude:
        if not a.why:
            raise StrategError("Укажите причину: --why \"...\"")
        rows = read_jsonl(p.sessions)
        hit = [r for r in rows if r.get("session_id") == a.exclude]
        write_jsonl(p.sessions, [r for r in rows if r.get("session_id") != a.exclude])
        old = read_jsonl(_excluded_path(p)) if _excluded_path(p).exists() else []
        write_jsonl(_excluded_path(p), [r for r in old if r.get("session_id") != a.exclude] + [
            {"session_id": a.exclude, "why": a.why, "excluded_at": now(), "record": hit[0] if hit else None}])
        add(p, action=f"Сеанс {a.exclude} исключён из расхода проекта: {a.why}", tool="strateg cost")
        print(f"Сеанс {a.exclude} исключён" + (f" (был ${hit[0].get('cost_usd', 0)})" if hit else " (в расходе его не было)")
              + "; повторно он не запишется ни в один проект.")
        return
    print(cost_report(p))


def register(sub):
    s = sub.add_parser("log", help="журнал действий: add / start / done / fail / list")
    s.add_argument("op", choices=["add", "start", "done", "fail", "list"])
    s.add_argument("text", nargs="?", default="", help="описание действия (add/start) или id записи (done/fail)")
    s.add_argument("--tool"); s.add_argument("--status", default="done", choices=["done", "failed", "skipped"])
    s.add_argument("--key", help="ключ идемпотентности: повтор с тем же ключом будет остановлен")
    s.add_argument("--force", action="store_true")
    s.add_argument("--model"); s.add_argument("--tokens-in", type=int, default=0); s.add_argument("--tokens-out", type=int, default=0)
    s.add_argument("--minutes", type=float, default=0); s.add_argument("--human-minutes", type=float, default=0)
    s.add_argument("--note"); s.add_argument("--error"); s.add_argument("--last", type=int)
    s.set_defaults(fn=cmd_log)
    s = sub.add_parser("cost", help="отчёт о расходах: модели, время, человек; --exclude <id сеанса> --why — убрать сеанс")
    s.add_argument("--exclude", help="id сеанса, который не относится к проекту (например, разработка репозитория)")
    s.add_argument("--why")
    s.set_defaults(fn=cmd_cost)
