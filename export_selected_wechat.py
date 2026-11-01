# -*- coding: utf-8 -*-
"""Merge only chat sessions listed in wechat_sessions.csv into one searchable PDF.

Place this script and the CSV in the WeChatMsg-4x-main project folder. It reads existing
export_20days/*.html and never touches the encrypted WeChat database.
"""
from pathlib import Path
from html import escape
import csv
import os
import shutil
import subprocess
import tempfile
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
CSV_FILE = BASE / 'wechat_sessions.csv'
SOURCE = BASE / 'export_20days'
OUT_HTML = BASE / 'wechat_selected_20days.html'
OUT_PDF = BASE / 'wechat_selected_20days.pdf'

if not CSV_FILE.is_file():
    raise SystemExit(f'Missing CSV: {CSV_FILE}')
if not SOURCE.is_dir():
    raise SystemExit(f'Missing source directory: {SOURCE}')

with CSV_FILE.open('r', encoding='utf-8-sig', newline='') as f:
    rows = list(csv.reader(f))[1:]

selected = []
for row in rows:
    if len(row) >= 3 and row[2].strip():
        selected.append((row[0].strip(), row[2].strip()))
if not selected:
    raise SystemExit('CSV contains no selected sessions')

missing = []
sections = []
nav = []
message_count = 0
seen = set()

for name, filename in selected:
    # Restrict input paths to simple filenames from the source folder.
    if Path(filename).name != filename or not filename.lower().endswith('.html'):
        missing.append(filename)
        continue
    if filename in seen:
        continue
    seen.add(filename)
    src = SOURCE / filename
    if not src.is_file():
        missing.append(filename)
        continue
    soup = BeautifulSoup(src.read_text(encoding='utf-8'), 'html.parser')
    h1 = soup.select_one('h1')
    title = h1.get_text(' ', strip=True) if h1 else name
    messages = []
    for msg in soup.select('main .msg'):
        body = msg.select_one('.bub')
        if body is None:
            continue  # Skip system messages without normal message content.
        tm = msg.select_one('.time')
        who = msg.select_one('.name')
        time_text = tm.get_text(' ', strip=True) if tm else ''
        sender = who.get_text(' ', strip=True) if who else 'Unknown'
        text = body.get_text('\n', strip=True)
        messages.append(
            '<div class="msg"><div class="info">'
            f'{escape(time_text)}　{escape(sender)}'
            '</div><div class="body">'
            f'{escape(text)}'
            '</div></div>'
        )
    if not messages:
        continue
    idx = len(sections) + 1
    nav.append(f'<li><a href="#session-{idx}">{escape(title)}</a> ({len(messages)})</li>')
    sections.append(f'<section id="session-{idx}"><h2>{idx}. {escape(title)} ({len(messages)} messages)</h2>' + ''.join(messages) + '</section>')
    message_count += len(messages)

if missing:
    print('WARNING: these source HTML files are missing or invalid:')
    for f in missing:
        print('  ' + f)
if not sections:
    raise SystemExit('No readable chat messages in selected files; PDF not created')

html_doc = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>微信聊天记录 - 选定会话</title>
<style>
@page {size:A4; margin:14mm 13mm}
body {font-family:"Microsoft YaHei","Microsoft JhengHei",sans-serif; font-size:11px; line-height:1.55; color:#222}
h1 {text-align:center; font-size:22px}
h2 {font-size:16px; border-bottom:1px solid #777; padding-bottom:5px}
.meta {text-align:center; color:#555}
.toc {columns:2; font-size:11px; padding:0 10px}
.toc li {break-inside:avoid; padding:2px 0}
a {color:#1263ab; text-decoration:none}
section {break-before:page}
.msg {padding:5px 0; border-bottom:1px solid #ddd; break-inside:avoid-page}
.info {font-weight:bold; color:#555}
.body {white-space:pre-wrap; overflow-wrap:anywhere}
</style></head><body>'''
html_doc += '<h1>微信聊天记录</h1><p class="meta">2026-10-07 至 2026-10-26</p>'
html_doc += f'<p class="meta">{len(sections)} 个会话 · {message_count} 条正文消息</p>'
html_doc += '<h2>会话目录</h2><ol class="toc">' + ''.join(nav) + '</ol>'
html_doc += ''.join(sections) + '</body></html>'
OUT_HTML.write_text(html_doc, encoding='utf-8')
print(f'Selected sessions: {len(selected)}')
print(f'Included sessions: {len(sections)}')
print(f'Text messages: {message_count}')
print(f'HTML created: {OUT_HTML}')

edge_candidates = [
    Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
    Path(os.environ.get('PROGRAMFILES', r'C:\Program Files')) / 'Microsoft/Edge/Application/msedge.exe',
    Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/Edge/Application/msedge.exe',
]
edge = next((p for p in edge_candidates if p.is_file()), None)
if edge is None:
    print('Edge not found. Open the HTML in a browser and use Ctrl+P > Save as PDF.')
else:
    with tempfile.TemporaryDirectory(prefix='wechat_pdf_') as profile:
        cmd = [str(edge), '--headless=new', '--disable-gpu', '--no-first-run',
               '--no-pdf-header-footer', f'--user-data-dir={profile}',
               f'--print-to-pdf={OUT_PDF}', OUT_HTML.as_uri()]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
            if OUT_PDF.is_file() and OUT_PDF.stat().st_size > 1000:
                print(f'PDF created: {OUT_PDF} ({OUT_PDF.stat().st_size / 1024 / 1024:.1f} MB)')
            else:
                print('Automatic PDF export did not succeed. Open HTML in Edge and use Ctrl+P > Save as PDF.')
                if result.stderr:
                    print(result.stderr[-900:])
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f'Automatic PDF export failed: {e}')
            print('Open HTML in Edge and use Ctrl+P > Save as PDF.')
