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

from vrctool_app.lifecycle import set_shutdown_callback
from vrctool_app.server import app as asgi_app

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="vrctool 网页控制台启动器")
    parser.add_argument("--host", default="127.0.0.1", help="网页服务监听地址")
    parser.add_argument("--port", default=8765, type=int, help="网页服务端口")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    return parser.parse_args()


def main() -> int:
    global server
    args = parse_args()
    url = f"http://{args.host}:{args.port}"

    config = uvicorn.Config(
        asgi_app,
        host=args.host,
        port=args.port,
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
        print("后端服务已关闭。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
