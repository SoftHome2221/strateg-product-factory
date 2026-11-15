"""Сравнение словарного и векторного поиска по методике на перефразированных запросах.

Запуск:  python benchmarks/search_eval.py            (нужен Ollama с моделью bge-m3 для второго режима)
Запросы намеренно сформулированы другими словами, чем текст методики. Ожидаемый файл выбран автором набора заранее.
Мера: попал ли ожидаемый файл в первые три результата. Набор маленький (10 запросов) — это ориентир, а не оценка качества.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.stdout.reconfigure(encoding="utf-8")
from strateglib.search import search  # noqa: E402

CASES = [
    ("люди говорят что купят а потом не покупают", "interviews.md"),
    ("чем рискуем если пообещать в рекламе лишнее", "comm-strategy.md"),
    ("как понять что пора прекращать искать информацию", "research.md"),
    ("цифры в двух отчётах не сходятся", "evidence.md"),
    ("начальник просит рекламу а на самом деле проблема в другом", "framing.md"),
    ("все предложенные пути по сути одно и то же", "options.md"),
    ("продукт для всех подряд", "product-strategy.md"),
    ("как узнать что ставка не сработала", "validation-plan.md"),
    ("прошло три месяца и никто не помнит почему так решили", "decisions.md"),
    ("кнопку не видно на телефоне", "ux.md"),
]


def run(label):
    hits = 0
    for q, want in CASES:
        res = search(q, "kb", None, 3)
        files = [r["where"].split(":")[0].split("/")[-1] for r in res]
        ok = want in files
        hits += ok
        print(f"  {'+' if ok else '-'} {q[:52]:52} → {', '.join(files) or '—'}")
    print(f"{label}: {hits} из {len(CASES)} в первых трёх\n")
    return hits


os.environ.pop("STRATEG_EMBED_MODEL", None)
a = run("Словарный поиск")
os.environ["STRATEG_EMBED_MODEL"] = os.environ.get("EVAL_EMBED_MODEL", "bge-m3")
b = run("Словарный + векторный")
print(f"Итог: словарный {a}/{len(CASES)}, с векторами {b}/{len(CASES)}")
