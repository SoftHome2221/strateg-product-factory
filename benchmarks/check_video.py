"""Record a dedicated test window and exercise the existing video ingestion boundary.

No desktop-wide capture, microphone, personal data, speech recognition, or API key.
The VTT is an exact export of text shown on screen, not a speech transcript.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'benchmarks/codex-2026-11-14/video'
WORK = Path('C:/Users/Дарья/.codex/visualizations/2026/11/14/01a1d9fb-d86d-75a1-842d-4a5c4ae16130/video-check')
FIXTURE = WORK / 'fixture'
MEDIA = WORK / 'media'
ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')


def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def cli(args, expected=0):
    r = subprocess.run([sys.executable, 'tools/strateg.py', *args], cwd=FIXTURE, env=ENV,
                       capture_output=True, text=True, encoding='utf-8')
    if r.returncode != expected:
        raise RuntimeError(f'Unexpected exit {r.returncode}, expected {expected}: {r.stdout} {r.stderr}')
    return {'args': args, 'exit_code': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}


def show_window():
    import tkinter as tk
    scenes = json.loads((OUT / 'scenes.json').read_text(encoding='utf-8'))
    app = tk.Tk()
    app.title('Strateg Video Check')
    app.geometry('1100x620+80+80')
    app.configure(bg='#111827')
    title = tk.Label(app, text='Стратег · проверка видео', bg='#111827', fg='#e5e7eb', font=('Segoe UI', 25, 'bold'))
    title.pack(anchor='w', padx=30, pady=(25, 12))
    caption = tk.Label(app, text='Ожидание начала записи…', bg='#111827', fg='#93c5fd', font=('Segoe UI', 16),
                       wraplength=1030, justify='left')
    caption.pack(anchor='w', padx=30, pady=12)
    body = tk.Text(app, bg='#1f2937', fg='#f3f4f6', insertbackground='white', relief='flat',
                   font=('Consolas', 15), wrap='word', padx=20, pady=20, height=14)
    body.pack(fill='both', expand=True, padx=30, pady=12)
    tk.Label(app, text='Реальные выводы команд · контролируемое тестовое окно · без звука',
             bg='#111827', fg='#9ca3af', font=('Segoe UI', 12)).pack(anchor='w', padx=30, pady=(0,20))
    (WORK / 'window-ready').write_text('ready')
    def display(index):
        scene = scenes[index]
        caption.configure(text=scene['title'])
        body.configure(state='normal')
        body.delete('1.0', 'end')
        body.insert('1.0', scene['screen_text'])
        body.configure(state='disabled')
        if index + 1 < len(scenes):
            app.after(4000, lambda: display(index + 1))
    def wait_start():
        if (WORK / 'recording-start').exists():
            display(0)
        else:
            app.after(50, wait_start)
    app.after(50, wait_start)
    app.after(30000, app.destroy)
    app.mainloop()


def main():
    if (OUT / 'result.json').exists() or (MEDIA / 'screen.mp4').exists():
        raise SystemExit('Video artifacts exist; inspect before repeating.')
    OUT.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    for name in ['tools', 'templates', 'config', 'knowledge']:
        shutil.copytree(ROOT / name, FIXTURE / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    cli(['new', 'video-check', '--title', 'Изолированная проверка видео', '--request', 'Проверить загрузку видео и границы известного содержания'])
    scenes = []
    for arm, label in [('chat', 'Обычный чат'), ('agent', 'Агент')]:
        response = ROOT / f'benchmarks/codex-2026-11-14/{arm}-response.md'
        result = cli(['validate', '--file', str(response)])
        # Display the actual output, with just the machine-specific absolute prefix shortened.
        displayed = result['stdout'].strip().replace(str(response), response.name)
        scenes.append({'title': label + ': один и тот же validate --file',
                       'screen_text': f'$ python tools/strateg.py validate --file {response.name}\n\n{displayed}',
                       'actual_command': result})
    result = cli(['data', 'compare', '--a', '200/10000', '--b', '300/10000'])
    scenes.append({'title': 'Воспроизводимый расчёт · условные данные, не продажи',
                   'screen_text': '$ python tools/strateg.py data compare --a 200/10000 --b 300/10000\n\n' + result['stdout'].strip(),
                   'actual_command': result})
    dump(OUT / 'scenes.json', scenes)
    ui = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'window'], cwd=ROOT, env=ENV)
    recorder = None
    try:
        for _ in range(100):
            if (WORK / 'window-ready').exists():
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Test window did not become ready')
        recording = MEDIA / 'screen.mp4'
        with (OUT / 'capture-stderr.txt').open('wb') as err:
            recorder = subprocess.Popen([shutil.which('ffmpeg'), '-hide_banner', '-y', '-f', 'gdigrab',
                                         '-framerate', '10', '-draw_mouse', '0', '-i', 'title=Strateg Video Check',
                                         '-t', '13', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '20',
                                         '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p',
                                         '-movflags', '+faststart', str(recording)], stdout=subprocess.DEVNULL, stderr=err)
            time.sleep(.5)
            (WORK / 'recording-start').write_text('start')
            if recorder.wait(timeout=35):
                raise RuntimeError('Window capture failed; inspect capture-stderr.txt')
    finally:
        if recorder and recorder.poll() is None:
            recorder.kill()
        if ui.poll() is None:
            ui.terminate()
        ui.wait(timeout=5)
    probe = json.loads(subprocess.check_output([shutil.which('ffprobe'), '-v', 'error', '-show_streams', '-show_format',
                                               '-of', 'json', str(recording)], encoding='utf-8'))
    digest = hashlib.sha256(recording.read_bytes()).hexdigest()
    decode = subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(recording), '-f', 'null', '-'],
                            capture_output=True, text=True, encoding='utf-8')
    assert decode.returncode == 0, decode.stderr
    presentation = OUT / 'screen.mp4'
    subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-y', '-i', str(recording),
                    '-vf', 'crop=1100:620:0:0', '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', str(presentation)], check=True)
    for index, second in enumerate([2,6,10], 1):
        subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-y', '-ss', str(second), '-i', str(presentation),
                        '-frames:v', '1', str(OUT / f'frame-{index}-{second:02d}s.png')], check=True)
    no_text = cli(['ingest', str(recording), '--kind', 'video', '--title', 'Контролируемая запись тестового окна без расшифровки'])
    registry = FIXTURE / 'projects/video-check/sources/sources.jsonl'
    before = [json.loads(s) for s in registry.read_text(encoding='utf-8').splitlines()]
    assert before[-1]['needs_transcript'] is True
    blocked = cli(['ev', 'add', '--type', 'fact', '--source', before[-1]['id'], '--loc', '00:02',
                   '--claim', 'На экране показан результат формальной проверки ответа чата'], expected=1)
    evidence = FIXTURE / 'projects/video-check/evidence/evidence.jsonl'
    assert not evidence.exists() or not evidence.read_text(encoding='utf-8').strip()
    transcript = ['WEBVTT', '', 'NOTE Экспорт текста экрана; речи и аудиодорожки нет. Не распознавание речи.', '']
    for i, scene in enumerate(scenes):
        transcript += [f'00:00:{i*4:02d}.500 --> 00:00:{(i+1)*4:02d}.400', scene['title'], scene['screen_text'], '']
    vtt = recording.with_suffix('.vtt')
    vtt.write_text('\n'.join(transcript), encoding='utf-8')
    refreshed = cli(['ingest', str(recording), '--kind', 'video', '--refresh',
                     '--title', 'Контролируемая запись тестового окна с текстом экрана'])
    after = [json.loads(s) for s in registry.read_text(encoding='utf-8').splitlines()]
    assert after[-1].get('transcript_from') and not after[-1].get('needs_transcript')
    accepted = cli(['ev', 'add', '--type', 'fact', '--source', after[-1]['id'], '--loc', '00:00:00.500–00:00:04.400',
                    '--claim', 'В тексте экранной записи результат validate для ответа чата содержит долю строк с опорой 27%',
                    '--conf', 'medium'])
    result = {'recording': str(recording), 'recording_sha256': digest, 'probe': probe,
              'decode_exit_code': decode.returncode, 'no_transcript_ingest': no_text,
              'unknown_content_fact_blocked': blocked, 'refresh_with_screen_text': refreshed,
              'known_text_fact_accepted': accepted, 'screen_transcript': str(vtt),
              'keyframe_seconds': [2,6,10], 'visual_review': 'pending',
              'presentation_copy': {'path': str(presentation), 'processing': 'crop black DPI padding only; no change to window content or timing'},
              'limitations': ['Controlled dedicated-window screen recording, not a real user interview',
                              'No audio track; VTT exports screen text, not speech recognition',
                              'Frames extracted externally by ffmpeg; ingest does not decode video',
                              'Old local placeholder source remains a separate record after refresh']}
    dump(OUT / 'result.json', result)
    shutil.copy2(vtt, OUT / 'screen.vtt')
    print(json.dumps({'video': str(recording), 'seconds': probe['format']['duration'],
                      'no_transcript_guard': 'passed', 'with_transcript': 'passed', 'visual_review': 'pending'}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    show_window() if len(sys.argv) > 1 and sys.argv[1] == 'window' else main()
