# -*- coding: utf-8 -*-
"""wx4 命令行入口。

典型用法：
    python -m wx4 all                  # 一键：检测 -> 取密钥 -> 解密 -> 导出
    python -m wx4 info                 # 只看环境探测结果
    python -m wx4 key                  # 只提取密钥
    python -m wx4 decrypt              # 只解密（用已保存的密钥）
    python -m wx4 sessions             # 列出会话
    python -m wx4 export -f html       # 导出全部会话
    python -m wx4 show <wxid>          # 在终端看某个会话
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time

# Windows 控制台默认 GBK，聊天记录里有 emoji，强制 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      errors="replace", line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                      errors="replace", line_buffering=True)
    except Exception:                                     # noqa: BLE001
        pass

from . import decrypt as dec
from . import export as exp
from . import key as keymod
from . import paths
from .reader import open_data

DEFAULT_KEY_FILE = "wx4_keys.json"
DEFAULT_DECRYPT_DIR = "app/DataBase/decrypted"


def log(msg):
    print(msg, flush=True)


def _account(args):
    acc = paths.find_account(getattr(args, "wxid", None))
    if not acc:
        log("[-] 没找到微信数据目录。请确认微信已登录，或用 --db-storage 指定。")
        return None
    return acc


def _db_storage(args):
    if getattr(args, "db_storage", None):
        return args.db_storage
    acc = paths.find_account(getattr(args, "wxid", None))
    return acc["db_storage"] if acc else None


# ---------------------------------------------------------------------------
def cmd_info(args):
    desc = paths.describe()
    log("微信安装目录 : %s" % desc["install_path"])
    log("Weixin.exe   : %s" % desc["weixin_exe"])
    log("数据根目录   : %s" % desc["xwechat_root"])
    log("已登录账号   : %s" % (", ".join(desc["logged_in_wxids"]) or "无"))
    procs = keymod.find_weixin_processes()
    log("运行中的进程 : %s"
        % (", ".join("PID=%d(%dMB)" % (p["pid"], p["mem_kb"] // 1024) for p in procs)
           or "微信未运行"))
    for a in desc["accounts"]:
        n = len(dec.list_encrypted(a["db_storage"]))
        log("账号 %-30s 库文件 %3d 个  %s" % (a["dir_name"], n, a["db_storage"]))
    return 0


def _do_key(args, db_storage):
    ex = keymod.KeyExtractor(db_storage, progress=log)
    try:
        ex.extract(save_to=args.key_file)
    except RuntimeError as e:
        log("[-] %s" % e)
        return None
    if not ex.keys:
        log("[-] 没能从内存里拿到任何密钥。")
        log("    常见原因：微信未登录 / 权限不足 / 微信版本差异。")
        log("    可以试试：1) 以管理员身份运行  2) 在微信里重新登录一次再运行")
        return None
    return ex


def cmd_key(args):
    db_storage = _db_storage(args)
    if not db_storage:
        return 1
    ex = _do_key(args, db_storage)
    return 0 if ex else 2


def _do_decrypt(args, db_storage):
    kf = args.key_file
    if not os.path.exists(kf):
        log("[-] 找不到密钥文件 %s，请先运行: python -m wx4 key" % kf)
        return None
    payload = keymod.load_keys(kf)
    keys = {k: v for k, v in payload.items() if not k.startswith("_")}
    if not keys:
        log("[-] 密钥文件里没有可用密钥")
        return None
    log("[*] 用 %d 个密钥解密 %s" % (len(keys), db_storage))
    res = dec.decrypt_all(keys, db_storage, args.out_dir, progress=log)
    log("[*] 成功 %d 个，失败 %d 个，跳过 %d 个"
        % (len(res["ok"]), len(res["failed"]), len(res["skipped"])))
    for rel, err in res["failed"]:
        log("    失败 %s：%s" % (rel, err))
    return res


def cmd_decrypt(args):
    db_storage = _db_storage(args)
    if not db_storage:
        return 1
    return 0 if _do_decrypt(args, db_storage) else 2


def cmd_all(args):
    acc = _account(args)
    if not acc:
        return 1
    log("[1/3] 提取密钥 ...")
    ex = _do_key(args, acc["db_storage"])
    if not ex:
        return 2
    log("[2/3] 解密数据库 ...")
    if not _do_decrypt(args, acc["db_storage"]):
        return 3
    log("[3/3] 导出聊天记录 ...")
    args.decrypted_dir = args.out_dir
    return cmd_export(args)


def _read(args):
    acc = paths.find_account(getattr(args, "wxid", None))
    account_dir = acc["path"] if acc else None
    data = open_data(args.decrypted_dir, getattr(args, "wxid", "") or "",
                     progress=log, account_dir=account_dir)
    if not data.msg_dbs:
        log("[-] %s 下没有解密后的 message_*.db，请先解密" % args.decrypted_dir)
        return None
    if not data.wxid and acc:
        data.wxid = acc["wxid"]
    return data


def cmd_sessions(args):
    data = _read(args)
    if not data:
        return 1
    sessions = data.sessions()
    log("共 %d 个会话（%d 个有消息）"
        % (len(sessions), sum(1 for s in sessions if data.has_messages(s["username"]))))
    for s in sessions:
        flag = "有" if data.has_messages(s["username"]) else "无"
        log("  [%s] %-34s %-24s %s"
            % (flag, s["username"][:34], s["display"][:24], s["summary"][:50]))
    return 0


def cmd_show(args):
    data = _read(args)
    if not data:
        return 1
    msgs = data.messages(args.session, limit=args.limit)
    log("会话 %s 共 %d 条" % (data.session_display(args.session), len(msgs)))
    for m in msgs:
        who = "我" if m["is_sender"] else m["sender"]
        log("[%s] %s: %s" % (m["time_str"], who, m["text"].replace("\n", " ⏎ ")))
    return 0


def cmd_export(args):
    data = _read(args)
    if not data:
        return 1
    sessions = [args.session] if args.session else None
    from datetime import datetime, timedelta
    start = int(datetime.strptime(args.start, "%Y-%m-%d").timestamp()) if args.start else None
    end = int((datetime.strptime(args.end, "%Y-%m-%d") + timedelta(days=1)).timestamp()) - 1 if args.end else None
    if start is not None and end is not None and start > end:
        raise ValueError("开始日期不能晚于结束日期")
    res = exp.export_all(data, args.export_dir, fmt=args.format,
                         sessions=sessions, progress=log,
                         media=args.media, images_only=args.images_only, copy_dat=not args.no_copy_dat, start=start, end=end)
    if args.format == "html" and not args.session:
        exp.export_index(data, args.export_dir, progress=log)
    log("[*] 导出目录：%s" % os.path.abspath(args.export_dir))
    return 0


def cmd_media(args):
    """按会话及日期范围精确导出图片、语音和文件。"""
    from datetime import datetime, timedelta
    from . import media as media_mod

    data = _read(args)
    if data is None:
        return 1

    start = (
        int(datetime.strptime(args.start, "%Y-%m-%d").timestamp())
        if args.start else None
    )
    end = (
        int((datetime.strptime(args.end, "%Y-%m-%d")
             + timedelta(days=1)).timestamp()) - 1
        if args.end else None
    )

    if start is not None and end is not None and start > end:
        raise ValueError("开始日期不能晚于结束日期")

    sessions = (
        [args.session] if args.session else
        [s["username"] for s in data.sessions()
         if data.has_messages(s["username"])]
    )

    total_images = total_voices = total_files = 0

    for session in sessions:
        msgs = data.messages(session, start=start, end=end)
        if not msgs:
            continue

        folder = os.path.join(
            args.media_dir,
            exp.safe_name(data.session_display(session))
            + "_" + exp.safe_name(session)
        )

        st = media_mod.export_session_media(
            data, session, msgs, folder,
            copy_dat=not args.no_copy_dat,
            progress=log
        )

        total_images += st.images
        total_voices += st.voices
        total_files += st.files

    log("===== MEDIA SUMMARY =====")
    log("IMAGES: %d" % total_images)
    log("VOICES: %d" % total_voices)
    log("FILES: %d" % total_files)
    log("MEDIA_EXPORT_DONE")
    return 0


def cmd_voice_export(args):
    """按联系人和日期范围批量导出语音。"""
    from .voice_batch import export_voice_batch

    data = _read(args)
    if data is None:
        return 1

    return export_voice_batch(
        data,
        session=args.session,
        start=args.start,
        end=args.end,
        export_dir=args.export_dir,
        progress=log,
    )


def cmd_legacy(args):
    """兼容老工具的输出目录结构（app/DataBase/Msg）。"""
    log("[!] 微信 4.x 的库结构与 3.x 完全不同，老版查看界面的数据层无法直接复用。")
    log("    app/DataBase/Msg 这类目录仅供 3.x 使用；4.x 请用 python -m wx4 导出。")
    return 0


# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="python -m wx4",
        description="PC 微信 4.x 聊天记录导出工具（密钥提取 + 解密 + 读取 + 导出）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--wxid", help="指定账号 wxid（默认取最近使用的账号）")
    p.add_argument("--db-storage", help="直接指定 db_storage 目录")
    p.add_argument("--key-file", default=DEFAULT_KEY_FILE, help="密钥文件（默认 %s）" % DEFAULT_KEY_FILE)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("info", help="查看环境探测结果").set_defaults(func=cmd_info)
    sub.add_parser("key", help="提取数据库密钥").set_defaults(func=cmd_key)
    d = sub.add_parser("decrypt", help="解密数据库")
    d.add_argument("--out-dir", default=DEFAULT_DECRYPT_DIR,
                   help="解密输出目录")
    d.set_defaults(func=cmd_decrypt)

    def add_common(sp, with_read=True):
        sp.add_argument("--out-dir", default=DEFAULT_DECRYPT_DIR,
                        help="解密输出目录（默认 %s）" % DEFAULT_DECRYPT_DIR)
        if with_read:
            sp.add_argument("--decrypted-dir", default=DEFAULT_DECRYPT_DIR,
                            help="已解密目录")

    def add_export_opts(sp):
        sp.add_argument("-f", "--format", default="html", choices=list(exp.EXPORTERS),
                        help="导出格式（默认 html）")
        sp.add_argument("--export-dir", default="app/DataBase/export", help="导出目录")
        sp.add_argument("--start", help="开始日期 YYYY-MM-DD")
        sp.add_argument("--end", help="结束日期 YYYY-MM-DD")
        sp.add_argument("--session", help="只导出指定会话")
        sp.add_argument("--media", action="store_true",
                        help="同时导出图片/语音/视频/文件")
        sp.add_argument("--images-only", action="store_true",
                        help="只导出文字和图片")
        sp.add_argument("--no-copy-dat", action="store_true",
                        help="媒体导出时不复制未能解密的 V2 图片(.dat)")

    a = sub.add_parser("all", help="一键：取密钥 + 解密 + 导出")
    add_common(a)
    add_export_opts(a)
    a.set_defaults(func=cmd_all)

    s = sub.add_parser("sessions", help="列出会话")
    add_common(s)
    s.set_defaults(func=cmd_sessions)

    sh = sub.add_parser("show", help="在终端显示某会话消息")
    add_common(sh)
    sh.add_argument("session", help="会话 wxid")
    sh.add_argument("-n", "--limit", type=int, default=50, help="显示最后 N 条")
    sh.set_defaults(func=cmd_show)

    e = sub.add_parser("export", help="导出聊天记录")
    add_common(e)
    add_export_opts(e)
    e.set_defaults(func=cmd_export)

    m = sub.add_parser("media", help="只导出媒体（图片/语音/视频/文件）")
    add_common(m)
    m.add_argument("--media-dir", default="app/DataBase/export/media")
    m.add_argument("--session", help="只导出指定会话")
    m.add_argument("--start", help="开始日期 YYYY-MM-DD")
    m.add_argument("--end", help="结束日期 YYYY-MM-DD")
    m.add_argument("--no-copy-dat", action="store_true",
                   help="不复制未能解密的 V2 图片(.dat)")
    m.set_defaults(func=cmd_media)

    v = sub.add_parser("voice-export", help="按联系人和日期批量导出MP3及ZIP")
    add_common(v)
    v.add_argument("--session", required=True, help="联系人或群聊wxid")
    v.add_argument("--start", required=True, help="开始日期 YYYY-MM-DD")
    v.add_argument("--end", required=True, help="结束日期 YYYY-MM-DD")
    v.add_argument("--export-dir", default="voice_batch_export",
                   help="语音导出根目录")
    v.set_defaults(func=cmd_voice_export)

    sub.add_parser("legacy", help="关于老版 3.x 界面的说明").set_defaults(func=cmd_legacy)
    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 0
    if args.cmd in ("all", "decrypt", "sessions", "show", "export", "voice-export", "media"):
        args.out_dir = getattr(args, "out_dir", DEFAULT_DECRYPT_DIR)
        args.decrypted_dir = getattr(args, "decrypted_dir", DEFAULT_DECRYPT_DIR)
    t0 = time.time()
    rc = args.func(args)
    if args.cmd in ("all", "key", "decrypt"):
        log("[*] 用时 %.1fs" % (time.time() - t0))
    return rc


if __name__ == "__main__":
    sys.exit(main())

