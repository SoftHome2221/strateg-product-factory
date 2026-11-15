"""Apply the repository's unchanged grounding metric equally to both Codex answers."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from strateglib.validate import grounding, REQUIRED_STRATEGY, REQUIRED_TEST_PLAN

OUT = Path(__file__).with_name('codex-2026-11-14')


def evaluate():
    results = {}
    for arm in ['chat', 'agent']:
        # Primary endpoint is the complete final answer, for both arms.
        path = OUT / f'{arm}-response.md'
        text = path.read_text(encoding='utf-8')
        stats = grounding(text, count_urls=True)
        headings = '\n'.join(line.lower() for line in text.splitlines() if line.startswith('#'))
        commands, tools, failures = [], [], []
        for line in (OUT / f'{arm}-events.jsonl').read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get('item', {})
            if event.get('type') != 'item.completed':
                continue
            if item.get('type') == 'command_execution':
                commands.append({'command': item.get('command'), 'exit_code': item.get('exit_code')})
            if item.get('type') == 'mcp_tool_call':
                tools.append({'server': item.get('server'), 'tool': item.get('tool'), 'error': item.get('error')})
            if item.get('status') == 'failed':
                failures.append(item.get('type'))
        stats.update({
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'words': len(re.findall(r'\S+', text)),
            'characters': len(text),
            # Sensitivity: ordinary prose may use E-002 instead of [E-002].
            # Keep the original response untouched and show this metric separately.
            'bare_reference_sensitivity': grounding(re.sub(r'\b([EC]-\d{3})\b', r'[\1]', text), count_urls=True),
            'required_heading_patterns_present': {name: bool(re.search(pat, headings)) for pat, name in REQUIRED_STRATEGY},
            'test_plan_terms_present_anywhere': {name: bool(re.search(pat, text, re.I)) for pat, name in REQUIRED_TEST_PLAN},
            'execution': json.loads((OUT / f'{arm}-metrics.json').read_text(encoding='utf-8')),
            'commands': commands, 'mcp_calls': tools, 'failed_items': failures,
            'validator_stdout': subprocess.run([sys.executable, str(ROOT / 'tools/strateg.py'), '--project', 'family-cloud',
                                                 'validate', '--file', str(path)], capture_output=True,
                                                text=True, encoding='utf-8', errors='replace',
                                                env=dict(os.environ, PYTHONIOENCODING='utf-8')).stdout,
        })
        if arm == 'agent' and (OUT / 'agent-strategy.md').exists():
            stored = (OUT / 'agent-strategy.md').read_text(encoding='utf-8')
            stats['stored_strategy_grounding'] = grounding(stored, count_urls=True)
            stats['stored_strategy_matches_final_exactly'] = stored.strip() == text.strip()
        results[arm] = stats
    results['notes'] = [
        'Primary endpoint: full last message, unchanged, for both arms.',
        'grounding counts URLs and E/C refs equally; it detects formatting, not truth.',
        'Heading/term matching is diagnostic, not a human quality score.',
        'Input and cached tokens overlap; cached input is a subset, not an extra charge.',
        'Dollars and human time are unknown; no inferred cost is added to the project.',
    ]
    checks = json.loads((OUT / 'source-checks.json').read_text(encoding='utf-8'))
    for arm in ['chat', 'agent']:
        results[arm]['source_check_counts'] = {verdict: sum(c['verdict'] == verdict for c in checks[arm])
                                               for verdict in ['confirmed', 'partial', 'unsupported', 'contradicted']}
        seconds = round(results[arm]['execution']['seconds'])
        results[arm]['elapsed_mm_ss'] = f'{seconds // 60}:{seconds % 60:02d}'
    chat_prompt = (OUT / 'chat-submitted-prompt.txt').read_bytes()
    agent_prompt = (OUT / 'agent-submitted-prompt.txt').read_bytes()
    results['input_audit'] = {'identical_submitted_prompts': chat_prompt == agent_prompt,
                             'prompt_sha256': hashlib.sha256(chat_prompt).hexdigest()}
    results['independent_ai_review'] = checks['independent_ai_review']
    (OUT / 'evaluation.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for arm in ['chat', 'agent']:
        row = results[arm]
        print(json.dumps({k: row[k] for k in ['words', 'lines', 'with_ref', 'share_ref', 'share_grounded', 'numeric_bare', 'execution']}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    evaluate()
