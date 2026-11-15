"""Маршрутизация подзадач: какой процесс, уровень модели и инструмент выбрать — и исправление ошибочного выбора.

Каскад из трёх ступеней, от самой авторитетной к самой дешёвой:
  1. исправления человека и агента (config/routing_examples.jsonl) — ближайший пример;
  2. внешняя модель-классификатор, если задана STRATEG_ROUTER_CMD и она уверена не ниже порога;
  3. встроенные правила по ключевым словам (0 токенов).

Договор с внешним классификатором повторяет форму моделей, которые «выбирают из вариантов» (например, примитив Choice
у Jev): на stdin — JSON {"state": "<текст подзадачи>", "choice": {"instructions": "...", "criteria": {"<класс>": "<описание>"}}},
на stdout — JSON {"choice": "<класс>", "probabilities": {"<класс>": 0.0-1.0}, "confidence": 0.0-1.0}.
Принимается и короткий ответ {"class": "...", "confidence": ...}.
"""
from __future__ import annotations

import json
import os
import subprocess

from .common import CONFIG, P, StrategError, active_slug, append_jsonl, next_id, now, read_json, read_jsonl, write_jsonl
from .search import tokens

EXAMPLES = CONFIG / "routing_examples.jsonl"


def _cfg() -> dict:
    cfg = read_json(CONFIG / "routing.json")
    if not cfg:
        raise StrategError("Нет config/routing.json")
    return cfg


def _similarity(a: set, b: set) -> float:
    return len(a & b) / max(1, len(a | b))


def ask_external(text: str, cfg: dict) -> tuple[dict | None, str]:
    """Спрашивает внешний классификатор. Возвращает (ответ или None, пояснение для журнала)."""
    from .common import setting
    cmd = setting("STRATEG_ROUTER_CMD")
    if not cmd:
        return None, ""
    payload = {"state": text, "choice": {
        "instructions": "К какому классу подзадач относится эта работа агента-стратега?",
        "criteria": {name: c["label"] + ". Признаки: " + ", ".join(c["keywords"][:8]) for name, c in cfg["classes"].items()}}}
    try:
        # байты, а не текст: чужая команда может печатать в любой кодировке, и это не должно ронять маршрутизацию
        r = subprocess.run(cmd, input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True, shell=True,
                           timeout=cfg.get("external_timeout_s", 30))
        if r.returncode != 0:
            try:
                err = r.stderr.decode("utf-8")
            except UnicodeDecodeError:  # в Windows дочерний Python пишет stderr в кодировке системы
                import locale
                err = r.stderr.decode(locale.getpreferredencoding(False), "replace")
            err = (err.strip().splitlines() or [""])[-1][:150]
            return None, f"внешний классификатор завершился с кодом {r.returncode}" + (f" ({err})" if err else "") + ", использованы правила; "
        o = json.loads(r.stdout.decode("utf-8", "replace"))
        if not isinstance(o, dict):
            raise ValueError("ответ не объект")
    except subprocess.TimeoutExpired:
        return None, "внешний классификатор не ответил вовремя, использованы правила; "
    except (OSError, ValueError) as e:
        return None, f"внешний классификатор недоступен ({type(e).__name__}), использованы правила; "
    cls = o.get("choice") or o.get("class")
    if cls not in cfg["classes"]:
        return None, "внешний классификатор вернул неизвестный класс, использованы правила; "
    conf = float(o.get("confidence", 0.0))
    threshold = cfg.get("external_accept", 0.6)
    if conf < threshold:
        return None, f"внешний классификатор не уверен («{cls}», {conf:.2f} < порога {threshold}), использованы правила; "
    return {"class": cls, "confidence": round(conf, 2), "source": "external",
            "why": "внешний классификатор STRATEG_ROUTER_CMD" + (
                "; вероятности: " + ", ".join(f"{k} {v:.2f}" for k, v in sorted(o["probabilities"].items(), key=lambda x: -x[1])[:3])
                if isinstance(o.get("probabilities"), dict) else "")}, ""


def classify(text: str) -> dict:
    cfg = _cfg()
    t = set(tokens(text))
    best_ex, best_sim = None, 0.0
    for ex in read_jsonl(EXAMPLES):
        s = _similarity(t, set(tokens(ex["text"])))
        if s > best_sim:
            best_ex, best_sim = ex, s
    if best_ex and best_sim >= 0.5:
        return {"class": best_ex["class"], "confidence": round(min(0.95, 0.5 + best_sim / 2), 2), "source": "example",
                "why": f"похоже на исправленный ранее пример: «{best_ex['text'][:60]}»"}
    ext, note = ask_external(text, cfg)
    if ext:
        return ext
    scores = {}
    for name, c in cfg["classes"].items():
        kw = {s for k in c["keywords"] for s in tokens(k)}
        scores[name] = len(t & kw)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top, second = ranked[0], ranked[1]
    if top[1] == 0:
        return {"class": cfg["default_class"], "confidence": 0.3, "source": "rules",
                "why": note + "ключевых слов не найдено — класс по умолчанию"}
    conf = round(min(0.9, 0.45 + 0.15 * (top[1] - second[1]) + 0.05 * top[1]), 2)
    return {"class": top[0], "confidence": conf, "source": "rules",
            "why": note + f"совпадения по ключевым словам: {top[1]} (следующий класс «{second[0]}»: {second[1]})"}


def decide(text: str) -> dict:
    cfg = _cfg()
    r = classify(text)
    c = cfg["classes"][r["class"]]
    tier = c["tier"]
    env_models = cfg["tiers"]
    out = {**r, "label": c["label"], "process": c["process"], "tier": tier, "model_hint": env_models[tier], "tool": c["tool"],
           "escalate_if": c.get("escalate_if", "")}
    if r["confidence"] < cfg.get("low_confidence", 0.5):
        out["warning"] = "уверенность низкая: агент должен сам проверить выбор и при ошибке исправить его командой route fix"
    return out


def cmd_route(a):
    slug = active_slug(a.project, required=False)
    cfg = _cfg()
    if a.op == "classes":
        for name, c in cfg["classes"].items():
            print(f"{name:10} {c['label']}\n           процесс: {c['process']} · уровень: {c['tier']} ({cfg['tiers'][c['tier']]}) · инструмент: {c['tool']}")
        return
    if a.op == "fix":
        if not (a.text and a.cls and a.why):
            raise StrategError("Нужно: route fix R-003 --cls <класс> --why \"почему выбор был ошибочным\"")
        if a.cls not in cfg["classes"]:
            raise StrategError(f"Класс: {', '.join(cfg['classes'])}")
        p = P(slug)
        rows = read_jsonl(p.routes)
        for r in rows:
            if r["id"] == a.text:
                r.update(corrected_to=a.cls, correction_why=a.why, corrected_at=now())
                write_jsonl(p.routes, rows)
                append_jsonl(EXAMPLES, {"text": r["task"], "class": a.cls, "why": a.why, "from": r["class"], "at": now()[:10]})
                c = cfg["classes"][a.cls]
                print(f"{r['id']}: исправлено {r['class']} → {a.cls}. Пример сохранён в config/routing_examples.jsonl — похожие задачи теперь пойдут сюда.")
                print(f"Правильный маршрут: {c['process']} · уровень {c['tier']} ({cfg['tiers'][c['tier']]}) · {c['tool']}")
                return
        raise StrategError(f"Маршрут {a.text} не найден")
    if a.op == "escalate":
        p = P(slug)
        rows = read_jsonl(p.routes)
        order = ["script", "fast", "standard", "strong"]
        for r in rows:
            if r["id"] == a.text:
                cur = r.get("tier_used", r["tier"])
                nxt = order[min(len(order) - 1, order.index(cur) + 1)]
                r.update(tier_used=nxt, escalated_at=now(), escalation_why=a.why or "")
                write_jsonl(p.routes, rows)
                print(f"{r['id']}: уровень {cur} → {nxt} ({cfg['tiers'][nxt]}). Причина: {a.why or '—'}")
                return
        raise StrategError(f"Маршрут {a.text} не найден")
    if a.op == "list":
        for r in read_jsonl(P(slug).routes):
            fix = f" → ИСПРАВЛЕНО на {r['corrected_to']}: {r['correction_why']}" if r.get("corrected_to") else ""
            esc = f" → уровень повышен до {r['tier_used']}" if r.get("tier_used") else ""
            print(f"{r['id']} {r['class']:10} ({r['confidence']}) {r['task'][:70]}{fix}{esc}")
        return
    # op == "pick"
    if not a.text:
        raise StrategError("Нужно: route pick \"описание подзадачи\"")
    d = decide(a.text)
    rid = ""
    if slug:
        p = P(slug)
        rows = read_jsonl(p.routes)
        rid = next_id(rows, "R")
        append_jsonl(p.routes, {"id": rid, "ts": now(), "task": a.text, **{k: d[k] for k in ("class", "confidence", "source", "tier", "process", "tool", "why")}})
    print(f"{rid} класс: {d['class']} — {d['label']} (уверенность {d['confidence']}; {d['why']})")
    print(f"  процесс:    {d['process']}")
    print(f"  модель:     уровень «{d['tier']}» → {d['model_hint']}")
    print(f"  инструмент: {d['tool']}")
    if d["escalate_if"]:
        print(f"  повысить уровень, если: {d['escalate_if']}  (route escalate {rid} --why ...)")
    if d.get("warning"):
        print(f"  ВНИМАНИЕ: {d['warning']}")


def register(sub):
    s = sub.add_parser("route", help="маршрутизация: pick / fix / escalate / list / classes")
    s.add_argument("op", choices=["pick", "fix", "escalate", "list", "classes"]); s.add_argument("text", nargs="?")
    s.add_argument("--cls"); s.add_argument("--why")
    s.set_defaults(fn=cmd_route)
