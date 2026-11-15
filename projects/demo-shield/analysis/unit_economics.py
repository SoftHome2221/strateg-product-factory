"""Экономика на одного подключившегося за первые 6 месяцев, по каналам. УЧЕБНЫЕ данные.

Повторить: python projects/demo-shield/analysis/unit_economics.py
Вход: таблица активности S-003 и оценки затрат команды из справки S-001 (сведение E-008).
Допущения расчёта:
  - активен в месяце = заплатил за месяц; первый месяц бесплатный;
  - берутся только когорты с полными наблюдениями (последний месяц данных исключён как, возможно, неполный);
  - горизонт — сколько месяцев наблюдается самая ранняя когорта; более поздние когорты учитываются на своём горизонте.
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

PRICE, SERVICE = 149, 35           # ₽ в месяц
CAC = {"family": 0, "self": 90}    # ₽ за подключение (оценки команды)
LAST_MONTH = "2026-10"             # исключается как неполный

sys.stdout.reconfigure(encoding="utf-8")
src = Path(__file__).resolve().parents[1] / "sources" / "raw" / "S-003-events_demo.csv"
months = defaultdict(set)
channel = {}
with src.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        months[r["user_id"]].add(r["active_date"][:7])
        channel[r["user_id"]] = r["channel"]

print("| Канал | Пользователей | Платных месяцев на человека | Выручка, ₽ | Обслуживание, ₽ | Привлечение, ₽ | Итог на человека, ₽ |")
print("|---|---|---|---|---|---|---|")
for ch in ("family", "self"):
    users = [u for u in months if channel[u] == ch and min(months[u]) < "2026-09"]  # когорты май–август
    paid = active = 0
    for u in users:
        ms = {m for m in months[u] if m != LAST_MONTH}
        active += len(ms)
        paid += len(ms) - 1          # первый месяц бесплатный
    n = len(users)
    rev, serv = PRICE * paid / n, SERVICE * active / n
    print(f"| {ch} | {n} | {paid / n:.2f} | {rev:.0f} | {serv:.0f} | {CAC[ch]} | {rev - serv - CAC[ch]:+.0f} |")
print("\nКогорты май–август 2026, наблюдение по сентябрь 2026 включительно (от 2 до 5 месяцев на когорту).")
