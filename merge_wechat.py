from pathlib import Path
from bs4 import BeautifulSoup
from html import escape

root = Path(__file__).resolve().parent / "export_20days"
files = sorted(p for p in root.glob("*.html")
               if p.name != "index.html" and p.name != "wechat_20days.html")

sections = []
total = 0

for p in files:
    soup = BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
    title = soup.select_one("h1")
    name = title.get_text(" ", strip=True) if title else p.stem
    messages = []

    for m in soup.select("main .msg"):
        body = m.select_one(".bub")
        if body is None:
            continue

        who = m.select_one(".name")
        tm = m.select_one(".time")

        sender = who.get_text(" ", strip=True) if who else "未知"
        timestamp = tm.get_text(" ", strip=True) if tm else ""
        content = body.get_text("\n", strip=True)

        messages.append(
            '<div class="msg">'
            f'<div class="info">{escape(timestamp)}　{escape(sender)}</div>'
            f'<div class="body">{escape(content)}</div>'
            '</div>'
        )

    if messages:
        total += len(messages)
        sections.append(
            f'<section><h2>{escape(name)}（{len(messages)} 条）</h2>'
            + "".join(messages)
            + '</section>'
        )

html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>微信聊天记录</title>
<style>
body {
    font-family: "Microsoft YaHei", sans-serif;
    font-size: 12px;
    line-height: 1.6;
}
h1 { text-align: center; }
h2 {
    font-size: 16px;
    border-bottom: 2px solid #555;
    padding-bottom: 6px;
}
section { break-before: page; }
.msg {
    padding: 6px 0;
    border-bottom: 1px solid #eee;
    break-inside: avoid;
}
.info { font-weight: bold; color: #444; }
.body { white-space: pre-wrap; overflow-wrap: anywhere; }
@page { size: A4; margin: 15mm; }
</style>
</head>
<body>
"""

html += "<h1>微信聊天记录</h1>"
html += "<p>时间范围：2026-10-07 至 2026-10-26</p>"
html += f"<p>共 {len(sections)} 个会话，{total} 条消息</p>"
html += "".join(sections)
html += "</body></html>"

output = root / "wechat_20days.html"
output.write_text(html, encoding="utf-8")

print("生成成功:", output)
print("会话数量:", len(sections))
print("消息数量:", total)