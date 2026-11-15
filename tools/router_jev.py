#!/usr/bin/env python3
"""Адаптер внешнего классификатора: Jev (TypeSafe AI) через агрегатор — AI/ML API или Electron Hub.

Подключить — переменными окружения или строками NAME=значение в файле .env в корне (он закрыт от git).
Файл .env.example — только образец, хранится в git: ключ туда не вписывается.
    JEV_API_KEY=<ключ агрегатора>
    STRATEG_ROUTER_CMD=python tools/router_jev.py
    JEV_API_URL=https://api.electronhub.ai/v1        (для Electron Hub; без переменной — AI/ML API)

Electron Hub: https://docs.electronhub.ai/api-reference/systemone.md (прочитана 13.11.2026) —
    POST /v1/systemone, псевдоним /v1/decisions; модель jev, принимает и typesafe/jev; тот же формат state/questions → answers;
    цена 0,042 $ за млн входных токенов, выход бесплатно; ключи вида ek-…, заголовок Authorization: Bearer.

Написан по странице документации агрегатора:
    https://docs.aimlapi.com/api-references/decision-models/typesafe/jev.md  (прочитана 12.11.2026)
    POST https://api.aimlapi.com/v1/decisions, заголовок Authorization: Bearer <ключ>
    тело: {"model": "typesafe/jev", "state": ..., "questions": {"<ключ>": {"type": "choice", "instructions": ..., "criteria": {...}}}}
    ответ: {"answers": {"<ключ>": {"choice": ..., "confidence": ..., "probabilities": {...}}}, "usage": {...}}

СОСТОЯНИЕ: проверен с настоящим сервисом 13.11.2026 через Electron Hub (5 запросов, ответы в документированном формате).
Через AI/ML API — только на локальной имитации (tests/selftest.py). При смене агрегатора сверьте адрес и поля.
Другой адрес (например, прямой API поставщика) задаётся JEV_API_URL, другая модель — JEV_MODEL.

Договор с маршрутизатором: на stdin — {"state": ..., "choice": {"instructions": ..., "criteria": {...}}},
на stdout — {"choice": ..., "probabilities": {...}, "confidence": ...}. Любая ошибка — код возврата 1:
маршрутизатор тогда откатывается на встроенные правила.
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strateglib.common import setting  # переменная окружения, иначе файл .env в корне

URL = (setting("JEV_API_URL") or "https://api.aimlapi.com/v1/decisions").rstrip("/")
if not URL.endswith(("/decisions", "/systemone")):
    URL += "/decisions"  # задан базовый адрес агрегатора (…/v1): у AI/ML API и Electron Hub путь /v1/decisions
MODEL = (setting("JEV_MODEL") or "typesafe/jev")


def main() -> int:
    key = setting("JEV_API_KEY")
    if not key:
        sys.stderr.write("router_jev: не задан JEV_API_KEY (ни в окружении, ни в .env)\n")
        return 1
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    body = {"model": MODEL, "state": req["state"],
            "questions": {"route": {"type": "choice", "instructions": req["choice"]["instructions"],
                                    "criteria": req["choice"]["criteria"]}}}
    http = urllib.request.Request(URL, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                  headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(http, timeout=float(setting("JEV_TIMEOUT_S") or "20")) as r:
            data = json.loads(r.read().decode("utf-8"))
        ans = data["answers"]["route"]
        out = {"choice": ans["choice"], "probabilities": ans.get("probabilities", {}), "confidence": float(ans.get("confidence", 0.0))}
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"router_jev: сервис ответил {e.code}\n")
        return 1
    except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError) as e:
        sys.stderr.write(f"router_jev: {type(e).__name__}: {e}\n")
        return 1
    usage = data.get("usage") or {}
    if usage:
        sys.stderr.write(f"router_jev: токены вход {usage.get('input_tokens')}, выход {usage.get('output_tokens')}\n")
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
