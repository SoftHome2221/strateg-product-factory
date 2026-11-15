"""Генератор УЧЕБНЫХ данных для демо-проекта. Это не данные реального продукта.
Запуск: python projects/demo-shield/inbox/make_demo_data.py  (результат детерминирован, seed=42)
"""
import csv, random
from pathlib import Path

random.seed(42)
MONTHS = ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
# сколько новых пользователей пришло в когорте: (ребёнок подключил родителю, человек подключил себе по баннеру)
NEW = {"2026-05": (420, 180), "2026-06": (430, 320), "2026-07": (410, 520), "2026-08": (400, 760),
       "2026-09": (390, 1010), "2026-10": (400, 1250)}
# вероятность быть активным в k-й месяц после подключения
KEEP = {"family": [1, 0.78, 0.70, 0.66, 0.63, 0.61], "self": [1, 0.41, 0.27, 0.20, 0.16, 0.14]}
rows, uid = [], 0
for ci, m in enumerate(MONTHS):
    for channel, n in zip(("family", "self"), NEW[m]):
        for _ in range(n):
            uid += 1
            alive = True
            for k in range(len(MONTHS) - ci):
                if k > 0:
                    alive = alive and random.random() < KEEP[channel][k] / KEEP[channel][k - 1]
                if not alive:
                    break
                y, mo = MONTHS[ci + k].split("-")
                rows.append([f"u{uid:05d}", f"{y}-{mo}-{random.randint(1, 28):02d}", channel,
                             "trial" if k == 0 else "paid_149"])
out = Path(__file__).with_name("events_demo.csv")
with out.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f); w.writerow(["user_id", "active_date", "channel", "plan"]); w.writerows(rows)
print(f"{out.name}: {len(rows)} строк, {uid} пользователей")
