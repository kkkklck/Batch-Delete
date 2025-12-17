# -*- coding: utf-8 -*-
"""
文件按日期清理（UI版）
- 选择文件夹后：递归扫描所有子文件夹里的文件（强制递归）
- 按日期/区间筛选（默认按修改时间 mtime）
- 先“扫描预览”，再“确认执行”
- 动作可选：移入 _trash_YYYYMMDD_HHMMSS（可反悔）或永久删除（需二次确认）
- 执行完不退出，可继续下一轮
"""

from __future__ import annotations

import fnmatch
import os
import queue
import shutil
import threading
import time as _time
from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


# --------------------- 数据结构 ---------------------

@dataclass
class Hit:
    path: Path
    when: datetime
    size: int


# --------------------- 工具函数 ---------------------

def human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{int(x)}B" if u == "B" else f"{x:.1f}{u}"
        x /= 1024
    return f"{n}B"


def parse_ymd(s: str) -> date:
    s = (s or "").strip()
    return datetime.strptime(s, "%Y-%m-%d").date()


def day_range_local(d: date) -> Tuple[datetime, datetime]:
    start = datetime.combine(d, time.min)
    end = datetime.combine(date.fromordinal(d.toordinal() + 1), time.min)
    return start, end


def get_file_time(p: Path, field: str) -> datetime:
    st = p.stat()
    ts = st.st_mtime if field == "mtime" else st.st_ctime
    return datetime.fromtimestamp(ts)


def split_patterns(s: str) -> Optional[List[str]]:
    s = (s or "").strip()
    if not s:
        return None
    parts = [x.strip() for x in s.split(",") if x.strip()]
    return parts or None


def match_any(name: str, patterns: Optional[List[str]]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def make_trash_dir(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = root / f"_trash_{stamp}"
    d.mkdir(parents=True, exist_ok=False)
    return d


def safe_relpath(file_path: Path, root: Path) -> Path:
    """尽量用相对路径；如果相对失败（极少），就退回只用文件名。"""
    try:
        return file_path.relative_to(root)
    except Exception:
        return Path(file_path.name)


# --------------------- 后台任务：扫描/执行 ---------------------

def worker_scan(
    q: queue.Queue,
    root: Path,
    time_field: str,
    mode: str,
    start_dt: datetime,
    end_dt: datetime,
    includes: Optional[List[str]],
    excludes: Optional[List[str]],
    skip_trash: bool,
    max_preview: int,
):
    """
    后台扫描：递归 root 下所有文件，筛选命中项。
    q 里发事件：
      ('scan_progress', scanned_count)
      ('scan_done', hits, scanned_total, total_bytes)
      ('scan_error', msg)
    """
    try:
        hits: List[Hit] = []
        scanned = 0
        total_bytes = 0

        trash_prefix = "_trash_"

        # rglob('*') 会递归扫描所有子文件夹
        for p in root.rglob("*"):
            if not p.is_file():
                continue

            scanned += 1
            if scanned % 500 == 0:
                q.put(("scan_progress", scanned))

            # 默认跳过 _trash_* 目录里的文件，避免二次误伤
            if skip_trash:
                try:
                    rel = p.relative_to(root)
                    if rel.parts and str(rel.parts[0]).startswith(trash_prefix):
                        continue
                except Exception:
                    pass

            name = p.name
            if excludes and match_any(name, excludes):
                continue
            if includes and not match_any(name, includes):
                continue

            try:
                dt = get_file_time(p, time_field)
            except (FileNotFoundError, PermissionError):
                continue

            ok = False
            if mode == "on":
                ok = (start_dt <= dt < end_dt)
            elif mode == "before":
                ok = (dt < start_dt)
            elif mode == "after":
                ok = (dt >= start_dt)  # 含当天之后
            elif mode == "between":
                ok = (start_dt <= dt < end_dt)

            if ok:
                try:
                    size = p.stat().st_size
                except Exception:
                    size = 0
                hits.append(Hit(path=p, when=dt, size=size))
                total_bytes += size

        hits.sort(key=lambda x: x.when)
        q.put(("scan_done", hits, scanned, total_bytes, max_preview))
    except Exception as e:
        q.put(("scan_error", f"{type(e).__name__}: {e}"))


def worker_execute(
    q: queue.Queue,
    root: Path,
    hits: List[Hit],
    action: str,
):
    """
    后台执行：
      - action == 'trash'：移动到 _trash_*
      - action == 'delete'：永久删除
    q 里发事件：
      ('exec_progress', i, total)
      ('exec_done', ok, fail, trash_dir_or_none, errors_preview)
      ('exec_error', msg)
    """
    try:
        total = len(hits)
        ok = 0
        fail = 0
        errors: List[str] = []

        trash_dir: Optional[Path] = None
        if action == "trash":
            trash_dir = make_trash_dir(root)

        for i, h in enumerate(hits, start=1):
            if i % 20 == 0 or i == total:
                q.put(("exec_progress", i, total))

            try:
                if action == "delete":
                    h.path.unlink()
                else:
                    assert trash_dir is not None
                    rel = safe_relpath(h.path, root)
                    dest = trash_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)

                    if dest.exists():
                        stamp = datetime.now().strftime("%H%M%S_%f")
                        dest = dest.with_name(dest.stem + f"__{stamp}" + dest.suffix)

                    shutil.move(str(h.path), str(dest))

                ok += 1
            except Exception as e:
                fail += 1
                if len(errors) < 20:
                    errors.append(f"{h.path} -> {type(e).__name__}: {e}")

        q.put(("exec_done", ok, fail, str(trash_dir) if trash_dir else None, errors))
    except Exception as e:
        q.put(("exec_error", f"{type(e).__name__}: {e}"))


# --------------------- UI 主体 ---------------------

class CleanerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🧹 按日期清理文件（递归扫描）")
        self.geometry("1050x720")
        self.minsize(950, 650)

        # 状态
        self.q: queue.Queue = queue.Queue()
        self.scan_thread: Optional[threading.Thread] = None
        self.exec_thread: Optional[threading.Thread] = None

        self.hits: List[Hit] = []
        self.last_scan_signature: Optional[str] = None
        self.dirty_after_scan: bool = True

        self._build_ui()
        self._poll_queue()

    # ---------- UI 构建 ----------

    def _build_ui(self):
        # 顶部：目录选择
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="目标文件夹：").pack(side="left")
        self.var_folder = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.var_folder)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 6))

        ttk.Button(top, text="选择…", command=self.on_browse).pack(side="left")
        ttk.Button(top, text="打开目录", command=self.on_open_folder).pack(side="left", padx=(6, 0))

        # 中部：参数区
        mid = ttk.Frame(self, padding=(10, 0, 10, 10))
        mid.pack(fill="x")

        # 第1行：时间字段 + 模式
        row1 = ttk.Frame(mid)
        row1.pack(fill="x", pady=(0, 8))

        ttk.Label(row1, text="时间字段：").pack(side="left")
        self.var_time_field = tk.StringVar(value="mtime")
        ttk.Radiobutton(row1, text="修改时间 mtime（推荐）", value="mtime",
                        variable=self.var_time_field, command=self.mark_dirty).pack(side="left", padx=(6, 6))
        ttk.Radiobutton(row1, text="ctime（Windows≈创建；Linux=状态变更）", value="ctime",
                        variable=self.var_time_field, command=self.mark_dirty).pack(side="left")

        ttk.Label(row1, text="    模式：").pack(side="left", padx=(18, 0))
        self.var_mode = tk.StringVar(value="on")
        mode_combo = ttk.Combobox(
            row1,
            textvariable=self.var_mode,
            values=["on", "before", "after", "between"],
            width=10,
            state="readonly",
        )
        mode_combo.pack(side="left", padx=(6, 0))
        mode_combo.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())

        ttk.Label(row1, text="（on=当天 / before=早于 / after=晚于含当天 / between=区间）").pack(side="left", padx=(10, 0))

        # 第2行：日期输入
        row2 = ttk.Frame(mid)
        row2.pack(fill="x", pady=(0, 8))
        ttk.Label(row2, text="开始日期：").pack(side="left")
        self.var_start_date = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        e1 = ttk.Entry(row2, textvariable=self.var_start_date, width=14)
        e1.pack(side="left", padx=(6, 14))
        e1.bind("<KeyRelease>", lambda e: self.mark_dirty())

        ttk.Label(row2, text="结束日期：").pack(side="left")
        self.var_end_date = tk.StringVar(value=(datetime.now().strftime("%Y-%m-%d")))
        self.ent_end = ttk.Entry(row2, textvariable=self.var_end_date, width=14)
        self.ent_end.pack(side="left", padx=(6, 10))
        self.ent_end.bind("<KeyRelease>", lambda e: self.mark_dirty())

        self.lbl_end_hint = ttk.Label(row2, text="（between 模式：不含结束日；其他模式会忽略结束日期）")
        self.lbl_end_hint.pack(side="left")

        # 第3行：include/exclude + 跳过 trash
        row3 = ttk.Frame(mid)
        row3.pack(fill="x", pady=(0, 8))
        ttk.Label(row3, text="只包含：").pack(side="left")
        self.var_include = tk.StringVar(value="")
        e_inc = ttk.Entry(row3, textvariable=self.var_include, width=28)
        e_inc.pack(side="left", padx=(6, 14))
        e_inc.bind("<KeyRelease>", lambda e: self.mark_dirty())
        ttk.Label(row3, text="例如：*.png,*.txt").pack(side="left")

        ttk.Label(row3, text="    排除：").pack(side="left", padx=(18, 0))
        self.var_exclude = tk.StringVar(value="")
        e_exc = ttk.Entry(row3, textvariable=self.var_exclude, width=28)
        e_exc.pack(side="left", padx=(6, 14))
        e_exc.bind("<KeyRelease>", lambda e: self.mark_dirty())
        ttk.Label(row3, text="例如：*.log,__pycache__*").pack(side="left")

        self.var_skip_trash = tk.BooleanVar(value=True)
        ttk.Checkbutton(row3, text="跳过 _trash_* 目录（推荐）",
                        variable=self.var_skip_trash, command=self.mark_dirty).pack(side="right")

        # 第4行：动作 + 按钮
        row4 = ttk.Frame(mid)
        row4.pack(fill="x")

        ttk.Label(row4, text="动作：").pack(side="left")
        self.var_action = tk.StringVar(value="trash")
        ttk.Radiobutton(row4, text="移入 _trash_*（可反悔）", value="trash",
                        variable=self.var_action, command=self.mark_dirty).pack(side="left", padx=(6, 10))
        ttk.Radiobutton(row4, text="永久删除（危险）", value="delete",
                        variable=self.var_action, command=self.mark_dirty).pack(side="left")

        self.btn_scan = ttk.Button(row4, text="① 扫描预览", command=self.on_scan)
        self.btn_scan.pack(side="right", padx=(6, 0))
        self.btn_exec = ttk.Button(row4, text="② 确认执行", command=self.on_execute, state="disabled")
        self.btn_exec.pack(side="right")

        # 分隔：预览区 + 日志区
        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 预览区
        preview = ttk.Labelframe(paned, text="预览列表（只显示前 N 条，避免卡死；但执行会处理全部命中项）", padding=8)
        paned.add(preview, weight=3)

        self.lbl_summary = ttk.Label(preview, text="还没扫描。")
        self.lbl_summary.pack(anchor="w", pady=(0, 8))

        cols = ("when", "size", "path")
        self.tree = ttk.Treeview(preview, columns=cols, show="headings", height=14)
        self.tree.heading("when", text="时间")
        self.tree.heading("size", text="大小")
        self.tree.heading("path", text="路径")
        self.tree.column("when", width=170, anchor="w")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("path", width=700, anchor="w")

        vsb = ttk.Scrollbar(preview, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # 日志区
        logs = ttk.Labelframe(paned, text="日志（执行完不会退出，你可以继续再跑一轮）", padding=8)
        paned.add(logs, weight=2)

        self.txt = tk.Text(logs, height=10, wrap="none")
        self.txt.pack(fill="both", expand=True)

        # 进度条 + 状态
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")

        self.pbar = ttk.Progressbar(bottom, mode="determinate")
        self.pbar.pack(side="left", fill="x", expand=True)

        self.var_status = tk.StringVar(value="就绪。")
        ttk.Label(bottom, textvariable=self.var_status).pack(side="left", padx=(10, 0))

        # 初始化 mode 控制
        self.on_mode_change(init=True)

    # ---------- 状态与日志 ----------

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt.insert("end", f"[{ts}] {msg}\n")
        self.txt.see("end")

    def set_status(self, msg: str):
        self.var_status.set(msg)

    def mark_dirty(self):
        self.dirty_after_scan = True
        self.btn_exec.config(state="disabled")

    def _signature(self) -> str:
        return "|".join([
            self.var_folder.get().strip(),
            self.var_time_field.get().strip(),
            self.var_mode.get().strip(),
            self.var_start_date.get().strip(),
            self.var_end_date.get().strip(),
            self.var_include.get().strip(),
            self.var_exclude.get().strip(),
            "skiptrash=" + str(self.var_skip_trash.get()),
            "action=" + self.var_action.get().strip(),
        ])

    # ---------- UI 事件 ----------

    def on_browse(self):
        folder = filedialog.askdirectory(title="选择要扫描的文件夹（会递归扫描所有子文件夹）")
        if folder:
            self.var_folder.set(folder)
            self.mark_dirty()

    def on_open_folder(self):
        p = self.var_folder.get().strip().strip('"').strip("'")
        if not p:
            return
        try:
            path = Path(p).expanduser().resolve()
            if not path.exists():
                messagebox.showwarning("提示", "路径不存在。")
                return
            # Windows 用 os.startfile，mac/linux 用 xdg-open/open
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore
            else:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, str(path)])
        except Exception as e:
            messagebox.showerror("错误", f"打开失败：{e}")

    def on_mode_change(self, init: bool = False):
        mode = self.var_mode.get()
        if mode == "between":
            self.ent_end.config(state="normal")
        else:
            self.ent_end.config(state="disabled")
        if not init:
            self.mark_dirty()

    def _read_inputs(self):
        folder = self.var_folder.get().strip().strip('"').strip("'")
        if not folder:
            raise ValueError("请先选择目标文件夹。")

        root = Path(folder).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("目标文件夹不存在或不是目录。")

        time_field = self.var_time_field.get().strip()
        mode = self.var_mode.get().strip()

        try:
            start_date = parse_ymd(self.var_start_date.get())
        except Exception:
            raise ValueError("开始日期格式不对，必须是 YYYY-MM-DD。")

        if mode == "between":
            try:
                end_date = parse_ymd(self.var_end_date.get())
            except Exception:
                raise ValueError("结束日期格式不对，必须是 YYYY-MM-DD。")
            start_dt = datetime.combine(start_date, time.min)
            end_dt = datetime.combine(end_date, time.min)
            if end_dt <= start_dt:
                raise ValueError("结束日期必须晚于开始日期（between 是 [开始, 结束)）。")
        else:
            start_dt, end_dt = day_range_local(start_date)

        includes = split_patterns(self.var_include.get())
        excludes = split_patterns(self.var_exclude.get())
        skip_trash = bool(self.var_skip_trash.get())

        action = self.var_action.get().strip()
        if action not in ("trash", "delete"):
            action = "trash"

        return root, time_field, mode, start_dt, end_dt, includes, excludes, skip_trash, action

    def on_scan(self):
        if self.scan_thread and self.scan_thread.is_alive():
            messagebox.showinfo("提示", "正在扫描中，请稍等。")
            return
        if self.exec_thread and self.exec_thread.is_alive():
            messagebox.showinfo("提示", "正在执行中，请稍等。")
            return

        try:
            root, time_field, mode, start_dt, end_dt, includes, excludes, skip_trash, _action = self._read_inputs()
        except Exception as e:
            messagebox.showerror("输入有问题", str(e))
            return

        self.log("开始扫描（递归子文件夹）……")
        self.set_status("扫描中……")
        self.pbar.config(mode="indeterminate")
        self.pbar.start(10)

        # 清空预览
        self.tree.delete(*self.tree.get_children())
        self.lbl_summary.config(text="扫描中……")

        max_preview = 1500  # UI最多展示条数（执行仍会处理全部）
        self.scan_thread = threading.Thread(
            target=worker_scan,
            daemon=True,
            args=(self.q, root, time_field, mode, start_dt, end_dt, includes, excludes, skip_trash, max_preview),
        )
        self.scan_thread.start()

    def on_execute(self):
        if self.exec_thread and self.exec_thread.is_alive():
            messagebox.showinfo("提示", "正在执行中，请稍等。")
            return
        if not self.hits:
            messagebox.showinfo("提示", "还没有命中项；请先扫描预览。")
            return

        # 如果扫描后改了参数，要求重新扫描（避免“你以为删A，实际删B”）
        sig = self._signature()
        if self.last_scan_signature != sig or self.dirty_after_scan:
            if not messagebox.askyesno("提醒", "你扫描后修改过参数。为了安全，请重新扫描预览。要现在重新扫描吗？"):
                return
            self.on_scan()
            return

        action = self.var_action.get().strip()

        if action == "delete":
            # 二次确认：输入 DELETE
            if not messagebox.askyesno("危险操作", "你选的是【永久删除】。确认继续？"):
                return
            token = simpledialog.askstring("最终确认", "请输入 DELETE（全大写）以继续：")
            if token != "DELETE":
                messagebox.showinfo("取消", "没输入 DELETE，已取消。")
                return
        else:
            if not messagebox.askyesno("确认执行", "将把命中文件移动到 _trash_* 目录。确认继续？"):
                return

        try:
            root, *_ = self._read_inputs()
        except Exception as e:
            messagebox.showerror("输入有问题", str(e))
            return

        self.log(f"开始执行：{action}（命中 {len(self.hits)} 个）……")
        self.set_status("执行中……")
        self.pbar.stop()
        self.pbar.config(mode="determinate", maximum=max(len(self.hits), 1), value=0)

        self.btn_scan.config(state="disabled")
        self.btn_exec.config(state="disabled")

        self.exec_thread = threading.Thread(
            target=worker_execute,
            daemon=True,
            args=(self.q, root, self.hits, action),
        )
        self.exec_thread.start()

    # ---------- 处理后台消息 ----------

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _handle_msg(self, msg):
        kind = msg[0]

        if kind == "scan_progress":
            scanned = msg[1]
            self.set_status(f"扫描中……已扫 {scanned} 个文件")

        elif kind == "scan_error":
            self.pbar.stop()
            self.pbar.config(mode="determinate", value=0)
            self.set_status("就绪。")
            self.log("扫描失败：" + msg[1])
            messagebox.showerror("扫描失败", msg[1])

        elif kind == "scan_done":
            hits, scanned_total, total_bytes, max_preview = msg[1], msg[2], msg[3], msg[4]
            self.pbar.stop()
            self.pbar.config(mode="determinate", value=0)
            self.set_status("扫描完成。")

            self.hits = hits
            self.dirty_after_scan = False
            self.last_scan_signature = self._signature()

            summary = f"扫描到文件：{scanned_total} | 命中：{len(hits)} | 总大小：{human_bytes(total_bytes)}"
            self.lbl_summary.config(text=summary)
            self.log(summary)

            # 填充预览（只显示前 max_preview 条）
            self.tree.delete(*self.tree.get_children())
            show = hits[:max_preview]
            for h in show:
                self.tree.insert("", "end", values=(
                    h.when.strftime("%Y-%m-%d %H:%M:%S"),
                    human_bytes(h.size),
                    str(h.path),
                ))
            if len(hits) > max_preview:
                self.tree.insert("", "end", values=("……", "……", f"（仅展示前 {max_preview} 条；实际会执行 {len(hits)} 条）"))

            # 是否允许执行
            if len(hits) > 0:
                self.btn_exec.config(state="normal")
            else:
                self.btn_exec.config(state="disabled")

        elif kind == "exec_progress":
            i, total = msg[1], msg[2]
            self.pbar.config(value=i)
            self.set_status(f"执行中…… {i}/{total}")

        elif kind == "exec_error":
            self.set_status("就绪。")
            self.log("执行失败：" + msg[1])
            messagebox.showerror("执行失败", msg[1])
            self.btn_scan.config(state="normal")
            # 执行失败后一般需要重新扫描
            self.mark_dirty()

        elif kind == "exec_done":
            ok, fail, trash_dir, errors = msg[1], msg[2], msg[3], msg[4]
            self.set_status("就绪。")
            self.btn_scan.config(state="normal")

            self.log(f"执行完成：成功 {ok}，失败 {fail}")
            if trash_dir:
                self.log(f"回收站：{trash_dir}")

            if errors:
                self.log("失败明细（最多20条）：")
                for e in errors:
                    self.log("  " + e)

            # 执行完：参数没变也不再允许直接“执行”，需要重新扫描（因为文件已被移动/删除）
            self.hits = []
            self.btn_exec.config(state="disabled")
            self.dirty_after_scan = True

            if fail == 0:
                if trash_dir:
                    messagebox.showinfo("完成", f"✅ 全部完成。\n已移动到：{trash_dir}\n\n窗口不会退出，你可以改参数继续下一轮。")
                else:
                    messagebox.showinfo("完成", "✅ 全部完成（永久删除）。\n\n窗口不会退出，你可以继续下一轮。")
            else:
                messagebox.showwarning("完成但有失败", f"完成：成功 {ok}，失败 {fail}。\n看日志里的失败原因（常见：权限/文件占用）。")

        else:
            # 未知消息
            pass


if __name__ == "__main__":
    import sys
    app = CleanerApp()
    app.mainloop()
