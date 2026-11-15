"""Verify and archive the finished synthetic workflow without altering registries."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT/'benchmarks/codex-2026-11-14/workflow-check'
META = json.loads((CASE/'provenance.json').read_text(encoding='utf-8'))
WORK = Path(META['continuation_fixture'])
ORIGINAL = Path(META['original_fixture'])
PROJECT = WORK/'projects'/META['project']


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def main():
    task = json.loads((PROJECT/'state/task.json').read_text(encoding='utf-8'))
    scenario = json.loads((WORK/'scenario.json').read_text(encoding='utf-8'))
    evidence = rows(PROJECT/'evidence/evidence.jsonl')
    original_runs = rows(ORIGINAL/'projects'/META['project']/'analysis/runs.jsonl')
    current_runs = rows(PROJECT/'analysis/runs.jsonl')
    decisions = rows(PROJECT/'decisions/decisions.jsonl')
    commands = rows(CASE/'commands.jsonl')
    budget_runs = [r for r in current_runs if r.get('result',{}).get('metric')=='hours' and r.get('result',{}).get('agg')=='sum']
    validation = subprocess.run([sys.executable,'tools/strateg.py','--project',META['project'],'validate'],
        cwd=WORK,env=dict(os.environ,STRATEG_NO_DOTENV='1',STRATEG_ROUTER_CMD='',PYTHONIOENCODING='utf-8'),
        capture_output=True,text=True,encoding='utf-8')
    (CASE/'validation.txt').write_text(validation.stdout+validation.stderr,encoding='utf-8')
    checks = {
      'all_seven_stages_done':all(s['status']=='done' for s in task['stages'].values()),
      'all_gate_values_are_exact_test_fixtures':all(task['stages'][k]['human']==scenario[k+'_gate'] for k in ['brief','research','options','review','support']),
      'formal_validation_passed':validation.returncode==0,
      'original_cursor_state_unchanged':hashlib.sha256((ORIGINAL/'projects'/META['project']/'state/task.json').read_bytes()).hexdigest()==META['copied_task_sha256'],
      'original_calculations_preserved':current_runs[:len(original_runs)]==original_runs,
      'all_evidence_explicitly_synthetic':all('СИНТЕТИКА' in e.get('claim','') for e in evidence),
      'one_project_report':(PROJECT/'outputs/report.md').is_file(),
      'two_independent_critiques_archived':all((CASE/n).is_file() for n in ['critic-options.md','critic-review.md']),
      'decision_recorded':bool(decisions),
      'four_test_commitments_recorded':len(decisions)==1 and len(decisions[0].get('commitments',[]))==4 and all(c['owner']==scenario['owner'] and c['due']==scenario['check_date'] and c['status']=='open' for c in decisions[0]['commitments']),
      'due_alerts_exercised':any(r['args']==['dec','due'] and r['returncode']==0 and 'скоро срок обязательства' in r['stdout'] for r in commands),
      'assumed_preparation_budget_checked':bool(budget_runs) and all(g['value']<=8 for g in budget_runs[-1]['result']['groups'])
    }
    shutil.copytree(PROJECT,CASE/'project',dirs_exist_ok=True)
    result = {'date':'2026-11-15','scope':'Synthetic seven-stage workflow mechanics; no real market study or human approvals',
      'provenance':META,'checks':checks,'passed':sum(checks.values()),'total':len(checks),
      'stages':task['stages'],'validation_output':validation.stdout+validation.stderr,
      'source_count':len(rows(PROJECT/'sources/sources.jsonl')),'evidence_count':len(evidence),
      'conclusion_count':len(rows(PROJECT/'evidence/conclusions.jsonl')),
      'decisions':decisions,'analysis_runs':current_runs,
      'critiques':{'options':{'task':'workflow_options_critic','separate_context':True,'finding_count':6},
                  'review':{'task':'workflow_report_critic','separate_context':True,'finding_count':5},
                  'artifacts':'Summaries of findings, not full transcripts; author recorded dispositions in outputs.'},
      'limitations':[
        'Stages brief and collect and initial evidence came from the Cursor run; stages research through support were completed in Codex after user instruction.',
        'This confirms workflow completion and artifact consistency, not a full seven-stage Cursor UI run.',
        'TEST_SCENARIO values exercise gates, not real human approvals; roles and dates are scenario fixtures.',
        'Independent AI critics are not human blind evaluators. Synthetic evidence cannot prove market demand or overall recommendation superiority.',
        'Tokens, monetary cost and human time of the continuation were not measured; inherited Cursor time-only zero-dollar records do not mean the work was free.',
        'Known Cursor start-context and automatic-journal limitations remain as recorded in the separate hook trace.'
      ]}
    (CASE/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'checks':checks,'passed':result['passed'],'total':result['total']},ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit(2)


if __name__=='__main__':
    main()
