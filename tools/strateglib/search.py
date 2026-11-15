"""Поиск по базе знаний и материалам проекта: по формулировке, по смыслу и по связям.

По смыслу — два уровня. Всегда: основа слова и словарь синонимов (без моделей). Дополнительно, если задана
STRATEG_EMBED_MODEL (например, bge-m3 в локальном Ollama): векторные представления, смешанные со словарным счётом
пополам. Векторы кэшируются в .cache/; при недоступности модели поиск молча остаётся словарным.

Индекс строится на лету — он не может устареть. Отозванные записи в выдачу по умолчанию не попадают,
а ответы агента из прошлых сеансов помечаются как «вывод агента», а не как факт.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request

from .common import KNOWLEDGE, ROOT, P, StrategError, active_slug, read_json, read_jsonl, rel

_ENDINGS = sorted("""иями ями ами иях ями ость ости остью ение ения ению ением ений ание ания анию
ого его ому ему ыми ими ая яя ое ее ые ие ый ий ой ым им ом ем ах ях ов ев ей ам ям ую юю
ть ти ет ит ут ют ат ят ал ил ел ла ло ли ся сь а я о е ы и у ю ь""".split(), key=len, reverse=True)
_STOP = set("и в во не на с со к по из за от до для что как это то а но или же ли бы у о об при the a an of to in for and or is are".split())


def stem(w: str) -> str:
    if re.fullmatch(r"[a-z0-9]+", w):
        return w[:-1] if len(w) > 4 and w.endswith("s") else w
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[: -len(e)]
    return w


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-zа-яё0-9]+", text.lower().replace("ё", "е")) if w not in _STOP and len(w) > 1]


def _synonyms() -> dict[str, set[str]]:
    groups = read_json(KNOWLEDGE / "_synonyms.json", [])
    m = {}
    for g in groups:
        st = {t for w in g for t in tokens(w)}
        for t in st:
            m.setdefault(t, set()).update(st)
    return m


def _md_chunks(path, source_label: str, kind: str):
    heading, buf, start = path.stem, [], 1
    lines = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines + ["## "], 1):
        if re.match(r"^#{1,3} ", line) or (len(buf) > 40 and not line.strip()):
            body = "\n".join(buf).strip()
            if len(body) > 30:
                yield {"where": f"{rel(path)}:{start}", "title": heading, "text": body, "kind": kind, "label": source_label}
            buf, start = [], n
            if re.match(r"^#{1,3} ", line):
                heading = line.lstrip("# ").strip() or heading
        else:
            buf.append(line)


def corpus(scope: str, slug: str | None, include_inactive: bool = False) -> list[dict]:
    docs = []
    if scope in ("kb", "all"):
        for f in sorted(KNOWLEDGE.glob("*.md")):
            docs += list(_md_chunks(f, "методика", "kb"))
    slug = active_slug(slug, required=False)
    if scope in ("project", "all") and slug:
        p = P(slug)
        from .evidence import TYPES
        src = {s["id"]: s for s in read_jsonl(p.sources_reg)}
        for e in read_jsonl(p.evidence):
            if e["status"] != "active" and not include_inactive:
                continue
            st = "" if e["status"] == "active" else " · ОТОЗВАНО/ЗАМЕНЕНО — не использовать"
            docs.append({"where": e["id"], "title": f"{TYPES[e['type']]}{st}", "kind": "evidence", "label": f"сведение ← {e.get('source') or 'без источника'}",
                         "text": e["claim"] + (" «" + e["quote"] + "»" if e.get("quote") else "")})
        for c in read_jsonl(p.conclusions):
            if c["status"] == "retracted" and not include_inactive:
                continue
            docs.append({"where": c["id"], "title": f"ВЫВОД АГЕНТА ({c['strength']}; {c['status']})", "kind": "conclusion",
                         "label": "вывод ← " + ", ".join(c["based_on"]), "text": c["text"]})
        for d in read_jsonl(p.decisions):
            docs.append({"where": d["id"], "title": f"РЕШЕНИЕ ({d['status']})", "kind": "decision", "label": "решение",
                         "text": d["decision"] + " " + d.get("rationale", "")})
        for s in src.values():
            if s["status"] != "active" and not include_inactive:
                continue
            f = p.root.parent.parent / s["text"]
            if f.exists():
                for ch in _md_chunks(f, f"источник {s['id']}: {s['title'][:50]}", "source"):
                    docs.append(ch)
        for f in sorted(p.outputs.glob("*.md")):
            if f.name != "report.md":
                docs += list(_md_chunks(f, "результат агента (не факт)", "output"))
    return docs


def embed(texts: list[str]) -> list[list[float]] | None:
    """Векторные представления через локальную модель (Ollama /api/embed). None — если модель не задана или недоступна."""
    from .common import setting
    model = setting("STRATEG_EMBED_MODEL")
    if not model:
        return None
    url = os.environ.get("STRATEG_EMBED_URL", "http://127.0.0.1:11434/api/embed")
    cache_file = ROOT / ".cache" / ("embeddings-" + re.sub(r"[^\w.-]+", "_", model) + ".json")
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    except (OSError, ValueError):
        cache = {}
    keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
    todo = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in cache]
    try:
        for i in range(0, len(todo), 24):
            part = todo[i:i + 24]
            req = urllib.request.Request(url, data=json.dumps({"model": model, "input": [t for _k, t in part]}).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                vecs = json.loads(r.read().decode("utf-8"))["embeddings"]
            for (k, _t), v in zip(part, vecs):
                cache[k] = [round(x, 4) for x in v]
    except (OSError, ValueError, KeyError):
        return None
    if todo:
        cache_file.parent.mkdir(exist_ok=True)
        cache_file.write_text(json.dumps(cache), encoding="utf-8")
    return [cache[k] for k in keys]


def _cos(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def search(query: str, scope: str = "all", slug: str | None = None, top: int = 6, include_inactive: bool = False) -> list[dict]:
    docs = corpus(scope, slug, include_inactive)
    if not docs:
        return []
    syn = _synonyms()
    q = tokens(query)
    q_exp = {t: 1.0 for t in q}
    for t in q:
        for s in syn.get(t, ()):
            q_exp.setdefault(s, 0.6)
    toks = [tokens(d["title"] + " " + d["text"]) for d in docs]
    N = len(docs)
    avg = sum(len(t) for t in toks) / N
    df = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    scored = []
    for d, t in zip(docs, toks):
        tf = {}
        for w in t:
            tf[w] = tf.get(w, 0) + 1
        s = 0.0
        for w, weight in q_exp.items():
            if w in tf:
                idf = math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5))
                s += weight * idf * tf[w] * 2.5 / (tf[w] + 1.5 * (0.25 + 0.75 * len(t) / avg))
        title_t = set(tokens(d["title"]))
        s += 1.5 * len(title_t & set(q))
        if query.lower() in d["text"].lower():
            s += 3
        scored.append((s, d))
    vecs = embed([query] + [(d["title"] + ". " + d["text"])[:1200] for d in docs])
    if vecs:
        sims = [_cos(vecs[0], v) for v in vecs[1:]]
        lo, hi = min(sims), max(sims)
        mx = max(s for s, _d in scored) or 1.0
        scored = [(0.5 * s / mx + 0.5 * ((c - lo) / (hi - lo) if hi > lo else 0.0), {**d, "mode": "смысл+слова"})
                  for (s, d), c in zip(scored, sims)]
    else:
        scored = [(s, {**d, "mode": "слова"}) for s, d in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return [{**d, "score": round(s, 2)} for s, d in scored[:top]]


def snippet(text: str, query: str, width: int = 260) -> str:
    low = text.lower()
    pos = -1
    for w in re.findall(r"[a-zа-яё0-9]{4,}", query.lower()):
        pos = low.find(w[: max(4, len(w) - 2)])
        if pos >= 0:
            break
    start = max(0, pos - 60) if pos >= 0 else 0
    s = text[start:start + width].replace("\n", " ")
    return ("…" if start else "") + s + ("…" if start + width < len(text) else "")


def cmd_search(a):
    res = search(a.query, a.scope, a.project, a.top, a.all)
    if not res:
        print("Ничего не найдено. Попробуйте другую формулировку или --scope all.")
        return
    for r in res:
        print(f"[{r['score']} {r.get('mode', '')}] {r['where']} · {r['title']} · {r['label']}")
        print(f"     {snippet(r['text'], a.query)}")


def cmd_related(a):
    """Связи записи в обе стороны: на чём основана и что на неё опирается."""
    from .evidence import downstream, print_impact
    p = P(a.project)
    rid = a.id
    ev = {e["id"]: e for e in read_jsonl(p.evidence)}
    co = {c["id"]: c for c in read_jsonl(p.conclusions)}
    de = {d["id"]: d for d in read_jsonl(p.decisions)}
    src = {s["id"]: s for s in read_jsonl(p.sources_reg)}
    print(f"== {rid} ==")
    if rid in ev:
        e = ev[rid]
        print(f"{e['type']}: {e['claim']}")
        s = src.get(e.get("source") or "")
        print("Основание: " + (f"{s['id']} — {s['title']} ({s['origin']})" if s else "нет источника"))
    elif rid in co:
        print(co[rid]["text"])
        print("Основания:")
        for b in co[rid]["based_on"]:
            x = ev.get(b) or co.get(b)
            print(f"  {b}: {(x.get('claim') or x.get('text'))[:110] if x else '?'}")
    elif rid in de:
        print(de[rid]["decision"])
        print("Основания: " + ", ".join(de[rid].get("based_on", [])))
        return
    elif rid in src:
        print(src[rid]["title"])
        print("Сведения из источника: " + (", ".join(e["id"] for e in ev.values() if e.get("source") == rid) or "—"))
        return
    else:
        raise StrategError(f"Запись {rid} не найдена")
    print("Что опирается на запись:")
    print_impact(downstream(p, rid), rid)


def register(sub):
    s = sub.add_parser("search", help="поиск по методике и материалам проекта")
    s.add_argument("query"); s.add_argument("--scope", choices=["kb", "project", "all"], default="all")
    s.add_argument("--top", type=int, default=6); s.add_argument("--all", action="store_true", help="включая отозванные записи")
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("related", help="связи записи: основания и зависимые выводы"); s.add_argument("id"); s.set_defaults(fn=cmd_related)
