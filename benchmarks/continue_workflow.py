"""Continue the isolated QA workflow, preserving the original Cursor snapshot."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[1]
BASE = Path('C:/Users/Дарья/.codex/visualizations/2026/11/14/01a1d9fb-d86d-75a1-842d-4a5c4ae16130')
SRC = BASE/'cursor-full-check'
DEST = BASE/'workflow-check'
SLUG = 'cursor-seven-stage'
CASE = ROOT/'benchmarks/codex-2026-11-14/workflow-check'
ENV = dict(os.environ, STRATEG_NO_DOTENV='1', STRATEG_ROUTER_CMD='', PYTHONIOENCODING='utf-8')


def cli(*args):
    result = subprocess.run([sys.executable,'tools/strateg.py','--project',SLUG,*args],
        cwd=DEST,env=ENV,capture_output=True,text=True,encoding='utf-8')
    with (CASE/'commands.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'args':list(args),'returncode':result.returncode,
                           'stdout':result.stdout,'stderr':result.stderr},ensure_ascii=False)+'\n')
    print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, file=sys.stderr, end='')
    if result.returncode:
        raise SystemExit(result.returncode)


def main():
    CASE.mkdir(parents=True,exist_ok=True)
    if sys.argv[1:] == ['init']:
        if DEST.exists():
            raise SystemExit('Continuation already exists; inspect status before repeating.')
        for folder in ['tools','knowledge','templates','config']:
            shutil.copytree(SRC/folder,DEST/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        shutil.copytree(SRC/'projects'/SLUG,DEST/'projects'/SLUG)
        for name in ['AGENTS.md','scenario.json']:
            shutil.copy2(SRC/name,DEST/name)
        (CASE/'provenance.json').write_text(json.dumps({
            'original_fixture':str(SRC),'continuation_fixture':str(DEST),
            'project':SLUG,'resumed_in':'Codex','original_environment':'Cursor',
            'entry_stage':'research','completed_before_continuation':['brief','collect'],
            'synthetic':True,'human_gates':'TEST_SCENARIO fixtures, not real human approvals',
            'copied_task_sha256':hashlib.sha256((SRC/'projects'/SLUG/'state/task.json').read_bytes()).hexdigest()
        },ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        cli('status')
    else:
        cli(*sys.argv[1:])


if __name__=='__main__':
    main()
