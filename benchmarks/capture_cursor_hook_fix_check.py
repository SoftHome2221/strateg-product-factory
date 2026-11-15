"""Verify corrected hooks against the observed Cursor run and saved artifacts."""
from pathlib import Path
from collections import Counter
import json
import os
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[1]
CASE=ROOT/'benchmarks/codex-2026-11-14/cursor-hook-fixes'
SETUP=json.loads((CASE/'setup.json').read_text(encoding='utf-8'))
FIXTURE=Path(SETUP['fixture'])
PROJECT=FIXTURE/'projects'/SETUP['project']


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def main():
    observation=json.loads((CASE/'ui-observations.json').read_text(encoding='utf-8'))
    events=rows(FIXTURE/'hook-events.jsonl')
    for event in events:
        if event.get('file_path'):
            try: event['file_path']=Path(event['file_path']).relative_to(FIXTURE).as_posix()
            except ValueError: event['file_path']='<outside fixture>'
    current=[e for e in events if e['session_id']==observation['session_id']]
    journal=rows(PROJECT/'state/journal.jsonl')
    evidence=rows(PROJECT/'evidence/evidence.jsonl')
    sources=rows(PROJECT/'sources/sources.jsonl')
    env=dict(os.environ,STRATEG_NO_DOTENV='1',STRATEG_PROJECT=SETUP['project'],STRATEG_ROUTER_CMD='',PYTHONIOENCODING='utf-8')
    cost=subprocess.run([sys.executable,'tools/strateg.py','cost'],cwd=FIXTURE,env=env,capture_output=True,text=True,encoding='utf-8')
    (CASE/'cost.txt').write_text(cost.stdout+cost.stderr,encoding='utf-8')
    keys=[j['key'] for j in journal if j.get('key')]
    probes={
      'status_and_fallback_context':observation['status_received'] and observation['observed_context_probe']==SETUP['post_context_probe']
          and not observation['probe_value_disclosed_in_prompt'] and any(e['event']=='postToolUse' and e['context_marker_emitted'] for e in current),
      'missing_read_auto_logged':any(j['tool']=='Read' and j['status']=='failed' and j.get('auto') for j in journal),
      'protected_write_denied_and_auto_logged':any(j['tool']=='Write' and j['status']=='failed' and j.get('auto') for j in journal)
          and (FIXTURE/'.cursor/protected-probe.txt').read_text(encoding='utf-8')=='BEFORE\n',
      'mcp_is_error_auto_logged_and_fact_absent':any(j['tool']=='MCP:strateg_evidence_add' and j.get('error')=='mcp_is_error' and j.get('auto') for j in journal) and not evidence,
      'audited_web_route_logged':bool(sources) and any(j['tool']=='strateg ingest' and j['status']=='done' and j.get('note')=='https://example.com' for j in journal)
    }
    checks={
      'fallback_emitted_once_after_status':sum(e['event']=='postToolUse' and e['context_marker_emitted'] for e in current)==1,
      'no_duplicate_journal_keys':len(keys)==len(set(keys)),
      'no_manual_log_tool_call':not any(e.get('tool')=='MCP:strateg_cli' for e in current),
      'probe_code_not_read':not any((e.get('file_path') or '').endswith(('hook_probe.py','setup.json')) for e in current),
      'unknown_money_not_zero':cost.returncode==0 and '| Модели (измерено) | нет данных о токенах и деньгах |' in cost.stdout,
      'unknown_human_time_not_zero':'| Время человека (ответы, правки) | не записано |' in cost.stdout
    }
    result={'date':'2026-11-15','client_version':observation['client_version'],'model_label':observation['model_label'],
      'selftest':SETUP['selftest'],'code_sha256':SETUP['code_sha256'],'probes':probes,
      'probes_passed':sum(probes.values()),'probes_total':len(probes),'checks':checks,
      'context_proof':{'expected':SETUP['post_context_probe'],'observed':observation['observed_context_probe'],
                       'value_not_in_prompt':True,'injected_only_after_tool':True},
      'hook_event_counts':dict(Counter(e['event'] for e in current)),
      'journal':journal,'sources':sources,'cost_output':cost.stdout,
      'official_contract':SETUP['official_contract'],
      'limitations':[
        'sessionStart remains asynchronous; fallback is delivered after the first tool result, not guaranteed before the first action.',
        'Native WebFetch may still omit events. The tested tracked route is strateg_ingest(URL), which records the source and journal server-side.',
        'Tokens and money unavailable from the client remain unknown; formatting does not reconstruct billing data.',
        'Probe wrapper adds only a nonce to the actual fallback context and records sanitized metadata; raw tool payloads and account data are not archived.'
      ]}
    (CASE/'hook-events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events),encoding='utf-8')
    shutil.copytree(PROJECT,CASE/'project',dirs_exist_ok=True)
    (CASE/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'probes':probes,'checks':checks,'passed':result['probes_passed'],'total':result['probes_total']},ensure_ascii=False))
    if not all(probes.values()) or not all(checks.values()): raise SystemExit(2)


if __name__=='__main__': main()
