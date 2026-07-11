from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from vrctool_app import __version__
from vrctool_app.config_store import app_data_root


REPOSITORY = "danglong0313/vrctool"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_INSTALLER_SIZE = 500 * 1024 * 1024
ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class UpdateError(RuntimeError):
    pass


def extract_version(value: str) -> Version:
    match = re.search(r"\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?", value or "")
    if not match:
        raise UpdateError(f"无法识别版本号：{value or '-'}")
    try:
        return Version(match.group(0))
    except InvalidVersion as exc:
        raise UpdateError(f"版本号格式无效：{value}") from exc


def select_installer_asset(release: Dict[str, Any]) -> Dict[str, Any]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub Release 中没有可用资产")
    installers = [
        item
        for item in assets
        if isinstance(item, dict)
        and str(item.get("name", "")).lower().endswith(".exe")
        and "setup" in str(item.get("name", "")).lower()
    ]
    if not installers:
        raise UpdateError("新版本未提供 vrctool 安装包")
    installers.sort(
        key=lambda item: (
            "vrctool" not in str(item.get("name", "")).lower(),
            str(item.get("name", "")).lower(),
        )
    )
    return installers[0]


def normalize_sha256(value: str) -> str:
    digest = (value or "").strip().lower()
    if digest.startswith("sha256:"):
        digest = digest.split(":", 1)[1]
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise UpdateError("安装包缺少有效的 SHA-256 摘要")
    return digest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_helper_path() -> Path:
    return app_data_root() / f"update-helper-{os.getpid()}.ps1"


class UpdateManager:
    def __init__(self, state) -> None:
        self.state = state
        self.can_install = os.name == "nt" and bool(getattr(sys, "frozen", False))
        self._operation_lock = threading.Lock()
        self._download_thread: Optional[threading.Thread] = None
        self.state.patch("update", can_install=self.can_install)

    def check_for_updates(self) -> Dict[str, Any]:
        with self._operation_lock:
            update = self.state.snapshot().get("update", {})
            if update.get("status") in {"downloading", "installing"}:
                return self.state.snapshot()
            self.state.patch(
                "update",
                status="checking",
                error="",
                available=False,
                progress=0,
                downloaded_bytes=0,
                installer_path="",
            )
            try:
                release = self._fetch_json(LATEST_RELEASE_URL)
                tag_name = str(release.get("tag_name", ""))
                latest = extract_version(tag_name)
                current = extract_version(__version__)
                available = latest > current
                values: Dict[str, Any] = {
                    "current_version": str(current),
                    "latest_version": str(latest),
                    "available": available,
                    "release_name": str(release.get("name") or tag_name),
                    "release_notes": str(release.get("body") or "")[:12000],
                    "release_url": str(release.get("html_url") or ""),
                    "asset_name": "",
                    "asset_size": 0,
                    "download_url": "",
                    "digest": "",
                    "error": "",
                    "status": "up_to_date",
                }
                if available:
                    asset = select_installer_asset(release)
                    size = int(asset.get("size") or 0)
                    if size <= 0 or size > MAX_INSTALLER_SIZE:
                        raise UpdateError("安装包大小异常")
                    values.update(
                        status="available",
                        asset_name=Path(str(asset.get("name", ""))).name,
                        asset_size=size,
                        download_url=str(asset.get("browser_download_url") or ""),
                        digest=normalize_sha256(str(asset.get("digest") or "")),
                    )
                    self.state.log("ok", f"发现新版本 {latest}")
                else:
                    self.state.log("ok", f"当前已是最新版本 {current}")
                self.state.patch("update", **values)
            except Exception as exc:
                message = self._friendly_error(exc)
                self.state.patch("update", status="error", available=False, error=message)
                self.state.log("warn", f"检查更新失败：{message}")
            return self.state.snapshot()

    def start_download(self) -> Dict[str, Any]:
        with self._operation_lock:
            update = self.state.snapshot().get("update", {})
            if self._download_thread and self._download_thread.is_alive():
                return self.state.snapshot()
            if update.get("status") != "available":
                raise UpdateError("当前没有可下载的新版本")
            if not self.can_install:
                raise UpdateError("自动安装仅在 Windows 安装版中可用")
            self.state.patch(
                "update",
                status="downloading",
                progress=0,
                downloaded_bytes=0,
                installer_path="",
                error="",
            )
            self._download_thread = threading.Thread(
                target=self._download_worker,
                name="vrctool-update-download",
                daemon=True,
            )
            self._download_thread.start()
            return self.state.snapshot()

    def install_update(self) -> Dict[str, Any]:
        with self._operation_lock:
            update = self.state.snapshot().get("update", {})
            if not self.can_install:
                raise UpdateError("自动安装仅在 Windows 安装版中可用")
            if update.get("status") != "ready":
                raise UpdateError("安装包尚未下载完成")
            installer = Path(str(update.get("installer_path") or ""))
            if not installer.is_file():
                raise UpdateError("找不到已下载的安装包")
            expected = normalize_sha256(str(update.get("digest") or ""))
            if file_sha256(installer) != expected:
                installer.unlink(missing_ok=True)
                raise UpdateError("安装包校验失败，请重新下载")

            powershell = (
                Path(os.environ.get("SystemRoot", r"C:\Windows"))
                / "System32"
                / "WindowsPowerShell"
                / "v1.0"
                / "powershell.exe"
            )
            if not powershell.is_file():
                raise UpdateError("找不到 Windows PowerShell，无法启动更新")
            quoted_installer = str(installer).replace("'", "''")
            helper_path = update_helper_path()
            helper_path.parent.mkdir(parents=True, exist_ok=True)
            helper_path.write_text(
                "$ErrorActionPreference = 'Stop'\n"
                f"while (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) {{\n"
                "  Start-Sleep -Milliseconds 250\n"
                "}\n"
                "Start-Sleep -Milliseconds 1500\n"
                "try {\n"
                f"  Start-Process -FilePath '{quoted_installer}' "
                "-ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"
                "'/CLOSEAPPLICATIONS') -Wait\n"
                "} finally {\n"
                "  Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
                "}\n",
                encoding="utf-8-sig",
            )
            creation_flags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            try:
                subprocess.Popen(
                    [
                        str(powershell),
                        "-NoLogo",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(helper_path),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=creation_flags,
                )
            except OSError as exc:
                helper_path.unlink(missing_ok=True)
                raise UpdateError(f"无法启动更新安装器：{exc}") from exc
            self.state.patch("update", status="installing", error="")
            self.state.log("warn", "更新安装器已就绪，正在重启应用")
            return self.state.snapshot()

    def _download_worker(self) -> None:
        part_path: Optional[Path] = None
        try:
            update = self.state.snapshot().get("update", {})
            url = str(update.get("download_url") or "")
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
                raise UpdateError("安装包下载地址不受信任")
            expected = normalize_sha256(str(update.get("digest") or ""))
            asset_name = Path(str(update.get("asset_name") or "vrctool-update.exe")).name
            update_dir = app_data_root() / "updates"
            update_dir.mkdir(parents=True, exist_ok=True)
            destination = update_dir / asset_name
            part_path = destination.with_suffix(destination.suffix + ".part")
            part_path.unlink(missing_ok=True)

            request = Request(
                url,
                headers={
                    "Accept": "application/octet-stream",
                    "User-Agent": f"vrctool/{__version__}",
                },
            )
            digest = hashlib.sha256()
            downloaded = 0
            expected_size = int(update.get("asset_size") or 0)
            last_update = 0.0
            with urlopen(request, timeout=300) as response, part_path.open("wb") as handle:
                response_size = int(response.headers.get("Content-Length") or expected_size or 0)
                if response_size <= 0 or response_size > MAX_INSTALLER_SIZE:
                    raise UpdateError("安装包大小异常")
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > MAX_INSTALLER_SIZE:
                        raise UpdateError("安装包超过允许大小")
                    handle.write(chunk)
                    digest.update(chunk)
                    now = time.monotonic()
                    if now - last_update >= 0.2:
                        self.state.patch(
                            "update",
                            downloaded_bytes=downloaded,
                            progress=min(99, int(downloaded * 100 / response_size)),
                        )
                        last_update = now
            if expected_size and downloaded != expected_size:
                raise UpdateError("安装包下载不完整")
            if digest.hexdigest() != expected:
                raise UpdateError("安装包 SHA-256 校验失败")
            part_path.replace(destination)
            self._cleanup_old_installers(update_dir, destination)
            self.state.patch(
                "update",
                status="ready",
                downloaded_bytes=downloaded,
                progress=100,
                installer_path=str(destination),
                error="",
            )
            self.state.log("ok", "更新安装包已下载并通过校验")
        except Exception as exc:
            if part_path is not None:
                part_path.unlink(missing_ok=True)
            message = self._friendly_error(exc)
            self.state.patch("update", status="error", available=False, error=message)
            self.state.log("warn", f"下载更新失败：{message}")

    def _fetch_json(self, url: str) -> Dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"vrctool/{__version__}",
            },
        )
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise UpdateError("GitHub 返回了无效的更新信息")
        return payload

    @staticmethod
    def _cleanup_old_installers(directory: Path, keep: Path) -> None:
        for path in directory.glob("vrctool*setup*.exe"):
            if path != keep:
                try:
                    path.unlink()
                except OSError:
                    pass

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, UpdateError):
            return str(exc)
        reason = getattr(exc, "reason", None)
        if reason:
            return f"网络连接失败：{reason}"
        return str(exc) or exc.__class__.__name__
