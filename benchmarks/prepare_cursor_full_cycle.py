"""Prepare an isolated Cursor QA fixture, with synthetic inputs and hook telemetry.

Only test data is created. No production project or user secret is copied.
Scenario gate strings are explicitly mock inputs, never real product approvals.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'benchmarks/codex-2026-11-14/cursor-full-cycle'
FIXTURE = Path('C:/Users/Дарья/.codex/visualizations/2026/11/14/01a1d9fb-d86d-75a1-842d-4a5c4ae16130/cursor-full-check')

PROBE = r'''from pathlib import Path
import datetime, json, os, subprocess, sys
root = Path(__file__).resolve().parents[1]
event = sys.argv[1]
raw = sys.stdin.buffer.read()
try: payload = json.loads(raw.decode('utf-8-sig'))
except Exception: payload = {}
result = subprocess.run([sys.executable, str(root/'tools/strateg.py'), 'hook', 'cursor', event],
                        input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root,
                        env=dict(os.environ, STRATEG_NO_DOTENV='1', PYTHONIOENCODING='utf-8'))
try: response = json.loads(result.stdout.decode('utf-8-sig'))
except Exception: response = {}
if event == 'sessionStart' and isinstance(response.get('additional_context'), str):
    response['additional_context'] += '\nHOOK_CONTEXT_TOKEN=CURSOR-HOOK-20261114\n'
    result.stdout = json.dumps(response, ensure_ascii=False).encode('utf-8')
inp = payload.get('tool_input') or {}
if isinstance(inp, str):
    try: inp=json.loads(inp)
    except Exception: inp={}
entry = {'at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'event':event,
         'reported_event':payload.get('hook_event_name'), 'tool':payload.get('tool_name'),
         'input_keys':sorted(inp) if isinstance(inp,dict) else [],
         'file_path':payload.get('file_path') or (inp.get('path') or inp.get('file_path') if isinstance(inp,dict) else None),
         'session_id':payload.get('conversation_id') or payload.get('session_id'),
         'returncode':result.returncode, 'response_keys':sorted(response),
         'permission':response.get('permission'), 'message':response.get('user_message'),
         'context_present':bool(response.get('additional_context')),
         'context_marker_emitted':event=='sessionStart' and bool(response.get('additional_context')),
         'error_present':bool(payload.get('error_message') or result.stderr)}
# Never persist raw payloads: they can include user_email or file contents.
with (root/'hook-events.jsonl').open('a',encoding='utf-8') as f:
    f.write(json.dumps(entry,ensure_ascii=False)+'\n')
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
'''


def main():
    if (FIXTURE/'projects').exists():
        raise SystemExit('Fixture exists. Inspect status and files before repeating.')
    CASE.mkdir(parents=True, exist_ok=True)
    for folder in ['tools','knowledge','templates','config','.agents/skills','.claude/skills','.claude/agents','.cursor']:
        shutil.copytree(ROOT/folder,FIXTURE/folder,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['AGENTS.md','CLAUDE.md']:
        shutil.copy2(ROOT/name,FIXTURE/name)
    (FIXTURE/'.cursor/hook_probe.py').write_text(PROBE,encoding='utf-8')
    (FIXTURE/'.cursor/protected-probe.txt').write_text('SYNTHETIC_PROTECTED_MARKER_BEFORE\n',encoding='utf-8')
    hooks=json.loads((FIXTURE/'.cursor/hooks.json').read_text(encoding='utf-8'))
    for event,rows in hooks['hooks'].items():
        for row in rows:
            row['command']=f'python .cursor/hook_probe.py {event}'
    (FIXTURE/'.cursor/hooks.json').write_text(json.dumps(hooks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    mcp={'mcpServers':{'strateg':{'type':'stdio','command':sys.executable,
          'args':['${workspaceFolder}/tools/mcp_server.py'],
          'env':{'STRATEG_NO_DOTENV':'1','STRATEG_ROUTER_CMD':''}}}}
    (FIXTURE/'.cursor/mcp.json').write_text(json.dumps(mcp,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    inbox=FIXTURE/'inbox'
    inbox.mkdir()
    (FIXTURE/'hook-probes').mkdir()
    (inbox/'product.md').write_text('''# УЧЕБНЫЙ ПРОДУКТ. Все данные вымышлены
Название: «Семейный архив — QA». Это тест инструментов, не реальный бизнес и не исследование рынка.
Решение к 30.11.2026: какой один сегмент выбрать для ограниченной проверки семейного режима.
Критерий: обоснованная рекомендация и выполнимый план проверки; рост продаж не считается доказанным.
Есть в учебном продукте: ручная загрузка файлов; общий семейный альбом; приглашение второго участника;
личный раздел с отдельным доступом; месячная подписка и экран отмены.
Нет: автозагрузка всего телефона, гарантированное освобождение памяти, печать фотокниг, безлимит.
В плане (январь 2027, учебное допущение): перенос файлов из другого облака.
Предполагаемые сегменты: организаторы уже созданных семейных групп и родители маленьких детей.
Свой канал контакта есть у организаторов; это свойство учебного сценария, не факт о МегаФоне.
Неизвестны удержание после первого платежа, реальные затраты поддержки, размер рынка и причины отказов.
Не требуется покупать, публиковать или запускать эксперимент. Ответственные — только роли тестового сценария.
''',encoding='utf-8')
    (inbox/'research.md').write_text('''# СИНТЕТИЧЕСКИЙ МАТЕРИАЛ ДЛЯ QA
Все следующие сведения сгенерированы; они не подтверждают спрос реальных людей.
Две группы учебных контактов в октябре 2026: организаторы семейных групп и родители маленьких детей.
Показатель в contacts.csv: converted=1 — условная первая оплата, converted=0 — её отсутствие.
Единица — один учебный контакт, период — 01–31.10.2026; пропуски не закладывались.
Группы не рандомизированы; нельзя приписывать разницу только свойствам аудитории.
Бесплатные альтернативы: папка на компьютере, мессенджер, личное облако. Это варианты сценария, не измеренные доли.
Качественная гипотеза: организатору проще пригласить близкого, но причины покупки неизвестны.
Реальных интервью нет; синтетический материал не доказывает готовность платить.
''',encoding='utf-8')
    rows=['unit,segment,converted']
    for segment,paid in [('organizers',30),('parents',20)]:
        rows.extend(f'test_{segment}_{i:04d},{segment},{int(i<=paid)}' for i in range(1,1001))
    (inbox/'contacts.csv').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    scenario={'type':'SYNTHETIC_QA_SCENARIO_NOT_REAL_HUMAN_DECISIONS',
      'request':'Начни учебную проверку: кому рекомендовать семейный режим «Семейный архив — QA»?',
      'brief_gate':'TEST_SCENARIO: fixture brief accepted; not a real human product approval',
      'research_gate':'TEST_SCENARIO: supplied synthetic inputs sufficient for QA; not evidence about market demand',
      'options_gate':'TEST_SCENARIO: choose B, limited check for organizers; no real launch approval',
      'review_gate':'TEST_SCENARIO: accept QA report only after formal validation and independent critique; not a real human approval',
      'support_gate':'TEST_SCENARIO: record test decision and commitment; test role only, no real launch',
      'selected_option':'B: подготовить ограниченную проверку организаторов, только после проверки условий',
      'owner':'TEST_ROLE: руководитель учебного продукта','check_date':'2026-11-21'}
    (FIXTURE/'scenario.json').write_text(json.dumps(scenario,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    env=dict(os.environ,STRATEG_NO_DOTENV='1',PYTHONIOENCODING='utf-8')
    subprocess.run([sys.executable,'tools/strateg.py','new','cursor-seven-stage','--title','Семейный архив — QA, тест Cursor',
                    '--request',scenario['request']],cwd=FIXTURE,env=env,check=True,capture_output=True)
    manifest={'fixture':str(FIXTURE),'project':'cursor-seven-stage','synthetic':True,
      'human_gates':'Explicit scenario fixtures, not human decisions; separate from all live projects',
      'hook_probe':'Logs only sanitized event metadata and original response keys/decision; passes JSON to unchanged CLI',
      'session_marker':'CURSOR-HOOK-20261114',
      'hook_source_sha256':hashlib.sha256((FIXTURE/'tools/strateglib/hooks.py').read_bytes()).hexdigest(),
      'protected_probe_sha256':hashlib.sha256((FIXTURE/'.cursor/protected-probe.txt').read_bytes()).hexdigest(),
      'no_secret_file_created':not (FIXTURE/'hook-probes/.env').exists(),
      'files':{str(p.relative_to(FIXTURE)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [*inbox.glob('*'),FIXTURE/'scenario.json']}}
    (CASE/'fixture-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(str(FIXTURE))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
