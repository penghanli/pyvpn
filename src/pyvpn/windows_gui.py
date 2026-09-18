"""Portable Windows desktop client for pyvpn."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import tkinter as tk
from tkinter import font, messagebox, ttk

from .auth import normalize_fingerprint
from .client import async_main as client_async_main
from .profiles import (
    ProfileError,
    ServerProfile,
    add_profile,
    load_profile_store,
    probe_latency_ms,
    remove_profile,
    select_profile,
)
from .windows_app import (
    WINDOWS_APP_VERSION,
    WindowsAppPaths,
    bundled_resource,
    configure_bundled_wintun,
    is_windows_admin,
    native_windows_architecture,
    process_is_running,
    protect_data_directory,
    read_pid,
    remove_pid_if_current,
    resolve_app_paths,
    tail_text,
    write_pid,
)


APP_TITLE = "pyvpn"
BG = "#f4f6f8"
SURFACE = "#ffffff"
TEXT = "#17212b"
MUTED = "#66727d"
ACCENT = "#087f73"
ACCENT_DARK = "#05665d"
DANGER = "#b42318"
WARNING = "#9a6700"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--server-id")
    parser.add_argument("--pid-file", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--error-log-file", type=Path)
    return parser


def _run_worker(args: argparse.Namespace) -> int:
    required = {
        "profiles": args.profiles,
        "server-id": args.server_id,
        "pid-file": args.pid_file,
        "stop-file": args.stop_file,
        "ready-file": args.ready_file,
        "log-file": args.log_file,
        "error-log-file": args.error_log_file,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        return 2

    args.log_file.parent.mkdir(parents=True, exist_ok=True)
    log_stream = args.log_file.open("a", encoding="utf-8", buffering=1)
    error_stream = args.error_log_file.open("a", encoding="utf-8", buffering=1)
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = log_stream
    sys.stderr = error_stream

    try:
        return _run_worker_with_logs(args)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        log_stream.close()
        error_stream.close()


def _run_worker_with_logs(args: argparse.Namespace) -> int:
    configure_bundled_wintun()
    pid = os.getpid()
    write_pid(args.pid_file, pid)
    try:
        args.ready_file.unlink()
    except OSError:
        pass

    client_args = [
        "--profiles",
        str(args.profiles),
        "--server-id",
        args.server_id,
        "--stop-file",
        str(args.stop_file),
        "--ready-file",
        str(args.ready_file),
    ]
    try:
        asyncio.run(client_async_main(client_args))
        return 0
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(str(exc), file=sys.stderr, flush=True)
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    finally:
        try:
            args.ready_file.unlink()
        except OSError:
            pass
        remove_pid_if_current(args.pid_file, pid)


def _set_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


class _SingleInstance:
    def __init__(self, key: str):
        self.handle = None
        self.already_running = False
        if os.name != "nt":
            return
        import ctypes

        name = "Local\\pyvpn-gui-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        self.handle = kernel32.CreateMutexW(None, False, name)
        self.already_running = bool(self.handle and kernel32.GetLastError() == 183)

    def close(self) -> None:
        if self.handle and os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle(self.handle)
            self.handle = None


class ProfileDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        existing: ServerProfile | None,
        suggested_id: str,
        make_active: bool,
    ):
        super().__init__(parent)
        self.result: tuple[ServerProfile, bool] | None = None
        self.existing = existing
        self.title("编辑节点" if existing else "添加节点")
        self.configure(background=SURFACE)
        self.resizable(False, False)
        self.transient(parent)

        self.server_id = tk.StringVar(value=existing.server_id if existing else suggested_id)
        self.server_host = tk.StringVar(value=existing.server_host if existing else "")
        self.control_port = tk.StringVar(
            value=str(existing.control_port if existing else 8443)
        )
        self.token = tk.StringVar()
        self.fingerprint = tk.StringVar(
            value=existing.cert_fingerprint if existing else "sha256:"
        )
        self.make_active = tk.BooleanVar(value=make_active)
        self.show_token = tk.BooleanVar(value=False)

        body = ttk.Frame(self, padding=(24, 22, 24, 12), style="Surface.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(1, weight=1)

        fields = (
            ("节点 ID", self.server_id),
            ("服务器地址", self.server_host),
            ("控制端口", self.control_port),
            ("共享 Token", self.token),
            ("证书 SHA-256", self.fingerprint),
        )
        self.entries: list[ttk.Entry] = []
        for row, (label, variable) in enumerate(fields):
            ttk.Label(body, text=label, style="Surface.TLabel").grid(
                row=row, column=0, sticky="w", padx=(0, 14), pady=7
            )
            entry = ttk.Entry(body, textvariable=variable, width=58)
            entry.grid(row=row, column=1, sticky="ew", pady=7)
            self.entries.append(entry)

        if existing:
            self.entries[0].state(["disabled"])
        self.entries[3].configure(show="*")
        token_hint = "留空则保留原 Token" if existing else "Token 仅保存在本机节点文件中"
        ttk.Label(body, text=token_hint, style="Hint.TLabel").grid(
            row=5, column=1, sticky="w", pady=(0, 5)
        )
        ttk.Checkbutton(
            body,
            text="显示 Token",
            variable=self.show_token,
            command=self._toggle_token,
        ).grid(row=6, column=1, sticky="w", pady=(2, 4))
        ttk.Checkbutton(
            body,
            text="保存后设为当前节点",
            variable=self.make_active,
        ).grid(row=7, column=1, sticky="w", pady=(2, 10))

        footer = ttk.Frame(self, padding=(24, 12, 24, 20), style="Surface.TFrame")
        footer.grid(row=1, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Button(footer, text="取消", command=self.destroy).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(footer, text="保存", style="Accent.TButton", command=self._save).grid(
            row=0, column=2
        )

        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()
        self.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 3)
        self.geometry(f"+{x}+{y}")
        self.entries[1 if existing else 0].focus_set()

    def _toggle_token(self) -> None:
        self.entries[3].configure(show="" if self.show_token.get() else "*")

    def _save(self) -> None:
        try:
            port = int(self.control_port.get().strip())
            token = self.token.get()
            if self.existing is not None and not token.strip():
                token = self.existing.token
            profile = ServerProfile(
                server_id=self.server_id.get().strip(),
                server_host=self.server_host.get().strip(),
                control_port=port,
                token=token,
                cert_fingerprint=normalize_fingerprint(self.fingerprint.get()),
                tun_name=self.existing.tun_name if self.existing else "pyvpn0",
                mtu=self.existing.mtu if self.existing else 1280,
                no_dns=self.existing.no_dns if self.existing else False,
                bypass_ips=self.existing.bypass_ips if self.existing else (),
            )
        except (ProfileError, ValueError) as exc:
            messagebox.showerror("节点信息无效", str(exc), parent=self)
            return
        self.result = (profile, self.make_active.get())
        self.destroy()


class PyVpnWindowsApp:
    def __init__(self, root: tk.Tk, paths: WindowsAppPaths, instance: _SingleInstance):
        self.root = root
        self.paths = paths
        self.instance = instance
        self.latencies: dict[str, float | None | str] = {}
        self.child: subprocess.Popen[bytes] | None = None
        self.connection_state = "disconnected"
        self.connected_server_id: str | None = None
        self.expected_stop = False
        self.pending_reconnect = False
        self.close_after_stop = False
        self.last_running = False
        self.failure_reported_for: int | None = None

        self.root.title(f"{APP_TITLE} - Windows 客户端")
        self.root.geometry("880x590")
        self.root.minsize(760, 500)
        self.root.configure(background=BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._configure_styles()
        self._build_ui()
        self._refresh_profiles()
        self._refresh_process_state()
        self.root.after(500, self._poll_process)

        if not self.paths.profiles.exists():
            self.root.after(250, self.add_node)

    def _configure_styles(self) -> None:
        default_font = font.nametofont("TkDefaultFont")
        default_font.configure(family="Microsoft YaHei UI", size=10)
        font.nametofont("TkTextFont").configure(family="Microsoft YaHei UI", size=10)
        font.nametofont("TkHeadingFont").configure(
            family="Microsoft YaHei UI", size=10, weight="bold"
        )
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("App.TFrame", background=BG)
        style.configure("Surface.TFrame", background=SURFACE)
        style.configure("App.TLabel", background=BG, foreground=TEXT)
        style.configure("Surface.TLabel", background=SURFACE, foreground=TEXT)
        style.configure(
            "Hint.TLabel",
            background=SURFACE,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Header.TLabel",
            background=BG,
            foreground=TEXT,
            font=("Segoe UI", 25, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=BG,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 10),
        )
        style.configure("Treeview", rowheight=34, borderwidth=0, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TButton", foreground=ACCENT, padding=(18, 9))
        style.configure("Danger.TButton", foreground=DANGER)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(26, 20, 26, 16), style="App.TFrame")
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        header = ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="pyvpn", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Windows 客户端", style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        self.status_label = tk.Label(
            header,
            text="未连接",
            background=BG,
            foreground=MUTED,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.status_label.grid(row=0, column=1, rowspan=2, sticky="e", padx=(18, 12))
        ttk.Button(header, text="关于", command=self._show_about).grid(
            row=0, column=2, rowspan=2, sticky="e"
        )

        toolbar = ttk.Frame(outer, style="App.TFrame")
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.add_button = ttk.Button(toolbar, text="添加", command=self.add_node)
        self.add_button.pack(side="left")
        self.edit_button = ttk.Button(toolbar, text="编辑", command=self.edit_node)
        self.edit_button.pack(side="left", padx=(8, 0))
        self.delete_button = ttk.Button(
            toolbar,
            text="删除",
            style="Danger.TButton",
            command=self.delete_node,
        )
        self.delete_button.pack(side="left", padx=(8, 0))
        self.switch_button = ttk.Button(toolbar, text="设为当前", command=self.switch_node)
        self.switch_button.pack(side="left", padx=(8, 0))
        self.speed_button = ttk.Button(toolbar, text="测速", command=self.test_all_latency)
        self.speed_button.pack(side="right")

        table_frame = ttk.Frame(outer, style="Surface.TFrame", padding=1)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame,
            columns=("active", "server_id", "endpoint", "latency"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("active", text="状态")
        self.tree.heading("server_id", text="节点 ID")
        self.tree.heading("endpoint", text="服务器")
        self.tree.heading("latency", text="控制延迟")
        self.tree.column("active", width=80, minwidth=70, anchor="center", stretch=False)
        self.tree.column("server_id", width=180, minwidth=130)
        self.tree.column("endpoint", width=360, minwidth=220)
        self.tree.column("latency", width=130, minwidth=110, anchor="center", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_controls())
        self.tree.bind("<Double-1>", lambda _event: self.switch_node())

        connection = ttk.Frame(outer, style="Surface.TFrame", padding=(18, 15))
        connection.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        connection.columnconfigure(0, weight=1)
        self.active_title = ttk.Label(connection, text="当前节点：未设置", style="Surface.TLabel")
        self.active_title.grid(row=0, column=0, sticky="w")
        self.active_endpoint = ttk.Label(connection, text="请先添加节点", style="Hint.TLabel")
        self.active_endpoint.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.connect_button = tk.Button(
            connection,
            text="连接",
            command=self.toggle_connection,
            background=ACCENT,
            foreground="#ffffff",
            activebackground=ACCENT_DARK,
            activeforeground="#ffffff",
            disabledforeground="#d9e6e4",
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=34,
            pady=10,
        )
        self.connect_button.grid(row=0, column=1, rowspan=2, sticky="e", padx=(22, 0))

        self.footer_text = tk.StringVar(value="")
        ttk.Label(outer, textvariable=self.footer_text, style="Subtitle.TLabel").grid(
            row=4, column=0, sticky="ew", pady=(10, 0)
        )

    def _load_store(self):
        return load_profile_store(self.paths.profiles, allow_missing=True)

    def _selected_server_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def _refresh_profiles(self, *, select_id: str | None = None) -> None:
        previous = select_id or self._selected_server_id()
        try:
            store = self._load_store()
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return

        for item in self.tree.get_children():
            self.tree.delete(item)
        for server_id in sorted(store.servers):
            profile = store.servers[server_id]
            latency = self.latencies.get(server_id, "未测试")
            if latency is None:
                latency_text = "不可达"
            elif isinstance(latency, float):
                latency_text = f"{latency:.1f} ms"
            else:
                latency_text = str(latency)
            self.tree.insert(
                "",
                "end",
                iid=server_id,
                values=(
                    "当前" if server_id == store.active_server_id else "",
                    server_id,
                    f"{profile.server_host}:{profile.control_port}",
                    latency_text,
                ),
            )
        target = previous if previous in store.servers else store.active_server_id
        if target and self.tree.exists(target):
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)

        if store.active_server_id:
            profile = store.servers[store.active_server_id]
            self.active_title.configure(text=f"当前节点：{profile.server_id}")
            self.active_endpoint.configure(text=f"{profile.server_host}:{profile.control_port}")
        else:
            self.active_title.configure(text="当前节点：未设置")
            self.active_endpoint.configure(text="请先添加节点")
        profile_text = str(self.paths.profiles)
        if len(profile_text) > 68:
            profile_text = f"...\\{self.paths.profiles.parent.name}\\{self.paths.profiles.name}"
        self.footer_text.set(f"节点文件：{profile_text}    |    版本 {WINDOWS_APP_VERSION}")
        self._update_controls()

    def _update_controls(self) -> None:
        selected = self._selected_server_id()
        state = "normal" if selected else "disabled"
        self.edit_button.configure(state=state)
        self.delete_button.configure(state=state)
        self.switch_button.configure(state=state)
        try:
            has_servers = bool(self._load_store().servers)
        except ProfileError:
            has_servers = False
        self.speed_button.configure(state="normal" if has_servers else "disabled")
        if self.connection_state in {"connecting", "disconnecting"}:
            self.connect_button.configure(state="disabled")
        else:
            self.connect_button.configure(state="normal" if has_servers else "disabled")

    def _suggested_id(self, store) -> str:
        if not store.servers:
            return "default"
        index = 2
        while f"node-{index}" in store.servers:
            index += 1
        return f"node-{index}"

    def add_node(self) -> None:
        try:
            store = self._load_store()
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return
        old_active = store.active_server_id
        was_running = bool(self._running_pid())
        dialog = ProfileDialog(
            self.root,
            existing=None,
            suggested_id=self._suggested_id(store),
            make_active=not store.servers,
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        profile, make_active = dialog.result
        if profile.server_id in store.servers:
            messagebox.showerror("节点已存在", f"节点 ID 已存在：{profile.server_id}", parent=self.root)
            return
        try:
            self.paths.data_dir.mkdir(parents=True, exist_ok=True)
            if self.paths.data_dir.name == "pyvpn-data":
                protect_data_directory(self.paths.data_dir)
            add_profile(self.paths.profiles, profile, make_active=make_active)
        except (OSError, ProfileError) as exc:
            messagebox.showerror("无法保存节点", str(exc), parent=self.root)
            return
        self.latencies.pop(profile.server_id, None)
        self._refresh_profiles(select_id=profile.server_id)
        if make_active and was_running and old_active != profile.server_id:
            self.pending_reconnect = True
            self._request_disconnect()

    def edit_node(self) -> None:
        server_id = self._selected_server_id()
        if not server_id:
            return
        try:
            store = self._load_store()
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return
        if self._running_pid() and server_id == store.active_server_id:
            messagebox.showinfo("请先断开", "当前连接使用此节点，请先断开 VPN 再编辑。", parent=self.root)
            return
        old_active = store.active_server_id
        was_running = bool(self._running_pid())
        existing = store.servers[server_id]
        dialog = ProfileDialog(
            self.root,
            existing=existing,
            suggested_id=server_id,
            make_active=server_id == store.active_server_id,
        )
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        profile, make_active = dialog.result
        try:
            add_profile(
                self.paths.profiles,
                profile,
                replace=True,
                make_active=make_active,
            )
        except (OSError, ProfileError) as exc:
            messagebox.showerror("无法保存节点", str(exc), parent=self.root)
            return
        self.latencies.pop(server_id, None)
        self._refresh_profiles(select_id=server_id)
        if make_active and was_running and old_active != server_id:
            self.pending_reconnect = True
            self._request_disconnect()

    def delete_node(self) -> None:
        server_id = self._selected_server_id()
        if not server_id:
            return
        try:
            store = self._load_store()
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return
        if self._running_pid() and server_id == store.active_server_id:
            messagebox.showinfo("请先断开", "当前连接使用此节点，请先断开 VPN 再删除。", parent=self.root)
            return
        if not messagebox.askyesno("删除节点", f"确定删除节点 {server_id}？", parent=self.root):
            return
        try:
            remove_profile(self.paths.profiles, server_id)
        except (OSError, ProfileError) as exc:
            messagebox.showerror("无法删除节点", str(exc), parent=self.root)
            return
        self.latencies.pop(server_id, None)
        self._refresh_profiles()

    def switch_node(self) -> None:
        server_id = self._selected_server_id()
        if not server_id:
            return
        try:
            store = self._load_store()
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return
        if server_id == store.active_server_id:
            return
        try:
            select_profile(self.paths.profiles, server_id)
        except (OSError, ProfileError) as exc:
            messagebox.showerror("无法切换节点", str(exc), parent=self.root)
            return
        self._refresh_profiles(select_id=server_id)
        if self._running_pid():
            self.pending_reconnect = True
            self._request_disconnect()
        else:
            self.status_label.configure(text=f"已切换到 {server_id}", foreground=ACCENT)

    def test_all_latency(self) -> None:
        try:
            profiles = list(self._load_store().servers.values())
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return
        if not profiles:
            return
        for profile in profiles:
            self.latencies[profile.server_id] = "测试中..."
        self._refresh_profiles()
        self.speed_button.configure(state="disabled")
        self.status_label.configure(text="正在测试控制端口延迟...", foreground=WARNING)

        def work() -> dict[str, float | None]:
            workers = min(8, len(profiles))
            results: dict[str, float | None] = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        probe_latency_ms,
                        profile.server_host,
                        profile.control_port,
                        2.0,
                    ): profile.server_id
                    for profile in profiles
                }
                for future in as_completed(futures):
                    results[futures[future]] = future.result()
            return results

        def finish(results: dict[str, float | None]) -> None:
            self.latencies.update(results)
            self._refresh_profiles()
            self._refresh_process_state()

        def runner() -> None:
            results = work()
            try:
                self.root.after(0, finish, results)
            except tk.TclError:
                pass

        threading.Thread(target=runner, name="pyvpn-latency", daemon=True).start()

    def _worker_command(self, server_id: str) -> list[str]:
        if getattr(sys, "frozen", False):
            command = [sys.executable]
        else:
            command = [sys.executable, str(Path(sys.argv[0]).resolve())]
        command.extend(
            [
                "--worker",
                "--profiles",
                str(self.paths.profiles),
                "--server-id",
                server_id,
                "--pid-file",
                str(self.paths.pid),
                "--stop-file",
                str(self.paths.stop),
                "--ready-file",
                str(self.paths.ready),
                "--log-file",
                str(self.paths.log),
                "--error-log-file",
                str(self.paths.error_log),
            ]
        )
        return command

    def _running_pid(self) -> int | None:
        pid = read_pid(self.paths.pid)
        if pid and process_is_running(pid):
            return pid
        if self.child is not None and self.child.poll() is None:
            return self.child.pid
        if pid:
            try:
                self.paths.pid.unlink()
            except OSError:
                pass
        return None

    def toggle_connection(self) -> None:
        if self._running_pid():
            self._request_disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        try:
            store = self._load_store()
        except ProfileError as exc:
            messagebox.showerror("节点文件错误", str(exc), parent=self.root)
            return
        server_id = store.active_server_id
        if not server_id:
            messagebox.showinfo("没有当前节点", "请先添加节点并设为当前节点。", parent=self.root)
            return
        if self._running_pid():
            return
        self.paths.data_dir.mkdir(parents=True, exist_ok=True)
        for stale in (self.paths.stop, self.paths.ready, self.paths.pid):
            try:
                stale.unlink()
            except OSError:
                pass
        try:
            self.paths.log.write_text("", encoding="utf-8")
            self.paths.error_log.write_text("", encoding="utf-8")
            self.child = subprocess.Popen(
                self._worker_command(server_id),
                cwd=self.paths.executable_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            messagebox.showerror("无法启动", str(exc), parent=self.root)
            return
        self.connected_server_id = server_id
        self.expected_stop = False
        self.failure_reported_for = None
        self.connection_state = "connecting"
        self.last_running = True
        self._refresh_process_state()

    def _request_disconnect(self) -> None:
        if not self._running_pid():
            self._refresh_process_state()
            return
        try:
            self.paths.stop.write_text("stop\n", encoding="ascii")
        except OSError as exc:
            messagebox.showerror("无法断开", str(exc), parent=self.root)
            return
        self.expected_stop = True
        self.connection_state = "disconnecting"
        self._refresh_process_state()

    def _poll_process(self) -> None:
        running_pid = self._running_pid()
        was_running = self.last_running
        self.last_running = running_pid is not None

        if running_pid:
            if self.connection_state == "disconnecting" or self.expected_stop:
                self.connection_state = "disconnecting"
            elif self.paths.ready.is_file() or "VPN tunnel is running" in tail_text(
                self.paths.log, max_bytes=4096
            ):
                self.connection_state = "connected"
            else:
                self.connection_state = "connecting"
        else:
            previous_state = self.connection_state
            self.connection_state = "disconnected"
            try:
                self.paths.ready.unlink()
            except OSError:
                pass
            if self.pending_reconnect:
                self.pending_reconnect = False
                self.expected_stop = False
                self.root.after(350, self._connect)
            elif self.close_after_stop:
                self._destroy()
                return
            elif (
                was_running
                and not self.expected_stop
                and previous_state in {"connecting", "connected"}
            ):
                self._show_worker_failure()
            self.expected_stop = False
        self._refresh_process_state()
        self.root.after(500, self._poll_process)

    def _refresh_process_state(self) -> None:
        state = self.connection_state
        server = self.connected_server_id or ""
        if state == "connected":
            label = f"已连接 {server}" if server else "已连接"
            self.status_label.configure(text=label, foreground=ACCENT)
            self.connect_button.configure(text="断开", state="normal")
        elif state == "connecting":
            label = f"正在连接 {server}..." if server else "正在连接..."
            self.status_label.configure(text=label, foreground=WARNING)
            self.connect_button.configure(text="连接中...", state="disabled")
        elif state == "disconnecting":
            self.status_label.configure(text="正在断开...", foreground=WARNING)
            self.connect_button.configure(text="断开中...", state="disabled")
        else:
            self.status_label.configure(text="未连接", foreground=MUTED)
            self.connect_button.configure(text="连接")
        self._update_controls()

    def _show_worker_failure(self) -> None:
        pid = self.child.pid if self.child is not None else None
        if pid is not None and self.failure_reported_for == pid:
            return
        self.failure_reported_for = pid
        error_text = tail_text(self.paths.error_log)
        log_text = tail_text(self.paths.log)
        detail = error_text or log_text or "连接进程已退出，请检查服务器地址、Token 和证书指纹。"
        if len(detail) > 3500:
            detail = detail[-3500:]
        messagebox.showerror("VPN 连接失败", detail, parent=self.root)

    def _show_about(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("关于 pyvpn")
        dialog.geometry("650x470")
        dialog.minsize(520, 360)
        dialog.transient(self.root)
        dialog.configure(background=SURFACE)
        frame = ttk.Frame(dialog, padding=20, style="Surface.TFrame")
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=f"pyvpn {WINDOWS_APP_VERSION}",
            style="Surface.TLabel",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="单文件 Windows x64 客户端。测速为 TCP 控制端口往返建立时间，不代表下载带宽。",
            style="Hint.TLabel",
            wraplength=590,
        ).pack(anchor="w", pady=(6, 12))
        text = tk.Text(frame, wrap="word", relief="solid", borderwidth=1, font=("Consolas", 9))
        text.pack(fill="both", expand=True)
        notices = []
        for relative in (
            "THIRD_PARTY_NOTICES.txt",
            "licenses/LICENSE.txt",
            "licenses/WINTUN-LICENSE.txt",
            "windows_gui/THIRD_PARTY_NOTICES.txt",
        ):
            path = bundled_resource(relative)
            if path.is_file():
                notices.append(path.read_text(encoding="utf-8", errors="replace"))
        notice_text = "\n\n".join(dict.fromkeys(notices))
        text.insert(
            "1.0",
            notice_text or "Third-party notices are unavailable in this development run.",
        )
        text.configure(state="disabled")
        ttk.Button(frame, text="关闭", command=dialog.destroy).pack(anchor="e", pady=(12, 0))

    def _on_close(self) -> None:
        if self._running_pid():
            if not messagebox.askyesno("退出 pyvpn", "VPN 仍在连接。断开 VPN 并退出？", parent=self.root):
                return
            self.close_after_stop = True
            self._request_disconnect()
            return
        self._destroy()

    def _destroy(self) -> None:
        self.instance.close()
        self.root.destroy()


def _smoke_test() -> int:
    _set_dpi_awareness()
    with tempfile.TemporaryDirectory(prefix="pyvpn-windows-gui-") as temporary:
        app_root = Path(temporary)
        paths = resolve_app_paths(
            app_root,
            environment={"PYVPN_GUI_DATA_DIR": str(app_root / "data")},
        )
        add_profile(
            paths.profiles,
            ServerProfile(
                server_id="smoke-test",
                server_host="127.0.0.1",
                control_port=8443,
                token="smoke-test-token",
                cert_fingerprint="sha256:" + "a" * 64,
            ),
            make_active=True,
        )
        root = tk.Tk()
        root.withdraw()
        instance = _SingleInstance(str(paths.data_dir).lower())
        app = PyVpnWindowsApp(root, paths, instance)
        root.update_idletasks()
        if app.tree.get_children() != ("smoke-test",):
            raise RuntimeError("Windows GUI did not render the smoke-test profile")
        if os.environ.get("PYVPN_GUI_PREVIEW") == "1":
            root.deiconify()
            root.after(8000, app._destroy)
            root.mainloop()
        else:
            app._destroy()
    if sys.stdout is not None:
        print("Windows GUI smoke test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.worker:
        return _run_worker(args)
    if args.smoke_test:
        return _smoke_test()
    if os.name != "nt":
        raise SystemExit("The pyvpn desktop client requires Windows 10 or Windows 11.")

    _set_dpi_awareness()
    executable_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(sys.argv[0]).resolve().parent
    )
    paths = resolve_app_paths(executable_dir)
    instance = _SingleInstance(str(paths.data_dir).lower())
    root = tk.Tk()
    if instance.already_running:
        root.withdraw()
        messagebox.showinfo("pyvpn", "pyvpn 已经在运行。", parent=root)
        instance.close()
        root.destroy()
        return 0
    native_arch = native_windows_architecture()
    if native_arch not in {"amd64", "x86_64"}:
        root.withdraw()
        messagebox.showerror(
            "不支持的 Windows 架构",
            f"此版本仅支持 Windows x64 (AMD64)，当前系统架构为 {native_arch}。",
            parent=root,
        )
        instance.close()
        root.destroy()
        return 1
    if not is_windows_admin():
        root.withdraw()
        messagebox.showerror("需要管理员权限", "请右键 pyvpn.exe，选择“以管理员身份运行”。", parent=root)
        instance.close()
        root.destroy()
        return 1
    configure_bundled_wintun()
    PyVpnWindowsApp(root, paths, instance)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
