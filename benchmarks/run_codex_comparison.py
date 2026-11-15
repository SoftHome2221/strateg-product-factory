"""Paired Codex strategy-writing benchmark. No keys or user config are read.

prepare creates isolated inputs outside the repository; run captures CLI JSON events.
Existing project records are copied byte-for-byte, never edited directly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'benchmarks' / 'codex-2026-11-14'
WORK = Path('C:/Users/Дарья/.codex/visualizations/2026/11/14/01a1d9fb-d86d-75a1-842d-4a5c4ae16130/codex-comparison')
MODEL = 'gpt-6.1-sol'
ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1', STRATEG_TODAY='2026-11-14')
PROMPT = '''Я руководитель продукта в МегаФоне. До 30 ноября 2026 года нужна продуктовая и коммуникационная стратегия семейной подписки на облачное хранилище, рынок — Россия. Внутренних данных нет.
Исследование уже принято, руководитель выбрал вариант D: партнёрское облако для организаторов МегаСемей; собственную семейную надстройку рассматриваем позже при подтверждённом спросе. Обоснование, альтернативы и материалы лежат в input/. Это исторический выбор для задания, а не просьба заново выбрать направление.
Подготовь на этих материалах согласованную продуктовую и коммуникационную стратегию для выбранного D с рекомендацией руководителю и планом проверки. Покажи основания, ограничения и условия пересмотра. Читать буду с телефона, 5–10 минут. Полный итоговый текст — до 2500 слов. Если нужны дополнительные открытые источники, доступен веб-поиск; даты старых материалов не выдавай за текущие условия.
Не запускай продукт или эксперимент и не записывай за человека новых решений, ответственных или одобрений. Работа ограничена подготовкой стратегии; независимая оценка и принятие результата будут отдельно. Не создавай второй итоговый отчёт проекта.
Работай только внутри текущего рабочего каталога и с публичным вебом; не читай родительские, соседние каталоги, настройки пользователя или секреты. Не обращайся к исходному репозиторию за пределами рабочей копии. В финальном ответе приведи полный текст стратегии, а не только ссылку на файл.'''


def dump(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def command(args, cwd):
    r = subprocess.run([sys.executable, 'tools/strateg.py', '--project', 'family-cloud', *args], cwd=cwd, env=ENV,
                       capture_output=True, text=True, encoding='utf-8')
    if r.returncode:
        raise RuntimeError(r.stdout + r.stderr)
    return r.stdout


def prepare():
    if (OUT / 'protocol.json').exists():
        raise SystemExit('Protocol already exists; inspect it before re-running preparation.')
    OUT.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'projects/family-cloud'
    frozen = ROOT / 'benchmarks/codex-2026-11-14/frozen-input'
    hashes = {}
    for arm in ['chat', 'agent']:
        base = WORK / arm
        inp = base / 'input'
        inp.mkdir(parents=True, exist_ok=True)
        if frozen.exists():
            shutil.copytree(frozen, inp, dirs_exist_ok=True)
        else:
            for name in ['01-brief.md', '02-situation.md', '03-options.md']:
                shutil.copy2(source / 'outputs' / name, inp / name)
            for name in ['evidence.jsonl', 'conclusions.jsonl']:
                shutil.copy2(source / 'evidence' / name, inp / name)
            shutil.copy2(source / 'sources/sources.jsonl', inp / 'sources.jsonl')
            shutil.copytree(source / 'sources/text', inp / 'source-text', dirs_exist_ok=True)
        hashes[arm] = {str(p.relative_to(inp)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(inp.rglob('*')) if p.is_file()}
        if arm == 'agent':
            for name in ['tools', 'knowledge', 'templates', 'config']:
                shutil.copytree(ROOT / name, base / name, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ['.agents/skills', '.claude/skills', '.claude/agents']:
                shutil.copytree(ROOT / name, base / name, dirs_exist_ok=True)
            shutil.copy2(ROOT / 'AGENTS.md', base / 'AGENTS.md')
            project = base / 'projects/family-cloud'
            project.mkdir(parents=True, exist_ok=True)
            for name in ['project.json', 'state/task.json', 'state/research_plan.md']:
                (project / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, project / name)
            shutil.copytree(inp / 'source-text', project / 'sources/text', dirs_exist_ok=True)
            shutil.copy2(inp / 'sources.jsonl', project / 'sources/sources.jsonl')
            (project / 'evidence').mkdir(exist_ok=True)
            for name in ['evidence.jsonl', 'conclusions.jsonl']:
                shutil.copy2(inp / name, project / 'evidence' / name)
            (project / 'outputs').mkdir(exist_ok=True)
            for name in ['01-brief.md', '02-situation.md', '03-options.md']:
                shutil.copy2(inp / name, project / 'outputs' / name)
            command(['stage', 'reopen', 'strategy', '--why',
                     'Изолированный benchmark: заново подготовить стратегию на одинаковом пакете материалов и историческом выборе D; не менять живой проект'], base)
            command(['use', 'family-cloud'], base)
    assert hashes['chat'] == hashes['agent']
    (OUT / 'prompt.txt').write_text(PROMPT, encoding='utf-8')
    dump(OUT / 'protocol.json', {
        'date': '2026-11-14', 'model': MODEL, 'reasoning_effort': 'medium', 'cli': '0.167.0-alpha.4.1',
        'task': 'family-cloud: strategy for historically approved D, existing research supplied equally',
        'scope_limit': 'strategy authoring only; not a fresh full seven-stage run or independent research comparison',
        'order': ['chat', 'agent'], 'replicates': 1, 'web_search': 'live', 'shared_input_sha256': hashes['chat'],
        'delivery': 'Identical complete inputs also appended to prompt',
        'approval_mode': 'approve-for-me, both arms',
        'chat': {'cwd': str(WORK / 'chat'), 'project_doc_max_bytes': 0, 'sandbox': 'workspace-write',
                 'repo_workflow': False},
        'agent': {'cwd': str(WORK / 'agent'), 'project_doc_max_bytes': 65536, 'sandbox': 'workspace-write',
                  'repo_workflow': True},
        'limitations': ['One task, one run per arm', 'Same source corpus was collected in an earlier Claude session',
                        'Both runs use Codex CLI system scaffolding; chat is a proxy, not the ChatGPT UI',
                        'Path restrictions partly rely on prompt and event audit, not a hermetic filesystem',
                        'Agent may read method files and use project tools; this is the intended treatment',
                        'Timing excludes shared material preparation; human time and dollars not inferred'],
    })
    print('Prepared equal input hashes; separate workspaces; original project strategy withheld.', flush=True)


def run(arm):
    if (OUT / f'{arm}-metrics.json').exists() or (OUT / f'{arm}-events.jsonl').exists():
        raise SystemExit('Existing run artifacts found; do not repeat blindly.')
    base = WORK / arm
    args = [shutil.which('codex'), 'exec', '--ephemeral', '--ignore-user-config', '--skip-git-repo-check',
            '--approve-for-me', '--json', '--color', 'never',
            '--model', MODEL, '-c', 'model_reasoning_effort="medium"', '-c', 'web_search="live"',
            '-c', f'project_doc_max_bytes={0 if arm == "chat" else 65536}',
            '--output-last-message', str(OUT / f'{arm}-response.md'), '-']
    started = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    with (OUT / f'{arm}-events.jsonl').open('wb') as stdout, (OUT / f'{arm}-stderr.txt').open('wb') as stderr:
        proc = subprocess.Popen(args, cwd=base, env=ENV, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
        dump(OUT / f'{arm}-running.json', {'pid': proc.pid, 'started_at_utc': started, 'command': args})
        print(f'{arm}: started pid={proc.pid}', flush=True)
        try:
            supplied = '\n\n'.join(f'<material path="{p.relative_to(base / "input").as_posix()}">\n'
                                      + p.read_text(encoding='utf-8') + '\n</material>'
                                      for p in sorted((base / 'input').rglob('*')) if p.is_file())
            full_prompt = PROMPT + '\n\nВсе материалы input/ также приложены ниже целиком; чтение файлов для доступа к данным не требуется.\n\n' + supplied
            (OUT / f'{arm}-submitted-prompt.txt').write_text(full_prompt, encoding='utf-8')
            proc.communicate(full_prompt.encode('utf-8'), timeout=1200)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError(f'{arm} timed out; artifacts retained, no automatic repeat')
    metrics = {'exit_code': proc.returncode, 'seconds': round(time.monotonic() - t0, 2),
               'started_at_utc': started, 'model_requested': MODEL, 'usage': [], 'tool_counts': {}}
    for line in (OUT / f'{arm}-events.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('type') == 'turn.completed':
            metrics['usage'].append(event.get('usage'))
        if event.get('type') == 'item.completed':
            typ = event.get('item', {}).get('type', '')
            metrics['tool_counts'][typ] = metrics['tool_counts'].get(typ, 0) + 1
    strategy = base / 'projects/family-cloud/outputs/04-strategy.md'
    if arm == 'agent' and strategy.exists():
        shutil.copy2(strategy, OUT / 'agent-strategy.md')
        generated = OUT / 'agent-calculations'
        generated.mkdir(exist_ok=True)
        for artifact in (base / 'projects/family-cloud/analysis').glob('*'):
            if artifact.is_file():
                shutil.copy2(artifact, generated / artifact.name)
        (OUT / 'agent-validation.txt').write_text(command(['validate', 'strategy'], base), encoding='utf-8')
        shutil.copy2(base / 'projects/family-cloud/state/journal.jsonl', OUT / 'agent-workflow-journal.jsonl')
    dump(OUT / f'{arm}-metrics.json', metrics)
    print(json.dumps(metrics, ensure_ascii=False), flush=True)
    if proc.returncode:
        raise SystemExit(proc.returncode)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'chat', 'agent'])
    parser.add_argument('--output-dir', type=Path, help='Separate artifact directory for an explicitly requested repeat')
    parser.add_argument('--work-dir', type=Path, help='Separate workspace outside the repository for a repeat')
    args = parser.parse_args()
    if args.output_dir:
        OUT = args.output_dir.resolve()
    if args.work_dir:
        WORK = args.work_dir.resolve()
    action = args.action
    prepare() if action == 'prepare' else run(action)
