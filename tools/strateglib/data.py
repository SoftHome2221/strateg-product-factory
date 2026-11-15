"""Воспроизводимый анализ таблиц: профиль, когортное удержание, группировка, сравнение долей.

Числа считает скрипт, а не модель. Каждый запуск сохраняется в analysis/ вместе с командой и хэшем входа.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics as st
from pathlib import Path

from . import journal as jr
from .common import P, StrategError, now, read_jsonl, rel, sha256_bytes, append_jsonl
from .sources import read_csv_rows

DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%Y-%m", "%m.%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"]


def parse_date(s: str) -> dt.date | None:
    s = s.strip()
    for f in DATE_FORMATS:
        try:
            return dt.datetime.strptime(s[:19], f).date()
        except ValueError:
            continue
    return None


def parse_num(s: str) -> float | None:
    s = s.strip().replace("\xa0", "").replace(" ", "").replace("%", "")
    if not s:
        return None
    if re.fullmatch(r"-?\d+,\d+", s):
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def load(path: str) -> tuple[list[str], list[dict], Path]:
    f = Path(path)
    if not f.exists():
        raise StrategError(f"Файл не найден: {path}")
    if f.suffix.lower() == ".xlsx":
        raise StrategError("Сначала загрузите .xlsx через ingest — листы будут сохранены как CSV.")
    rows = read_csv_rows(f)
    if not rows:
        raise StrategError("Таблица пуста")
    head = [h.strip() for h in rows[0]]
    body = [dict(zip(head, r + [""] * (len(head) - len(r)))) for r in rows[1:] if any(c.strip() for c in r)]
    return head, body, f


def _col(head, name):
    if name not in head:
        raise StrategError(f"Нет столбца «{name}». Есть: {', '.join(head)}")
    return name


def _month(d: dt.date) -> str:
    return f"{d.year}-{d.month:02d}"


def _month_diff(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


def profile(head, body) -> dict:
    res = {"rows": len(body), "columns": [], "warnings": []}
    seen, dups = set(), 0
    for r in body:
        key = tuple(r.values())
        dups += key in seen
        seen.add(key)
    if dups:
        res["warnings"].append(f"полных дубликатов строк: {dups}")
    for h in head:
        vals = [r[h].strip() for r in body]
        filled = [v for v in vals if v and v.lower() not in ("na", "n/a", "null", "none", "-", "—", "nan")]
        miss = len(vals) - len(filled)
        nums = [parse_num(v) for v in filled]
        dates = [parse_date(v) for v in filled]
        col = {"name": h, "missing": miss, "missing_pct": round(100 * miss / max(1, len(vals)), 1), "unique": len(set(filled))}
        n_ok = sum(x is not None for x in nums)
        d_ok = sum(x is not None for x in dates)
        if filled and d_ok >= 0.9 * len(filled) and not (n_ok == len(filled) and all(len(v) <= 4 for v in filled)):
            ds = sorted(d for d in dates if d)
            col.update(type="дата", min=str(ds[0]), max=str(ds[-1]))
            months = sorted({_month(d) for d in ds})
            gaps = [m for a, b in zip(months, months[1:]) if _month_diff(a, b) > 1 for m in [f"{a}…{b}"]]
            if gaps:
                res["warnings"].append(f"«{h}»: пропущены месяцы между {', '.join(gaps[:5])}")
            if d_ok < len(filled):
                res["warnings"].append(f"«{h}»: {len(filled) - d_ok} значений не распознаны как дата")
        elif filled and n_ok >= 0.9 * len(filled):
            ns = [x for x in nums if x is not None]
            q = sorted(ns)
            col.update(type="число", min=q[0], max=q[-1], mean=round(st.fmean(ns), 3), median=st.median(ns),
                       p10=q[int(0.1 * (len(q) - 1))], p90=q[int(0.9 * (len(q) - 1))])
            if n_ok < len(filled):
                res["warnings"].append(f"«{h}»: {len(filled) - n_ok} значений не числа — возможно, смешаны форматы или единицы")
            if re.search(r"%|pct|share|доля|rate|конверс|удержан|retention", h, re.I):
                if q[-1] > 1.5 and q[0] >= 0 and q[-1] <= 100 and st.median(ns) <= 1:
                    res["warnings"].append(f"«{h}»: похоже, смешаны доли (0–1) и проценты (0–100)")
                if q[-1] > 100 or q[0] < 0:
                    res["warnings"].append(f"«{h}»: значения вне 0–100 для показателя-доли")
            if q[0] < 0 and re.search(r"count|кол|users|польз|выруч|revenue|price|цена|руб", h, re.I):
                res["warnings"].append(f"«{h}»: есть отрицательные значения")
            if len(ns) >= 8:
                med = st.median(ns)
                mad = st.median([abs(x - med) for x in ns]) or 1e-9
                out = [x for x in ns if abs(x - med) / (1.4826 * mad) > 6]
                if out:
                    res["warnings"].append(f"«{h}»: {len(out)} выбросов (напр. {out[0]}) — проверить единицы и ошибки ввода")
        else:
            top = sorted(((filled.count(v), v) for v in set(filled)), reverse=True)[:5]
            col.update(type="текст", top=[f"{v} ({c})" for c, v in top])
        if col["missing_pct"] >= 5:
            res["warnings"].append(f"«{h}»: пропусков {col['missing_pct']}% — решите, как их трактовать, до расчётов")
        if re.search(r"руб|₽|тыс|млн|usd|\$|%", h, re.I) is None and col.get("type") == "число" and \
                re.search(r"выруч|revenue|arpu|цена|price|стоим|cost|доход", h, re.I):
            res["warnings"].append(f"«{h}»: в названии не указаны единицы (₽, тыс. ₽?) — уточнить у владельца данных")
        res["columns"].append(col)
    return res


def retention(head, body, user: str, date: str, start: str | None = None) -> dict:
    """Когортное удержание по месяцам: когорта = месяц первой активности (или столбец start)."""
    _col(head, user), _col(head, date)
    first, active, bad = {}, {}, 0
    for r in body:
        d = parse_date(r[date])
        if not d or not r[user].strip():
            bad += 1
            continue
        u = r[user].strip()
        m = _month(d)
        active.setdefault(u, set()).add(m)
        s = parse_date(r[start]) if start and r.get(start) else None
        fm = _month(s) if s else m
        if u not in first or fm < first[u]:
            first[u] = fm
    if not first:
        raise StrategError("Не удалось прочитать ни одной строки: проверьте названия столбцов и формат дат")
    last_month = max(m for ms in active.values() for m in ms)
    cohorts = {}
    for u, c in first.items():
        cohorts.setdefault(c, []).append(u)
    table = []
    for c in sorted(cohorts):
        users = cohorts[c]
        horizon = _month_diff(c, last_month)
        row = {"cohort": c, "size": len(users), "retention": []}
        for k in range(horizon + 1):
            y, m = map(int, c.split("-"))
            m0 = (m - 1 + k)
            target = f"{y + m0 // 12}-{m0 % 12 + 1:02d}"
            row["retention"].append(round(100 * sum(1 for u in users if target in active[u]) / len(users), 1))
        table.append(row)
    notes = [f"последний месяц данных {last_month} может быть неполным — его значения не сравнивать с полными месяцами"]
    small = [r["cohort"] for r in table if r["size"] < 100]
    if small:
        notes.append(f"когорты меньше 100 пользователей ({', '.join(small)}): разница в несколько п. п. может быть шумом")
    if bad:
        notes.append(f"пропущено строк с нечитаемой датой или пустым пользователем: {bad}")
    return {"cohorts": table, "last_month": last_month, "users": len(first), "notes": notes}


def two_props(a: str, b: str) -> dict:
    def parse(s):
        m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", s)
        if not m or int(m.group(2)) == 0:
            raise StrategError("Формат: --a успехов/всего --b успехов/всего, например --a 120/1000 --b 150/1000")
        return int(m.group(1)), int(m.group(2))
    xa, na = parse(a)
    xb, nb = parse(b)
    pa, pb = xa / na, xb / nb
    diff = pb - pa
    se = math.sqrt(pa * (1 - pa) / na + pb * (1 - pb) / nb)
    pp = (xa + xb) / (na + nb)
    se0 = math.sqrt(pp * (1 - pp) * (1 / na + 1 / nb)) or 1e-12
    z = diff / se0
    pval = math.erfc(abs(z) / math.sqrt(2))
    notes = []
    if min(xa, xb, na - xa, nb - xb) < 10:
        notes.append("в одной из групп меньше 10 событий — нормальное приближение ненадёжно")
    if pval >= 0.05:
        notes.append("разница статистически не отличима от нуля на уровне 5% — это не доказательство отсутствия эффекта")
    return {"a": round(100 * pa, 2), "b": round(100 * pb, 2), "diff_pp": round(100 * diff, 2),
            "ci95_pp": [round(100 * (diff - 1.96 * se), 2), round(100 * (diff + 1.96 * se), 2)],
            "z": round(z, 2), "p_value": round(pval, 4), "notes": notes}


def groupby(head, body, by: str, metric: str | None, agg: str) -> dict:
    _col(head, by)
    groups = {}
    for r in body:
        groups.setdefault(r[by].strip() or "(пусто)", []).append(r)
    rows = []
    for g, rs in groups.items():
        row = {"group": g, "n": len(rs)}
        if metric:
            _col(head, metric)
            ns = [x for x in (parse_num(r[metric]) for r in rs) if x is not None]
            row["missing"] = len(rs) - len(ns)
            if ns:
                row["value"] = round({"mean": st.fmean, "sum": sum, "median": st.median, "min": min, "max": max}[agg](ns), 4)
        rows.append(row)
    rows.sort(key=lambda r: r["group"])
    return {"by": by, "metric": metric, "agg": agg if metric else "count", "groups": rows}


def _save(p: P, name: str, cmdline: str, f: Path | None, result: dict, md: str) -> str:
    p.analysis.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(f.read_bytes())[:16] if f else ""
    n = len(read_jsonl(p.analysis / "runs.jsonl")) + 1
    rid = f"A-{n:03d}"
    out = p.analysis / f"{rid}-{name}.md"
    out.write_text(f"<!-- расчёт {rid} · {now()} · вход: {rel(f) if f else '—'} sha256:{digest} -->\n"
                   f"<!-- повторить: python tools/strateg.py {cmdline} -->\n\n{md}\n", encoding="utf-8", newline="\n")
    append_jsonl(p.analysis / "runs.jsonl", {"id": rid, "ts": now(), "command": cmdline, "input": rel(f) if f else "",
                                              "input_sha256": digest, "output": rel(out), "result": result})
    jr.add(p, action=f"Расчёт {rid}: {cmdline[:90]}", tool="strateg data")
    return f"{rid} сохранён: {rel(out)}"


def cmd_data(a):
    import sys
    p = P(a.project)
    cmdline = "data " + " ".join(sys.argv[sys.argv.index("data") + 1:]) if "data" in sys.argv else "data"
    if a.op == "compare":
        if not (a.a and a.b):
            raise StrategError("Нужно: data compare --a 120/1000 --b 150/1000")
        r = two_props(a.a, a.b)
        md = (f"Группа A: {r['a']}% · группа B: {r['b']}% · разница B−A: {r['diff_pp']} п. п. "
              f"(95% ДИ: {r['ci95_pp'][0]}…{r['ci95_pp'][1]}) · z={r['z']}, p={r['p_value']}\n" + "\n".join("- " + n for n in r["notes"]))
        print(md)
        print(_save(p, "compare", cmdline, None, r, md))
        return
    if not a.file:
        raise StrategError("Укажите файл таблицы (csv/tsv)")
    head, body, f = load(a.file)
    if a.where:
        m = re.fullmatch(r"([^=]+)=(.*)", a.where)
        if not m:
            raise StrategError("Фильтр в формате --where столбец=значение")
        _col(head, m.group(1).strip())
        total = len(body)
        body = [r for r in body if r[m.group(1).strip()].strip() == m.group(2).strip()]
        print(f"Фильтр {a.where}: {len(body)} строк из {total}")
        if not body:
            raise StrategError("После фильтра не осталось строк")
    if a.op == "profile":
        r = profile(head, body)
        lines = [f"**Профиль {f.name}**: строк {r['rows']}, столбцов {len(head)}", "", "| Столбец | Тип | Пропуски | Уникальных | Диапазон / частые значения |", "|---|---|---|---|---|"]
        for c in r["columns"]:
            rng = f"{c.get('min')} … {c.get('max')}" + (f"; среднее {c['mean']}, медиана {c['median']}" if c.get("type") == "число" else "") \
                if c.get("type") in ("число", "дата") else "; ".join(c.get("top", []))
            lines.append(f"| {c['name']} | {c.get('type')} | {c['missing']} ({c['missing_pct']}%) | {c['unique']} | {rng} |")
        lines += ["", "**На что обратить внимание до расчётов:**"] + ([f"- {w}" for w in r["warnings"]] or ["- явных проблем не найдено"])
        md = "\n".join(lines)
    elif a.op == "retention":
        if not (a.user and a.date):
            raise StrategError("Нужно: data retention <файл> --user <столбец> --date <столбец> [--start <столбец>]")
        r = retention(head, body, a.user, a.date, a.start)
        width = max(len(c["retention"]) for c in r["cohorts"])
        lines = [f"**Удержание по месячным когортам** ({f.name}{'; фильтр ' + a.where if a.where else ''}; пользователей {r['users']}; данные по {r['last_month']})", "",
                 "| Когорта | Размер | " + " | ".join(f"M{k}" for k in range(width)) + " |", "|---|---|" + "---|" * width]
        for c in r["cohorts"]:
            cells = [f"{v}%" for v in c["retention"]] + [""] * (width - len(c["retention"]))
            if cells and c["retention"]:
                cells[len(c["retention"]) - 1] += "*"
            lines.append(f"| {c['cohort']} | {c['size']} | " + " | ".join(cells) + " |")
        lines += ["", "\\* — последний (возможно, неполный) месяц наблюдения", "", "**Оговорки:**"] + [f"- {n}" for n in r["notes"]]
        md = "\n".join(lines)
    elif a.op == "groupby":
        if not a.by:
            raise StrategError("Нужно: data groupby <файл> --by <столбец> [--metric <столбец> --agg mean|sum|median]")
        r = groupby(head, body, a.by, a.metric, a.agg)
        lines = [f"**{f.name}: {r['agg']}" + (f"({a.metric})" if a.metric else "") + f" по «{a.by}»**", "", "| Группа | Строк | Значение | Пропусков |", "|---|---|---|---|"]
        lines += [f"| {g['group']} | {g['n']} | {g.get('value', '—')} | {g.get('missing', 0)} |" for g in r["groups"]]
        md = "\n".join(lines)
    else:
        raise StrategError("Операции: profile, retention, groupby, compare")
    print(md)
    print(_save(p, a.op, cmdline, f, r, md))


def register(sub):
    s = sub.add_parser("data", help="расчёты по таблицам: profile / retention / groupby / compare")
    s.add_argument("op", choices=["profile", "retention", "groupby", "compare"]); s.add_argument("file", nargs="?")
    s.add_argument("--user"); s.add_argument("--date"); s.add_argument("--start"); s.add_argument("--by"); s.add_argument("--metric")
    s.add_argument("--agg", default="mean", choices=["mean", "sum", "median", "min", "max"]); s.add_argument("--a"); s.add_argument("--b")
    s.add_argument("--where", help="фильтр строк: столбец=значение")
    s.set_defaults(fn=cmd_data)
