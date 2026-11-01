# -*- coding: utf-8 -*-
"""GUI 多选导出：统一索引与结果统计。"""

import argparse
import html
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from wx4 import export as exp
from wx4 import paths
from wx4.reader import Wx4Data


def create_index(data, out_dir, sessions, counts, start_date, end_date):
    root = Path(out_dir)
    rows = []
    success = empty = failed = 0

    for number, sid in enumerate(sessions, 1):
        name = data.session_display(sid)
        count = counts[sid]
        suffix = sid[:24].replace("@", "_at_")
        matches = sorted(root.glob("*_" + suffix + ".html"))

        if count == 0:
            status = "无消息"
            operation = "—"
            empty += 1
        elif matches:
            status = "成功"
            relative = matches[0].relative_to(root).as_posix()
            url = html.escape(quote(relative, safe="/"), quote=True)
            operation = '<a href="' + url + '">查看聊天记录</a>'
            success += 1
        else:
            status = "失败：缺少HTML"
            operation = "—"
            failed += 1

        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td>"
            "<td>{}</td><td>{}</td></tr>".format(
                number,
                html.escape(str(name)),
                count,
                html.escape(status),
                operation
            )
        )

    page = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>微信聊天记录导出索引</title>
<style>
body{{font-family:"Microsoft YaHei",Arial,sans-serif;
max-width:1100px;margin:35px auto;padding:0 20px;
background:#f6f7f9;color:#222}}
h1{{font-size:25px}}
.summary{{padding:16px;background:white;border-radius:8px;
margin-bottom:20px;line-height:2}}
table{{width:100%;border-collapse:collapse;background:white}}
th,td{{padding:13px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#eaf0f6}}
a{{color:#1677d2;text-decoration:none}}
tr:hover{{background:#f4f8fd}}
</style>
</head>
<body>
<h1>微信聊天记录导出索引</h1>
<div class="summary">
<div>日期范围：{start} 至 {end}</div>
<div>选中会话：{total} 个</div>
<div>成功：{success} 个 | 无消息：{empty} 个 | 失败：{failed} 个</div>
<div>日期内消息总数：{messages} 条</div>
</div>
<table>
<thead><tr>
<th>序号</th><th>联系人 / 群聊</th>
<th>消息数量</th><th>状态</th><th>操作</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</body></html>""".format(
        start=html.escape(start_date),
        end=html.escape(end_date),
        total=len(sessions),
        success=success,
        empty=empty,
        failed=failed,
        messages=sum(counts.values()),
        rows="\n".join(rows)
    )

    root.mkdir(parents=True, exist_ok=True)
    index = root / "index.html"
    index.write_text(page, encoding="utf-8")

    print(
        "导出统计：选中 %d 个，成功 %d 个，无消息 %d 个，失败 %d 个"
        % (len(sessions), success, empty, failed),
        flush=True
    )
    print(
        "日期内消息总数：%d 条" % sum(counts.values()),
        flush=True
    )
    print("统一HTML入口：" + str(index), flush=True)

    return failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wxid", required=True)
    parser.add_argument("--decrypted-dir", required=True)
    parser.add_argument("--export-dir", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--session", action="append", required=True)
    parser.add_argument("--images-only", action="store_true")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    if start > end:
        raise ValueError("开始日期不能晚于结束日期")

    account = paths.find_account(args.wxid)
    if not account or account.get("wxid") != args.wxid:
        raise RuntimeError("账号数据目录不匹配")

    # 去重，保留原选择顺序。
    sessions = list(dict.fromkeys(args.session))

    start_ts = int(start.timestamp())
    end_ts = int((end + timedelta(days=1)).timestamp()) - 1

    data = None
    try:
        print("正在加载数据库……", flush=True)
        data = Wx4Data(
            args.decrypted_dir,
            wxid=args.wxid,
            account_dir=account["path"]
        )

        print(
            "开始批量导出，共 %d 个选定会话" % len(sessions),
            flush=True
        )

        # 与实际导出使用完全相同的日期范围。
        counts = {}

        for sid in sessions:
            counts[sid] = len(
                data.messages(sid, start=start_ts, end=end_ts)
            )

        exp.export_all(
            data,
            args.export_dir,
            fmt="html",
            sessions=sessions,
            progress=lambda msg: print(msg, flush=True),
            media=not args.images_only,
            images_only=args.images_only,
            copy_dat=False,
            start=start_ts,
            end=end_ts
        )

        failed = create_index(
            data,
            args.export_dir,
            sessions,
            counts,
            args.start,
            args.end
        )

        if failed:
            print(
                "BATCH_EXPORT_INCOMPLETE: %d 个会话缺少HTML" % failed,
                flush=True
            )
            return 1

        print("BATCH_EXPORT_SUCCESS", flush=True)
        return 0

    finally:
        if data is not None:
            data.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
