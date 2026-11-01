
"""按账号安全更新已解密的微信数据库。"""
from pathlib import Path
from datetime import datetime
import os
import sqlite3
import subprocess
import sys

from . import paths


def update_account_database(wxid, root_dir, progress=print):
    root = Path(root_dir).resolve()
    account = paths.find_account(wxid)

    if not account or account.get("wxid") != wxid:
        raise RuntimeError("微信账号与数据目录不匹配")

    base = root / "app" / "DataBase" / "accounts" / wxid
    target = base / "decrypted"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    staging = base / ("staging_" + stamp)
    backup = base / ("backup_" + stamp)
    keyfile = base / ("key_" + stamp + ".json")

    base.mkdir(parents=True, exist_ok=True)

    def run(args, title):
        progress(title)
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        p = subprocess.run(
            [sys.executable, "-m", "wx4"] + args,
            cwd=str(root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600
        )
        if p.returncode != 0:
            raise RuntimeError(
                title + "失败，退出码 " + str(p.returncode)
                + "\n" + p.stdout[-1500:]
            )
        progress(title + "成功")
        return p.stdout

    try:
        run(
            ["--wxid", wxid,
             "--key-file", str(keyfile), "key"],
            "提取数据库密钥"
        )

        if not keyfile.is_file():
            raise RuntimeError("没有生成密钥文件")

        run(
            ["--wxid", wxid,
             "--key-file", str(keyfile),
             "decrypt", "--out-dir", str(staging)],
            "解密最新数据库"
        )

        new_dbs = sorted(staging.rglob("message_[0-9]*.db"))
        old_dbs = (
            sorted(target.rglob("message_[0-9]*.db"))
            if target.exists() else []
        )

        if not new_dbs:
            raise RuntimeError("没有找到解密后的消息数据库")

        if old_dbs and len(new_dbs) < len(old_dbs):
            raise RuntimeError("新的消息数据库数量减少，停止更新")

        # 检查旧数据库中的文件是否全部存在于新数据库。
        if target.exists():
            old_names = {
                p.relative_to(target).as_posix()
                for p in target.rglob("*.db")
            }
            new_names = {
                p.relative_to(staging).as_posix()
                for p in staging.rglob("*.db")
            }

            missing = old_names - new_names

            if missing:
                raise RuntimeError(
                    "新数据库缺少文件：" + ", ".join(sorted(missing))
                )

        # 除消息库外，也必须存在联系人的数据库和语音数据库。
        required = ["contact.db", "media_0.db"]
        for name in required:
            if not list(staging.rglob(name)):
                raise RuntimeError("缺少必要数据库：" + name)

        # 检验SQLite是否能正常读取。
        for db in staging.rglob("*.db"):
            con = sqlite3.connect(
                "file:" + db.resolve().as_posix() + "?mode=ro",
                uri=True
            )
            try:
                result = con.execute(
                    "PRAGMA quick_check"
                ).fetchone()
                if not result or result[0] != "ok":
                    raise RuntimeError("数据库校验失败：" + db.name)
            finally:
                con.close()

        progress("数据库校验通过：" + str(len(new_dbs)) + "个消息库")

        # 先保留旧版本，再启用新版本。
        moved_old = False
        try:
            if target.exists():
                target.rename(backup)
                moved_old = True
            staging.rename(target)
        except Exception:
            if moved_old and not target.exists():
                backup.rename(target)
            raise

        progress("数据库更新成功")
        if moved_old:
            progress("旧数据库备份：" + str(backup))
        return target

    finally:
        # 临时密钥不保留，独立账号原有密钥不受影响。
        try:
            if keyfile.exists():
                keyfile.unlink()
        except OSError:
            progress("临时密钥未能删除，请检查：" + str(keyfile))
