from __future__ import annotations

import argparse
import ctypes
import os
import signal
import sys
import threading
import time
import webbrowser
from typing import Optional

import uvicorn

from vrctool_app import __version__
from vrctool_app.config_store import get_configured_web_port, set_configured_web_port
from vrctool_app.installation import InstallationError, launch_uninstaller
from vrctool_app.lifecycle import set_shutdown_callback
from vrctool_app.network import is_tcp_port_available
from vrctool_app.single_instance import SingleInstanceGuard, read_running_instance
from vrctool_app.state import RuntimeState
from vrctool_app.update_manager import UpdateError, UpdateManager

CTRL_CLOSE_EVENT = 2
CTRL_LOGOFF_EVENT = 5
CTRL_SHUTDOWN_EVENT = 6
WINDOWS_CTRL_EVENTS = {0, 1, CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT}

server: Optional[uvicorn.Server] = None
shutdown_started = threading.Event()
console_handler_ref = None


def request_server_stop(reason: str) -> None:
    global server
    if shutdown_started.is_set():
        return
    shutdown_started.set()
    print(f"\n正在关闭后端服务：{reason}")
    if server is not None:
        server.should_exit = True


def install_signal_handlers() -> None:
    def handle_signal(signum, _frame) -> None:
        request_server_stop(f"收到系统信号 {signum}")

    for item in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if item is not None:
            try:
                signal.signal(item, handle_signal)
            except (OSError, ValueError):
                pass

    if os.name != "nt":
        return

    handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    @handler_type
    def console_handler(ctrl_type: int) -> bool:
        if ctrl_type not in WINDOWS_CTRL_EVENTS:
            return False
        request_server_stop(f"控制台关闭事件 {ctrl_type}")
        deadline = time.time() + 4
        while time.time() < deadline:
            time.sleep(0.1)
        return True

    global console_handler_ref
    console_handler_ref = console_handler
    ctypes.windll.kernel32.SetConsoleCtrlHandler(console_handler_ref, True)


def valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口号必须是整数") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口号必须在 1 到 65535 之间")
    return port


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    aliases = {
        "-v": "version",
        "--version": "version",
        "-u": "upgrade",
        "--upgrade": "upgrade",
        "-p": "setport",
        "--port": "setport",
    }
    if not raw_args:
        raw_args = ["start"]
    elif raw_args[0] in aliases:
        raw_args[0] = aliases[raw_args[0]]
    elif raw_args[0].startswith("-") and raw_args[0] not in {"-h", "--help"}:
        raw_args.insert(0, "start")

    parser = argparse.ArgumentParser(description="vrctool 网页控制台启动器")
    commands = parser.add_subparsers(dest="command", required=True)

    start_parser = commands.add_parser("start", help="启动应用")
    start_parser.add_argument("--host", default="127.0.0.1", help="网页服务监听地址")
    start_parser.add_argument(
        "-p",
        "--port",
        default=None,
        type=valid_port,
        help="仅本次启动使用的网页端口，不写入配置",
    )
    start_parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")

    commands.add_parser("version", help="显示版本号")
    setport_parser = commands.add_parser("setport", help="设置默认网页端口，不启动应用")
    setport_parser.add_argument("port", type=valid_port, help="下次启动使用的网页端口")
    upgrade_parser = commands.add_parser("upgrade", help="检查并安装新版本")
    upgrade_parser.add_argument("--check", action="store_true", help="只检查更新")
    uninstall_parser = commands.add_parser("uninstall", help="卸载应用")
    uninstall_parser.add_argument("--silent", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(raw_args)


def run_upgrade(check_only: bool = False) -> int:
    manager = UpdateManager(RuntimeState())
    snapshot = manager.check_for_updates()
    update = snapshot.get("update", {})
    if update.get("status") == "error":
        print(f"检查更新失败：{update.get('error') or '未知错误'}")
        return 1
    current = update.get("current_version") or __version__
    latest = update.get("latest_version") or current
    if not update.get("available"):
        print(f"当前已是最新版本：v{current}")
        return 0
    print(f"发现新版本：v{latest}")
    if check_only:
        print(update.get("release_url") or "")
        return 0
    if not manager.can_install:
        print("自动安装仅在 Windows 安装版中可用。")
        return 1
    try:
        print("正在下载安装包并校验 SHA-256...")
        manager.download_update_blocking()
        manager.install_update()
    except UpdateError as exc:
        print(f"更新失败：{exc}")
        return 1
    print("安装包已校验，更新程序即将启动。")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    global server
    args = parse_args(argv)
    if args.command == "version":
        print(f"vrctool {__version__}")
        return 0
    if args.command == "setport":
        running = read_running_instance() or {}
        running_port = int(running.get("port") or 0)
        if running_port != args.port and not is_tcp_port_available("127.0.0.1", args.port):
            print(f"端口 {args.port} 已被其他程序占用，默认网页端口未修改。")
            return 1
        port = set_configured_web_port(args.port)
        print(f"默认网页端口已设置为 {port}，将在下次启动时生效。")
        return 0
    if args.command == "upgrade":
        return run_upgrade(check_only=args.check)
    if args.command == "uninstall":
        try:
            uninstaller = launch_uninstaller(silent=args.silent)
        except InstallationError as exc:
            print(f"无法卸载 vrctool：{exc}")
            return 1
        print(f"卸载程序已启动：{uninstaller}")
        return 0

    configured_port = get_configured_web_port()
    web_port = args.port if args.port is not None else configured_port
    temporary_port = args.port is not None
    url = f"http://{args.host}:{web_port}"
    instance_guard = SingleInstanceGuard()

    if not instance_guard.acquire():
        running = read_running_instance() or {}
        running_url = running.get("url") or url
        print("vrctool 已经在运行，为了避免组件冲突，本次启动已取消。")
        print(f"已运行网页地址：{running_url}")
        if not args.no_browser:
            webbrowser.open(str(running_url))
        time.sleep(3)
        return 0

    if not is_tcp_port_available(args.host, web_port):
        print(f"网页端口 {web_port} 已被其他程序占用，vrctool 未启动。")
        print(f"可使用 vrctool -p <新端口> 修改默认端口，或使用 vrctool start -p <新端口> 临时启动。")
        instance_guard.close()
        return 1

    instance_guard.write_instance(args.host, web_port)
    os.environ["VRCTOOL_WEB_HOST"] = args.host
    os.environ["VRCTOOL_WEB_PORT"] = str(web_port)
    os.environ["VRCTOOL_WEB_PORT_TEMPORARY"] = "1" if temporary_port else "0"

    from vrctool_app.server import app as asgi_app

    config = uvicorn.Config(
        asgi_app,
        host=args.host,
        port=web_port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    set_shutdown_callback(lambda: request_server_stop("网页请求关闭"))
    install_signal_handlers()

    print("vrctool 正在启动")
    print(f"网页地址：{url}")
    print("关闭方式：在这个窗口按 Ctrl+C，或直接关闭这个窗口，后端会一起退出。")

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()

    try:
        server.run()
    finally:
        set_shutdown_callback(None)
        server = None
        instance_guard.close()
        print("后端服务已关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
