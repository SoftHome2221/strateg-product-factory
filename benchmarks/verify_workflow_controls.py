"""Check concrete workflow mechanisms without changing live product decisions.

This is a functional control test, not a new paired model-quality comparison.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'benchmarks/codex-2026-11-14'
WORK = Path('C:/Users/Дарья/.codex/visualizations/2026/11/14/01a1d9fb-d86d-75a1-842d-4a5c4ae16130/workflow-controls')
ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1', STRATEG_TODAY='2026-11-14')


def records(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]


def run(args, expected=0):
    result = subprocess.run([sys.executable, 'tools/strateg.py', '--project', 'family-cloud', *args], cwd=WORK,
                            env=ENV, capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == expected, result.stdout + result.stderr
    return {'args': args, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}


def main():
    if (OUT / 'workflow-controls.json').exists():
        raise SystemExit('Controls already measured; inspect before repeating.')
    for name in ['tools', 'templates', 'config', 'knowledge']:
        shutil.copytree(ROOT / name, WORK / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    project = WORK / 'projects/family-cloud'
    shutil.copytree(ROOT / 'projects/family-cloud', project)
    trace = {}
    before = records(project / 'evidence/conclusions.jsonl')
    assert next(c for c in before if c['id'] == 'C-001')['status'] == 'active'
    trace['impact_before'] = run(['impact', 'E-008'])
    trace['retract_simulated'] = run(['ev', 'retract', 'E-008', '--why', 'СИМУЛЯЦИЯ benchmark: проверка отзыва исторического сведения только в тестовой копии'])
    ev = next(e for e in records(project / 'evidence/evidence.jsonl') if e['id'] == 'E-008')
    conclusion = next(c for c in records(project / 'evidence/conclusions.jsonl') if c['id'] == 'C-001')
    assert ev['status'] == 'retracted'
    assert conclusion['status'] == 'needs_review'
    flagged_decisions = [d['id'] for d in records(project / 'decisions/decisions.jsonl') if d.get('review_flags')]
    assert flagged_decisions, 'Expected the historically dependent decision to be flagged'
    trace['validation_rejects_old_reference'] = run(['validate'], expected=2)
    assert 'недействительное сведение E-008' in trace['validation_rejects_old_reference']['stdout']
    trace['fresh_process_status'] = run(['status'])
    assert 'C-001' in trace['fresh_process_status']['stdout'] and 'пересмотр' in trace['fresh_process_status']['stdout']
    trace['recompute'] = run(['data', 'compare', '--a', '200/10000', '--b', '300/10000'])
    original_result = records(OUT / 'agent-calculations/runs.jsonl')[-1]['result']
    recomputed_result = records(project / 'analysis/runs.jsonl')[-1]['result']
    assert original_result == recomputed_result
    results = {
        'simulated': True, 'live_project_changed': False,
        'scope': 'Functional tests of workflow mechanisms, not a paired quality estimate or a business outcome',
        'checks': {
            'evidence_retraction_persisted': ev['status'] == 'retracted',
            'dependent_conclusion_flagged': conclusion['status'] == 'needs_review',
            'dependent_decision_flagged': bool(flagged_decisions),
            'validator_rejects_old_reference': True,
            'fresh_process_sees_review_need': True,
            'agent_calculation_reproduces_exactly': original_result == recomputed_result,
        },
        'affected_decisions': flagged_decisions,
        'matched_calculation_result': recomputed_result,
        'trace': trace,
        'limitation': 'No plain-chat response to a source-change scenario was generated. These controls demonstrate mechanisms, not general superiority.',
    }
    (OUT / 'workflow-controls.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(results['checks'], ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
