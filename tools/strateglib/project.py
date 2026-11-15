"""Проект и состояние задачи: создание, этапы, вопросы человеку, продолжение после перерыва."""
from __future__ import annotations

import re
import shutil

from .common import (CONFIG, PROJECTS, TEMPLATES, P, StrategError, active_slug, now, read_json,
                     read_jsonl, rel, today, write_json)

# (код, название, нужен ли выбор человека, файл-результат)
STAGES = [
    ("brief", "Постановка задачи", True, "outputs/01-brief.md"),
    ("collect", "Сбор материалов", False, None),
    ("research", "Исследование и картина ситуации", True, "outputs/02-situation.md"),
    ("options", "Варианты", True, "outputs/03-options.md"),
    ("strategy", "Продуктовая и коммуникационная стратегия", False, "outputs/04-strategy.md"),
    ("review", "Проверка и выпуск отчёта", True, "outputs/report.md"),
    ("support", "Сопровождение решения", False, None),
]
STAGE_CODES = [s[0] for s in STAGES]
STAGE_SKILL = {
    "brief": "strateg-brief", "collect": "strateg-collect", "research": "strateg-research",
    "options": "strateg-options", "strategy": "strateg-strategy", "review": "strateg-review",
    "support": "strateg-support",
}
HUMAN_GATE_TEXT = {
    "brief": "человек подтвердил постановку (вопрос, цель, получатель, ограничения)",
    "research": "человек посмотрел картину ситуации и решил: достаточно или копать дальше",
    "options": "человек выбрал вариант (или попросил доработать)",
    "review": "человек принял итоговый отчёт",
}


def _stage(code: str):
    for s in STAGES:
        if s[0] == code:
            return s
    raise StrategError(f"Неизвестный этап «{code}». Допустимые: {', '.join(STAGE_CODES)}")


def load_task(p: P) -> dict:
    t = read_json(p.task)
    if t is None:
        raise StrategError(f"Нет файла состояния {rel(p.task)}")
    return t


def save_task(p: P, t: dict) -> None:
    t["updated_at"] = now()
    write_json(p.task, t)


# ---------- команды ----------

def cmd_new(a):
    slug = a.slug
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", slug):
        raise StrategError("slug: латиница в нижнем регистре, цифры и дефис, например retention-q4")
    root = PROJECTS / slug
    if root.exists():
        raise StrategError(f"Проект «{slug}» уже существует. Продолжить: python tools/strateg.py use {slug}")
    for d in ("sources/raw", "sources/text", "evidence", "state", "outputs", "analysis", "decisions"):
        (root / d).mkdir(parents=True, exist_ok=True)
    policy = read_json(CONFIG / "policy.json", {})
    write_json(root / "project.json", {
        "slug": slug, "title": a.title or slug, "created_at": now(),
        "source_mode": policy.get("default_source_mode", "public"),
        "allowed_domains": [],
        "note": "source_mode: public — любые публичные сайты, кроме запрещённых; strict — только allowed_domains",
    })
    stages = {c: {"status": "pending", "started_at": None, "done_at": None, "human": None} for c in STAGE_CODES}
    stages["brief"].update(status="in_progress", started_at=now())
    write_json(root / "state" / "task.json", {
        "project": slug, "title": a.title or slug, "stage": "brief", "stages": stages,
        "questions": [], "next_action": "Уточнить постановку задачи (навык strateg-brief)",
        "request": a.request or "", "created_at": now(), "updated_at": now(),
    })
    shutil.copy(TEMPLATES / "state" / "research_plan.md", root / "state" / "research_plan.md")
    shutil.copy(TEMPLATES / "outputs" / "01-brief.md", root / "outputs" / "01-brief.md")
    (PROJECTS / ".active").write_text(slug + "\n", encoding="utf-8")
    print(f"Создан проект «{slug}» и выбран активным: {rel(root)}")
    print("Дальше: заполнить outputs/01-brief.md вместе с человеком (навык strateg-brief).")


def cmd_use(a):
    if not (PROJECTS / a.slug / "project.json").exists():
        raise StrategError(f"Проект «{a.slug}» не найден")
    (PROJECTS / ".active").write_text(a.slug + "\n", encoding="utf-8")
    print(f"Активный проект: {a.slug}")
    cmd_status(a)


def cmd_projects(a):
    act = active_slug(required=False)
    found = False
    for d in sorted(PROJECTS.iterdir()) if PROJECTS.exists() else []:
        if (d / "project.json").exists():
            found = True
            t = read_json(d / "state" / "task.json", {})
            mark = "*" if d.name == act else " "
            print(f"{mark} {d.name:28} этап: {t.get('stage', '?'):9} {t.get('title', '')}")
    if not found:
        print("Проектов пока нет. Создайте: python tools/strateg.py new <slug> --title \"...\"")


def status_text(slug: str | None = None, brief: bool = False) -> str:
    """Текст «где мы и что дальше». Используется командой status, хуком начала сессии и MCP."""
    from . import decisions as dec_mod, journal as jr
    slug = active_slug(slug, required=False)
    if not slug:
        return ("СТРАТЕГ: активного проекта нет.\n"
                "Начать: python tools/strateg.py new <slug> --title \"название\" --request \"запрос руководителя\"\n"
                "Демо: python tools/strateg.py use demo-shield")
    p = P(slug)
    t = load_task(p)
    out = [f"СТРАТЕГ · проект «{t.get('title')}» ({slug})"]
    if t.get("request"):
        out.append(f"Запрос: {t['request']}")
    cur = t["stage"]
    for i, (code, name, gate, _f) in enumerate(STAGES, 1):
        st = t["stages"][code]
        mark = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]"}[st["status"]]
        tail = ""
        if st["status"] == "done" and st.get("human"):
            tail = f" — решение человека: {st['human']}"
        elif code == cur and gate:
            tail = " — в конце нужен выбор человека"
        out.append(f"  {mark} {i}. {name} ({code}){tail}")
    out.append(f"Текущий этап: {cur} → навык .claude/skills/{STAGE_SKILL[cur]}/SKILL.md")
    out.append(f"Следующее действие: {t.get('next_action') or '— не записано —'}")
    openq = [q for q in t.get("questions", []) if q["status"] == "open"]
    if openq:
        out.append("Открытые вопросы к человеку:")
        out += [f"  {q['id']}: {q['text']}" for q in openq]
    unfinished = jr.unfinished(p)
    if unfinished:
        out.append("НЕЗАВЕРШЁННЫЕ действия (начаты, итог не записан — проверьте результат, не повторяйте вслепую):")
        out += [f"  {j['id']} [{j.get('ts', '')[:16]}] {j['action']}" for j in unfinished]
    failed = [j for j in read_jsonl(p.journal) if j.get("status") == "failed"][-3:]
    if failed and not brief:
        out.append("Последние сбои инструментов:")
        out += [f"  {j['id']} {j['action']}: {j.get('error', '')[:120]}" for j in failed]
    flags = dec_mod.attention(p)
    open_before = [c for c in STAGE_CODES if t["stages"][c]["status"] != "done"]
    if open_before:
        first = STAGE_CODES.index(open_before[0])
        ahead = [c for c in STAGE_CODES[first + 1:] if t["stages"][c]["status"] == "done"]
        if ahead:
            flags = [f"этап {open_before[0]} не закрыт, а следующие отмечены закрытыми ({', '.join(ahead)}): "
                     f"их результат мог устареть — пройдите и подтвердите заново"] + list(flags)
    if flags:
        out.append("Требует внимания:")
        out += [f"  ! {x}" for x in flags]
    n_src = len(read_jsonl(p.sources_reg))
    ev = read_jsonl(p.evidence)
    n_act = sum(1 for e in ev if e.get("status") == "active")
    out.append(f"Материалы: {n_src} источников · сведения: {n_act} действующих из {len(ev)}")
    out.append(jr.cost_line(p))
    if p.handoff.exists() and not brief:
        note = p.handoff.read_text(encoding="utf-8").strip()
        if note:
            out.append("Записка с прошлого сеанса (state/handoff.md):")
            out += ["  " + ln for ln in note.splitlines()[-12:]]
    return "\n".join(out)


def cmd_status(a):
    print(status_text(getattr(a, "project", None)))


def _check_gate(p: P, code: str) -> list[str]:
    """Проверка готовности этапа. Возвращает список проблем (пусто — можно закрывать)."""
    from . import validate as v
    problems = []
    _c, _n, _g, fname = _stage(code)
    if fname:
        f = p.root / fname
        if not f.exists():
            problems.append(f"нет файла {fname}")
        elif "{{" in f.read_text(encoding="utf-8"):
            problems.append(f"в {fname} остались незаполненные поля {{{{...}}}}")
    if code == "collect" and not read_jsonl(p.sources_reg):
        problems.append("в реестре нет ни одного источника (команда ingest)")
    if code == "research":
        ev = [e for e in read_jsonl(p.evidence) if e.get("status") == "active"]
        if not ev:
            problems.append("в реестре сведений нет действующих записей (команда ev add)")
        plan = p.state / "research_plan.md"
        if not plan.exists() or "{{" in plan.read_text(encoding="utf-8"):
            problems.append("state/research_plan.md не заполнен")
    if code == "options":
        problems += [m for lvl, m in v.check_options(p) if lvl == "ОШИБКА"]
    if code in ("strategy", "review"):
        problems += [m for lvl, m in v.check_all(p) if lvl == "ОШИБКА"]
    return problems


def cmd_stage(a):
    p = P(a.project)
    t = load_task(p)
    code = a.code or t["stage"]
    _c, name, gate, fname = _stage(code)
    st = t["stages"][code]
    if a.action == "start":
        st.update(status="in_progress", started_at=st.get("started_at") or now(), done_at=None)
        t["stage"] = code
        if fname and fname != "outputs/report.md":
            dst = p.root / fname
            tpl = TEMPLATES / fname
            if not dst.exists() and tpl.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(tpl, dst)
                print(f"Создан шаблон {rel(dst)}")
        save_task(p, t)
        print(f"Этап «{name}» начат. Навык: .claude/skills/{STAGE_SKILL[code]}/SKILL.md")
    elif a.action == "done":
        problems = _check_gate(p, code)
        if problems:
            raise StrategError("Этап нельзя закрыть:\n  - " + "\n  - ".join(problems), 2)
        if gate and not a.human:
            raise StrategError(
                f"Этап «{name}» закрывается только после выбора человека: {HUMAN_GATE_TEXT[code]}.\n"
                f"Покажите человеку результат, получите ответ и повторите с --human \"что именно решил человек\".", 2)
        st.update(status="done", done_at=now(), human=a.human)
        idx = STAGE_CODES.index(code)
        if idx + 1 < len(STAGE_CODES):
            nxt = STAGE_CODES[idx + 1]
            t["stage"] = nxt
            t["stages"][nxt].update(status="in_progress", started_at=t["stages"][nxt].get("started_at") or now())
            t["next_action"] = f"Начать этап «{_stage(nxt)[1]}»: python tools/strateg.py stage start"
        save_task(p, t)
        from . import journal as jr
        jr.add(p, action=f"Этап «{name}» закрыт" + (f"; решение человека: {a.human}" if a.human else ""),
               tool="strateg stage", stage=code)
        print(f"Этап «{name}» закрыт. Следующий: {t['stage']}")
    elif a.action == "reopen":
        if not a.why:
            raise StrategError("Укажите причину: --why \"...\"")
        st.update(status="in_progress", done_at=None)
        t["stage"] = code
        # следующие закрытые этапы опирались на прежний результат: их нужно пройти и подтвердить заново
        reset = []
        for later in STAGE_CODES[STAGE_CODES.index(code) + 1:]:
            ls = t["stages"][later]
            if ls["status"] != "pending":
                ls.update(status="pending", prev_done_at=ls.get("done_at") or ls.get("prev_done_at"),
                          prev_human=ls.get("human") or ls.get("prev_human"), done_at=None, human=None,
                          reset_because=f"переоткрыт этап {code}: {a.why}")
                reset.append(later)
        t["next_action"] = f"Этап «{name}» переоткрыт: {a.why}"
        save_task(p, t)
        from . import journal as jr
        jr.add(p, action=f"Этап «{name}» переоткрыт: {a.why}" + (f"; сброшены этапы: {', '.join(reset)}" if reset else ""),
               tool="strateg stage", stage=code)
        print(f"Этап «{name}» переоткрыт." + (f" Следующие этапы нужно пройти заново: {', '.join(reset)}." if reset else ""))


def cmd_next(a):
    p = P(a.project)
    t = load_task(p)
    t["next_action"] = a.text
    save_task(p, t)
    print("Следующее действие записано.")


def cmd_ask(a):
    p = P(a.project)
    t = load_task(p)
    qid = f"H-{len(t['questions']) + 1:02d}"
    t["questions"].append({"id": qid, "text": a.text, "why": a.why or "", "status": "open",
                           "asked_at": now(), "answer": None, "stage": t["stage"]})
    save_task(p, t)
    print(f"Вопрос {qid} записан. Задайте его человеку и сохраните ответ: python tools/strateg.py answer {qid} \"...\"")


def cmd_answer(a):
    p = P(a.project)
    t = load_task(p)
    for q in t["questions"]:
        if q["id"] == a.id:
            q.update(status="answered", answer=a.text, answered_at=now())
            save_task(p, t)
            print(f"Ответ на {a.id} сохранён.")
            return
    raise StrategError(f"Вопрос {a.id} не найден")


def cmd_handoff(a):
    p = P(a.project)
    t = load_task(p)
    stamp = f"\n## {now()[:16]} · этап {t['stage']}\n{a.text.strip()}\n"
    with p.handoff.open("a", encoding="utf-8", newline="\n") as f:
        f.write(stamp)
    if a.next:
        t["next_action"] = a.next
    save_task(p, t)
    print(f"Записка сохранена в {rel(p.handoff)}. В новом чате начните со слова «Продолжи».")


def register(sub):
    s = sub.add_parser("new", help="создать проект и сделать его активным")
    s.add_argument("slug"); s.add_argument("--title"); s.add_argument("--request", help="исходный запрос руководителя")
    s.set_defaults(fn=cmd_new)
    s = sub.add_parser("use", help="переключить активный проект"); s.add_argument("slug"); s.set_defaults(fn=cmd_use, project=None)
    s = sub.add_parser("projects", help="список проектов"); s.set_defaults(fn=cmd_projects)
    s = sub.add_parser("status", help="где мы и что дальше (с этого начинается любой сеанс)"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("stage", help="начать / закрыть / переоткрыть этап")
    s.add_argument("action", choices=["start", "done", "reopen"]); s.add_argument("code", nargs="?")
    s.add_argument("--human", help="что решил человек (обязательно для этапов с выбором)"); s.add_argument("--why")
    s.set_defaults(fn=cmd_stage)
    s = sub.add_parser("next", help="записать следующее действие"); s.add_argument("text"); s.set_defaults(fn=cmd_next)
    s = sub.add_parser("ask", help="записать вопрос к человеку"); s.add_argument("text"); s.add_argument("--why"); s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("answer", help="сохранить ответ человека"); s.add_argument("id"); s.add_argument("text"); s.set_defaults(fn=cmd_answer)
    s = sub.add_parser("handoff", help="записка «где остановились» перед перерывом")
    s.add_argument("text"); s.add_argument("--next", help="обновить следующее действие"); s.set_defaults(fn=cmd_handoff)
