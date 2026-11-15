"""Линия безубыточности «удержание × стоимость привлечения» по каналам. УЧЕБНЫЕ данные.

Повторить: python projects/demo-shield/analysis/breakeven.py
Добавлен после замечания критика: пороги остановки нужно брать с одной линии, а не по отдельности.

Модель (упрощение, оговорено в тексте):
  итог на человека = (цена − обслуживание) × платные_месяцы × k − обслуживание_первого_месяца − привлечение,
  где k = (удержание второго месяца в сценарии) / (нынешнее удержание второго месяца канала):
  считаем, что вся кривая удержания сдвигается пропорционально.
Допущения: активен = заплатил; горизонт 2–5 месяцев (когорты май–август, наблюдение по сентябрь); затраты — оценки команды.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

PRICE, SERVICE, LAST = 149, 35, "2026-10"
sys.stdout.reconfigure(encoding="utf-8")
src = Path(__file__).resolve().parents[1] / "sources" / "raw" / "S-003-events_demo.csv"
months, channel = defaultdict(set), {}
with src.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        months[r["user_id"]].add(r["active_date"][:7])
        channel[r["user_id"]] = r["channel"]


def nxt(m):
    y, mo = map(int, m.split("-"))
    return f"{y + mo // 12}-{mo % 12 + 1:02d}"


base = {}
print("## Исходные величины (когорты май–август 2026)\n")
print("| Канал | Пользователей | Активны во втором месяце | M1 | Платных месяцев на человека |")
print("|---|---|---|---|---|")
for ch in ("family", "self"):
    users = [u for u in months if channel[u] == ch and min(months[u]) < "2026-09"]
    m1 = sum(1 for u in users if nxt(min(months[u])) in months[u])
    paid = sum(len({m for m in months[u] if m != LAST}) - 1 for u in users) / len(users)
    base[ch] = (m1 / len(users), paid)
    print(f"| {ch} | {len(users)} | {m1} | {100 * m1 / len(users):.1f}% | {paid:.2f} |")

print("\n## Итог на человека, ₽: удержание второго месяца × стоимость привлечения\n")
cacs = [0, 60, 90, 120, 150, 170]
for ch, rets in (("family", [0.80, 0.70, 0.60, 0.50]), ("self", [0.42, 0.60, 0.70, 0.80])):
    m1, paid = base[ch]
    print(f"**Канал {ch}** (сейчас M1 = {100 * m1:.0f}%)\n")
    print("| M1 в сценарии | " + " | ".join(f"привлечение {c} ₽" for c in cacs) + " | Привлечение, при котором итог = 0 |")
    print("|---|" + "---|" * (len(cacs) + 1))
    for r in rets:
        gross = (PRICE - SERVICE) * paid * (r / m1) - SERVICE
        print(f"| {100 * r:.0f}% | " + " | ".join(f"{gross - c:+.0f}" for c in cacs) + f" | {gross:.0f} ₽ |")
    print()
