#!/usr/bin/env python3
"""Заглушка внешнего классификатора для проверки точки подключения STRATEG_ROUTER_CMD.

Это НЕ модель: она считает пересечение слов подзадачи с описаниями вариантов и превращает счёт в вероятности.
Нужна, чтобы без сети и ключей проверить договор «варианты на входе → вероятности и уверенность на выходе»
и поведение каскада (уверенный ответ, неуверенный ответ, сбой).

Подключить:   STRATEG_ROUTER_CMD="python tools/router_stub.py"
Режимы для проверки сбоев: --unsure (низкая уверенность), --garbage (не JSON), --fail (код возврата 1).

Как заменить на настоящую модель (например, Jev): напишите такой же скрипт, который читает со stdin
{"state": ..., "choice": {"instructions": ..., "criteria": {...}}}, вызывает модель по её официальной документации
(примитив выбора из вариантов) и печатает {"choice": ..., "probabilities": {...}, "confidence": ...}.
Ключ доступа берётся из переменной окружения, а не из репозитория.
"""
import json
import math
import re
import sys


def words(text: str) -> set:
    return {w[:5] for w in re.findall(r"[a-zа-яё0-9]{3,}", text.lower().replace("ё", "е"))}


def main() -> int:
    args = sys.argv[1:]
    if "--fail" in args:
        sys.stderr.write("stub: имитация недоступности\n")
        return 1
    if "--garbage" in args:
        sys.stdout.write("это не JSON")
        return 0
    req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    state = words(req["state"])
    criteria = req["choice"]["criteria"]
    scores = {name: len(state & words(desc)) for name, desc in criteria.items()}
    if "--unsure" in args:
        scores = {name: 1 for name in criteria}
    z = sum(math.exp(1.5 * v) for v in scores.values())
    probs = {name: math.exp(1.5 * v) / z for name, v in scores.items()}
    ranked = sorted(probs.items(), key=lambda x: -x[1])
    out = {"choice": ranked[0][0], "probabilities": {k: round(v, 4) for k, v in probs.items()},
           "confidence": round(ranked[0][1] - ranked[1][1], 4)}
    sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
