<!-- расчёт A-001 · 2026-11-14T16:54:45+03:00 · вход: projects/cursor-seven-stage/sources/raw/S-003-contacts.csv sha256:67ee133ce34e7dc6 -->
<!-- повторить: python tools/strateg.py data -->

**Профиль S-003-contacts.csv**: строк 2000, столбцов 3

| Столбец | Тип | Пропуски | Уникальных | Диапазон / частые значения |
|---|---|---|---|---|
| unit | текст | 0 (0.0%) | 2000 | test_parents_1000 (1); test_parents_0999 (1); test_parents_0998 (1); test_parents_0997 (1); test_parents_0996 (1) |
| segment | текст | 0 (0.0%) | 2 | parents (1000); organizers (1000) |
| converted | число | 0 (0.0%) | 2 | 0.0 … 1.0; среднее 0.025, медиана 0.0 |

**На что обратить внимание до расчётов:**
- «converted»: 50 выбросов (напр. 1.0) — проверить единицы и ошибки ввода
