"""Контрольный замер «обычный чат»: один запрос локальной модели через Ollama, без репозитория, без поиска, без уточнений.

Запуск:  python benchmarks/run_baseline_ollama.py [модель]      (по умолчанию qwen2.5:7b)
Модель не видит файлов проекта: ей передаётся только текст запроса ниже. Результат и время сохраняются рядом.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5:7b"
PROMPT = ("Я руководитель продукта в МегаФоне. Мы планируем семейную подписку на облачное хранилище, её пока нет. "
          "До 30 ноября 2026 года мне нужно решить, кому её продавать: на какой сегмент сделать ставку при запуске, под кого "
          "строить состав подписки, сообщение и первые каналы. Возможен и ответ «отдельную семейную подписку не запускать». "
          "Внутренних данных у меня для тебя нет, используй только открытые источники, рынок — Россия. "
          "Сделай продуктовую и коммуникационную стратегию с рекомендацией. Читать буду с телефона, 5–10 минут.")

body = json.dumps({"model": MODEL, "stream": False, "messages": [{"role": "user", "content": PROMPT}]}).encode("utf-8")
t0 = time.time()
with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body,
                                                   headers={"Content-Type": "application/json"}), timeout=900) as r:
    data = json.loads(r.read().decode("utf-8"))
sec = round(time.time() - t0, 1)
text = data["message"]["content"]
out = Path(__file__).with_name(f"baseline-chat-{MODEL.replace(':', '-').replace('/', '-')}-family-cloud.md")
head = (f"<!-- Контрольный замер: «обычный чат», локальная модель {MODEL} через Ollama, один запрос, без веб-поиска, без уточнений,\n"
        f"без доступа к файлам репозитория. Время ответа {sec} с; токены: вход {data.get('prompt_eval_count')}, выход {data.get('eval_count')}.\n"
        f"Расход: 0 $ (локальный запуск). Запрос — в benchmarks/run_baseline_ollama.py. -->\n\n")
out.write_text(head + text + "\n", encoding="utf-8", newline="\n")
print(f"{out.name}: {sec} с, {len(text)} символов, токены {data.get('prompt_eval_count')}/{data.get('eval_count')}")
