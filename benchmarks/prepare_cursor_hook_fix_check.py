"""Prepare a small, non-secret fixture for the corrected Cursor hooks."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid

from prepare_cursor_full_cycle import PROBE

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path('C:/Users/Дарья/.codex/visualizations/2026/11/14/01a1d9fb-d86d-75a1-842d-4a5c4ae16130/cursor-hooks-fixed-check')
CASE = ROOT/'benchmarks/codex-2026-11-14/cursor-hook-fixes'


def main():
    if FIXTURE.exists():
        raise SystemExit('Fixture exists; inspect it instead of repeating setup.')
    CASE.mkdir(parents=True,exist_ok=True)
    for folder in ['tools','knowledge','templates','config','.claude/skills','.claude/agents','.cursor']:
        shutil.copytree(ROOT/folder,FIXTURE/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(ROOT/'AGENTS.md',FIXTURE/'AGENTS.md')
    marker = 'POST-' + uuid.uuid4().hex
    probe = PROBE.replace("'sessionStart'", "'postToolUse'").replace('HOOK_CONTEXT_TOKEN','POST_CONTEXT_PROBE').replace('CURSOR-HOOK-20261114',marker)
    probe = probe.replace("PYTHONIOENCODING='utf-8'", "PYTHONIOENCODING='utf-8', STRATEG_PROJECT='hook-fix-check'")
    (FIXTURE/'.cursor/hook_probe.py').write_text(probe,encoding='utf-8')
    (FIXTURE/'.cursor/protected-probe.txt').write_text('BEFORE\n',encoding='utf-8')
    hooks=json.loads((FIXTURE/'.cursor/hooks.json').read_text(encoding='utf-8'))
    for event,entries in hooks['hooks'].items():
        for entry in entries:
            entry['command']=f'python .cursor/hook_probe.py {event}'
    (FIXTURE/'.cursor/hooks.json').write_text(json.dumps(hooks,indent=2)+'\n',encoding='utf-8')
    mcp={'mcpServers':{'strateg':{'type':'stdio','command':sys.executable,
        'args':['${workspaceFolder}/tools/mcp_server.py'],
        'env':{'STRATEG_NO_DOTENV':'1','STRATEG_ROUTER_CMD':'','STRATEG_PROJECT':'hook-fix-check'}}}}
    (FIXTURE/'.cursor/mcp.json').write_text(json.dumps(mcp,indent=2)+'\n',encoding='utf-8')
    (FIXTURE/'inbox').mkdir()
    env=dict(os.environ,STRATEG_NO_DOTENV='1',STRATEG_ROUTER_CMD='',STRATEG_PROJECT='hook-fix-check',PYTHONIOENCODING='utf-8')
    subprocess.run([sys.executable,'tools/strateg.py','new','hook-fix-check','--title','Проверка исправленных хуков',
        '--request','Учебная проверка резервного контекста, журнала ошибок и учёта без токенов.'],
        cwd=FIXTURE,env=env,check=True,capture_output=True)
    meta={'fixture':str(FIXTURE),'project':'hook-fix-check','post_context_probe':marker,
          'instrumentation':'Forwarded hook responses; nonce added only to postToolUse additional_context. Raw payloads/account details never saved.',
          'selftest':{'exit_code':0,'passed':87,'total':87,'observed_output':'Итог: 87 из 87 проверок пройдено. Инструменты работают.'},
          'official_contract':'https://cursor.com/docs/hooks',
          'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
              ['tools/strateglib/hooks.py','tools/strateglib/journal.py','tools/mcp_server.py','tests/selftest.py']}}
    (CASE/'setup.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(str(FIXTURE))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
