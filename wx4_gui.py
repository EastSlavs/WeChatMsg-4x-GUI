# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import subprocess
import threading
import sys
import os

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def account_database_dir(wxid):
    """每个微信账号使用独立的解密数据库目录。"""
    from wx4 import paths

    active = paths.find_account(wxid)
    if not active or active.get("wxid") != wxid:
        raise RuntimeError("找不到当前微信账号的数据目录")

    folder = ROOT / "app" / "DataBase" / "accounts" / wxid
    decrypted = folder / "decrypted"

    if not decrypted.is_dir():
        raise RuntimeError("当前账号尚未建立独立数据库")

    return decrypted


class App:
    def __init__(self, root):
        self.root = root
        root.title("微信 4.x 聊天记录导出工具")
        root.geometry("850x680")
        root.minsize(650, 520)

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="微信聊天记录导出", font=("Microsoft YaHei UI", 17, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 20))

        self.wxid = tk.StringVar(value="")
        self.session = tk.StringVar(value="")
        self.start = tk.StringVar(value="2026-09-01")
        self.end = tk.StringVar(value="2026-10-31")
        self.output = tk.StringVar(value=str(ROOT / "gui_export"))
        self.export_scope = tk.StringVar(value="单个会话")
        self.selected_sessions = []
        self.mode = tk.StringVar(value="完整聊天记录（文字、图片、语音、文件）")


        ttk.Label(frame, text="微信账号").grid(
            row=1, column=0, sticky="w", pady=8)
        self.account_combo = ttk.Combobox(
            frame, state="readonly", width=45
        )
        self.account_combo.grid(
            row=1, column=1, sticky="ew", padx=(12, 8), pady=8
        )
        self.account_combo.bind("<<ComboboxSelected>>", self.account_changed)
        ttk.Button(frame, text="刷新", command=self.load_accounts).grid(
            row=1, column=2, pady=8
        )

        ttk.Label(frame, text="搜索联系人").grid(
            row=2, column=0, sticky="w", pady=8)
        self.search_var = tk.StringVar()
        self.search_var.trace_add(
            "write", lambda *_: self.filter_contacts()
        )
        ttk.Entry(frame, textvariable=self.search_var).grid(
            row=2, column=1, columnspan=2,
            sticky="ew", padx=(12, 0), pady=8
        )

        ttk.Label(frame, text="选择联系人 / 群聊").grid(
            row=3, column=0, sticky="w", pady=8)
        self.contact_combo = ttk.Combobox(
            frame, state="readonly", width=45
        )
        self.contact_combo.grid(
            row=3, column=1, columnspan=2,
            sticky="ew", padx=(12, 0), pady=8
        )
        self.contact_combo.bind(
            "<<ComboboxSelected>>", self.contact_changed
        )

        for row, label, variable in [
            (4, "开始日期（YYYY-MM-DD）", self.start),
            (5, "结束日期（YYYY-MM-DD）", self.end),
        ]:
            ttk.Label(frame, text=label).grid(
                row=row, column=0, sticky="w", pady=8
            )
            ttk.Entry(frame, textvariable=variable).grid(
                row=row, column=1, columnspan=2,
                sticky="ew", padx=(12, 0), pady=8
            )


        # 导出内容
        ttk.Label(frame, text="导出内容").grid(
            row=6, column=0, sticky="w", pady=8
        )
        ttk.Combobox(
            frame,
            textvariable=self.mode,
            state="readonly",
            values=[
                "完整聊天记录（文字、图片、语音、文件）",
                "仅导出文字和图片",
                "仅批量导出语音（MP3 + ZIP）",
                "仅导出图片、语音、文件",
            ]
        ).grid(
            row=6, column=1, columnspan=2,
            sticky="ew", padx=(12, 0), pady=8
        )

        # 导出目录
        ttk.Label(frame, text="导出目录").grid(
            row=7, column=0, sticky="w", pady=8
        )
        ttk.Entry(
            frame, textvariable=self.output
        ).grid(
            row=7, column=1,
            sticky="ew", padx=(12, 8), pady=8
        )
        ttk.Button(
            frame, text="浏览", command=self.browse
        ).grid(row=7, column=2, pady=8)

        # 导出范围
        ttk.Label(frame, text="导出范围").grid(
            row=8, column=0, sticky="w", pady=8
        )
        self.scope_combo = ttk.Combobox(
            frame,
            textvariable=self.export_scope,
            values=("单个会话", "多选会话", "全部会话"),
            state="readonly",
            width=45
        )
        self.scope_combo.grid(
            row=8, column=1, sticky="ew", padx=(12, 8), pady=8
        )

        self.multi_button = ttk.Button(
            frame,
            text="选择多个（0）",
            command=self.choose_multiple_sessions
        )
        self.multi_button.grid(row=8, column=2, pady=8)

        # 开始导出
        self.button = ttk.Button(
            frame,
            text="开始导出",
            command=self.start_export
        )
        self.button.grid(
            row=9, column=0, columnspan=2,
            sticky="ew", pady=(18, 12)
        )
        self.cancel_button = ttk.Button(
            frame, text="取消导出",
            command=self.cancel_export,
            state="disabled"
        )
        self.cancel_button.grid(
            row=9, column=2, sticky="ew",
            pady=(18, 12), padx=(8, 0)
        )

        # 运行日志
        ttk.Label(
            frame, text="运行日志"
        ).grid(
            row=10, column=0, columnspan=3,
            sticky="w"
        )

        self.log = tk.Text(
            frame,
            height=12,
            font=("Consolas", 10),
            state="disabled"
        )
        self.log.grid(
            row=11, column=0, columnspan=3,
            sticky="nsew"
        )

        frame.rowconfigure(10, weight=1)

        self.accounts = {}
        self.contacts = {}
        self.all_contacts = []
        self.load_accounts()
        self.write("请选择微信账号和联系人，然后设置时间范围。")


    def load_accounts(self):
        """只显示正在登录的账号，自动读取账号名称。"""
        from wx4.key import find_weixin_processes
        from wx4.image_key import extract_master_key_from_cfg
        from wx4.reader import Wx4Data
        from wx4 import paths

        self.accounts.clear()
        active = set()

        for process in find_weixin_processes():
            try:
                result = extract_master_key_from_cfg(process["pid"])
                if result and result[2] and result[1]:
                    active.add(result[2])
            except (OSError, ValueError, TypeError):
                continue

        available = {
            item.get("wxid"): item
            for item in paths.describe().get("accounts", [])
        }

        decrypted_root = ROOT / "app" / "DataBase" / "decrypted"
        names = []

        for wxid in sorted(active):
            account = available.get(wxid)
            if not account:
                continue

            display = wxid

            # 当前数据库必须属于当前账号，避免拿到别人的备注。
            # 当前账号使用各自独立的数据库目录。
            if wxid:
                data = None
                try:
                    decrypted = account_database_dir(wxid)
                    data = Wx4Data(
                        str(decrypted),
                        wxid=wxid,
                        account_dir=account.get("path")
                    )

                    me = data.contacts.get(wxid) or {}
                    alias = (me.get("alias") or "").strip()
                    nickname = (me.get("nick_name") or "").strip()

                    if alias:
                        display = alias
                    elif nickname:
                        display = nickname

                except Exception as exc:
                    self.write("读取账号资料失败：" + str(exc))
                finally:
                    if data is not None:
                        data.close()

            label = "%s（当前登录）" % display

            # 避免两个账号使用相同昵称时产生冲突
            if label in self.accounts:
                label = "%s [%s]（当前登录）" % (display, wxid)

            self.accounts[label] = wxid
            names.append(label)

        self.account_combo["values"] = names

        if names:
            selected = names[0]
            self.account_combo.set(selected)
            self.wxid.set(self.accounts[selected])
            self.load_contacts()
            self.write("当前登录账号：%d 个" % len(names))
        else:
            self.account_combo.set("")
            self.wxid.set("")
            self.contact_combo.set("")
            self.session.set("")
            self.write("没有识别到当前登录的微信账号")

    def account_changed(self, event=None):
        selected = self.account_combo.get()
        if selected in self.accounts:
            self.wxid.set(self.accounts[selected])
            self.load_contacts()

    def load_contacts(self):
        """读取当前已解密数据库中的会话。"""
        from wx4.reader import Wx4Data
        from wx4 import paths

        wxid = self.wxid.get()
        account = paths.find_account(wxid)

        if not account:
            self.write("找不到对应账号的数据目录")
            return

        account_dir = account.get("path")
        decrypted = account_database_dir(wxid)

        data = None
        try:
            data = Wx4Data(
                str(decrypted),
                wxid=wxid,
                account_dir=account_dir
            )

            self.all_contacts = []
            for item in data.sessions():
                sid = item.get("username", "")
                display = item.get("display", sid)

                if not sid or not data.has_messages(sid):
                    continue

                self.all_contacts.append((display, sid))

            self.all_contacts.sort(key=lambda item: item[0])
            self.filter_contacts()

            self.write(
                "账号 %s：找到 %d 个有聊天记录的会话"
                % (wxid, len(self.all_contacts))
            )

        except Exception as exc:
            self.write("读取联系人失败：" + str(exc))

        finally:
            if data is not None:
                data.close()

    def filter_contacts(self):
        keyword = self.search_var.get().strip().casefold()

        matches = [
            (name, sid)
            for name, sid in self.all_contacts
            if keyword in name.casefold() or keyword in sid.casefold()
        ]

        self.contacts = {}
        labels = []

        for name, sid in matches:
            label = "%s  [%s]" % (name, sid)
            self.contacts[label] = sid
            labels.append(label)

        self.contact_combo["values"] = labels

        if labels:
            preferred = next(
                (label for label in labels
                 if self.contacts[label] == self.session.get()),
                labels[0]
            )
            self.contact_combo.set(preferred)
            self.session.set(self.contacts[preferred])
        else:
            self.contact_combo.set("")
            self.session.set("")

    def contact_changed(self, event=None):
        selected = self.contact_combo.get()
        if selected in self.contacts:
            self.session.set(self.contacts[selected])

    def choose_multiple_sessions(self):
        win = tk.Toplevel(self.root)
        win.title("多选联系人 / 群聊")
        win.geometry("620x540")
        win.transient(self.root)
        win.grab_set()

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="点击联系人可勾选或取消，支持选择任意数量"
        ).pack(anchor="w", pady=(0, 8))

        search = tk.StringVar()
        ttk.Entry(frame, textvariable=search).pack(
            fill="x", pady=(0, 8)
        )

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)

        listing = tk.Listbox(
            body,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            font=("Microsoft YaHei UI", 10)
        )
        listing.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(
            body, orient="vertical", command=listing.yview
        )
        scroll.pack(side="right", fill="y")
        listing.configure(yscrollcommand=scroll.set)

        selected = set(self.selected_sessions)
        visible = []
        updating = [False]

        def remember(event=None):
            if updating[0]:
                return
            visible_ids = {sid for _, sid in visible}
            selected.difference_update(visible_ids)
            for i in listing.curselection():
                selected.add(visible[i][1])
            counter.configure(text="已选择 %d 个会话" % len(selected))

        def refresh(*args):
            updating[0] = True
            try:
                visible.clear()
                listing.delete(0, "end")
                keyword = search.get().strip().casefold()

                for name, sid in self.all_contacts:
                    if keyword in name.casefold() or keyword in sid.casefold():
                        visible.append((name, sid))
                        listing.insert("end", "%s  [%s]" % (name, sid))

                for i, (_, sid) in enumerate(visible):
                    if sid in selected:
                        listing.selection_set(i)
            finally:
                updating[0] = False

            counter.configure(text="已选择 %d 个会话" % len(selected))

        listing.bind("<<ListboxSelect>>", remember)
        search.trace_add("write", refresh)

        counter = ttk.Label(frame, text="")
        counter.pack(anchor="w", pady=8)

        def confirm():
            remember()
            self.selected_sessions = sorted(selected)
            self.multi_button.configure(
                text="选择多个（%d）" % len(self.selected_sessions)
            )
            self.export_scope.set("多选会话")
            win.destroy()

        ttk.Button(
            frame, text="确定选择", command=confirm
        ).pack(fill="x")

        refresh()
        win.wait_window()

    def browse(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output.set(folder)

    def write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # GUI_BATCH_OPTIMIZED_V1
    def start_export(self):
        from datetime import datetime

        try:
            first = datetime.strptime(self.start.get(), "%Y-%m-%d")
            last = datetime.strptime(self.end.get(), "%Y-%m-%d")
            if first > last:
                raise ValueError("开始日期不能晚于结束日期")
        except ValueError as exc:
            messagebox.showerror("日期错误", str(exc))
            return

        wxid = self.wxid.get().strip()
        session = self.session.get().strip()
        mode = self.mode.get()
        scope = self.export_scope.get()
        output = self.output.get().strip()
        start_date = self.start.get().strip()
        end_date = self.end.get().strip()

        multi = scope == "多选会话"
        all_sessions = scope == "全部会话"
        chosen = list(self.selected_sessions) if multi else []

        if not wxid or not output:
            messagebox.showerror("参数不完整", "请指定账号和导出目录")
            return

        if scope == "单个会话" and not session:
            messagebox.showerror("参数不完整", "请选择联系人")
            return

        if multi:
            valid = {sid for _, sid in self.all_contacts}
            if not chosen or not set(chosen).issubset(valid):
                messagebox.showerror(
                    "选择错误", "请选择当前账号的联系人"
                )
                return

        if all_sessions:
            if not messagebox.askyesno(
                "确认全部导出",
                "确定按 %s 至 %s 导出全部会话吗？"
                % (start_date, end_date)
            ):
                return

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if multi or all_sessions:
            prefix = "多选会话" if multi else "全部会话"
            export_output = str(
                Path(output) /
                ("%s_%s_至_%s_%s"
                 % (prefix, start_date, end_date, stamp))
            )
        else:
            export_output = output

        self.cancel_requested = False
        self.current_process = None
        self.button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.write("开始更新数据库……")

        def emit(message):
            value = str(message)
            self.root.after(
                0,
                lambda line=value: self.write(line)
            )

        def worker():
            try:
                from wx4.account_update import update_account_database

                decrypted = update_account_database(
                    wxid, ROOT, progress=emit
                )

                if self.cancel_requested:
                    raise RuntimeError("用户已取消任务")

                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONPATH"] = str(ROOT)

                cmd_base = [
                    str(PYTHON), "-u", "-m", "wx4",
                    "--wxid", wxid
                ]

                is_voice = mode.startswith("仅批量导出语音")
                is_media = mode.startswith("仅导出图片")
                images_only = mode == "仅导出文字和图片"

                commands = []

                if multi and not is_voice and not is_media:
                    command = [
                        str(PYTHON), "-u", "-m", "wx4.gui_batch",
                        "--wxid", wxid,
                        "--decrypted-dir", str(decrypted),
                        "--export-dir", export_output,
                        "--start", start_date,
                        "--end", end_date
                    ]
                    for sid in chosen:
                        command += ["--session", sid]
                    if images_only:
                        command.append("--images-only")
                    commands.append(command)
                else:
                    if multi:
                        targets = chosen
                    elif all_sessions:
                        targets = [None]
                    else:
                        targets = [session]

                    for index, sid in enumerate(targets, 1):
                        if is_voice:
                            cmd = cmd_base + ["voice-export"]
                            dest_flag = "--export-dir"
                        elif is_media:
                            cmd = cmd_base + ["media"]
                            dest_flag = "--media-dir"
                        else:
                            cmd = cmd_base + ["export"]
                            dest_flag = "--export-dir"

                        dest = export_output
                        if multi:
                            safe = "".join(
                                c if c.isalnum() or c in "-_"
                                else "_"
                                for c in sid
                            )[:90]
                            dest = str(
                                Path(export_output) /
                                ("%04d_%s" % (index, safe))
                            )

                        cmd += [
                            "--decrypted-dir", str(decrypted),
                            "--start", start_date,
                            "--end", end_date
                        ]
                        if sid:
                            cmd += ["--session", sid]

                        cmd += [dest_flag, dest]
                        if is_media:
                            cmd += ["--no-copy-dat"]
                        elif not is_voice:
                            cmd += ["--no-copy-dat"]
                            cmd.append(
                                "--images-only"
                                if images_only else "--media"
                            )

                        commands.append(cmd)

                # 独立保存完整日志，不再截断最后16000字符。
                logs_dir = Path(output) / "_logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                log_path = logs_dir / (
                    "export_" + stamp + ".log"
                )
                emit("完整日志：" + str(log_path))

                code = 0
                with log_path.open(
                    "w", encoding="utf-8", errors="replace"
                ) as log:
                    for index, cmd in enumerate(commands, 1):
                        if self.cancel_requested:
                            code = 130
                            break

                        emit(
                            "导出任务 %d/%d" %
                            (index, len(commands))
                        )

                        proc = subprocess.Popen(
                            cmd,
                            cwd=str(ROOT),
                            env=env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            bufsize=1
                        )
                        self.current_process = proc

                        try:
                            for line in proc.stdout:
                                log.write(line)
                                log.flush()
                                emit(line.rstrip("\r\n"))
                        finally:
                            proc.stdout.close()

                        code = proc.wait()
                        self.current_process = None

                        if self.cancel_requested:
                            code = 130
                            break

                        if code != 0:
                            emit(
                                "任务失败，退出码：" + str(code)
                            )
                            break

                if self.cancel_requested:
                    code = 130

                message = (
                    "导出已取消" if code == 130 else
                    "导出完成" if code == 0 else
                    "导出失败，请查看完整日志"
                )

                self.root.after(
                    0,
                    lambda rc=code, msg=message:
                        self.finish_and_refresh(msg, rc, session)
                )

            except Exception as exc:
                error = str(exc)
                self.root.after(
                    0,
                    lambda msg=error: self.finish(msg, 1)
                )
            finally:
                self.current_process = None

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def cancel_export(self):
        if not self.button.instate(["disabled"]):
            return

        self.cancel_requested = True
        self.cancel_button.configure(state="disabled")
        self.write("正在取消任务……")

        proc = self.current_process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError as exc:
                self.write("取消进程失败：" + str(exc))

    def finish_and_refresh(self, result, code, selected_session):
        """导出完成后刷新联系人，并尽量保留原来的选择。"""
        self.finish(result, code)

        if code != 0:
            return

        try:
            self.load_contacts()

            # 刷新可能重建联系人选项，恢复原来的会话 ID。
            self.session.set(selected_session)
            self.write("联系人和群聊列表已自动刷新")

        except Exception as exc:
            self.write("联系人刷新失败：" + str(exc))

    def finish(self, result, code):
        self.write(result)
        status = (
            "成功" if code == 0 else
            "已取消" if code == 130 else
            "失败"
        )
        self.write("执行结果：" + status)
        self.button.configure(state="normal")
        self.cancel_button.configure(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()