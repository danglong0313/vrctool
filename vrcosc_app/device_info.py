from __future__ import annotations

import platform
from functools import lru_cache
from typing import Any, Dict

import psutil

try:
    import cpuinfo
except Exception:
    cpuinfo = None

try:
    import GPUtil
except Exception:
    GPUtil = None

try:
    import wmi
except Exception:
    wmi = None


@lru_cache(maxsize=1)
def _cpu_name() -> str:
    if cpuinfo is not None:
        try:
            detected = cpuinfo.get_cpu_info().get("brand_raw") or platform.processor()
            if detected:
                return detected
        except Exception:
            pass
    if wmi is not None and platform.system() == "Windows":
        try:
            processors = list(wmi.WMI().Win32_Processor())
            if processors:
                return getattr(processors[0], "Name", None) or "Unknown CPU"
        except Exception:
            pass
    return platform.processor() or "Unknown CPU"


@lru_cache(maxsize=1)
def _static_gpu_info() -> Dict[str, Any]:
    info = {"name": "未检测到 GPU", "total_gb": 0.0}
    if wmi is None or platform.system() != "Windows":
        return info
    try:
        controllers = list(wmi.WMI().Win32_VideoController())
    except Exception:
        return info

    target = None
    for gpu in controllers:
        name = (getattr(gpu, "Name", "") or "").upper()
        if "NVIDIA" in name or "AMD" in name or "RADEON" in name:
            target = gpu
            break
    if target is None and controllers:
        target = controllers[0]
    if target is None:
        return info

    ram = getattr(target, "AdapterRAM", 0) or 0
    info["name"] = getattr(target, "Name", None) or info["name"]
    info["total_gb"] = int(ram) / (1024 ** 3) if ram else 0.0
    return info


def get_device_info() -> Dict[str, Any]:
    cpu_usage = psutil.cpu_percent(interval=0.05)
    ram = psutil.virtual_memory()
    gpu_name = _static_gpu_info()["name"]
    gpu_usage = 0.0
    vram_total = float(_static_gpu_info()["total_gb"])
    vram_used = 0.0

    if GPUtil is not None:
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu = gpus[0]
                gpu_name = gpu.name or gpu_name
                gpu_usage = float(gpu.load) * 100
                vram_total = float(gpu.memoryTotal) / 1024
                vram_used = float(gpu.memoryUsed) / 1024
        except Exception:
            pass

    return {
        "cpu": {
            "name": _cpu_name(),
            "usage": cpu_usage,
        },
        "gpu": {
            "name": gpu_name,
            "usage": gpu_usage,
            "vram_total": vram_total,
            "vram_used": vram_used,
        },
        "ram": {
            "total": ram.total / (1024 ** 3),
            "used": ram.used / (1024 ** 3),
            "usage": ram.percent,
        },
    }


def format_device_message(info: Dict[str, Any]) -> str:
    cpu = info["cpu"]
    gpu = info["gpu"]
    ram = info["ram"]
    return (
        f"CPU: {cpu['name']}\n"
        f"GPU: {gpu['name']}\n"
        f"CPU {cpu['usage']:.2f}%|GPU {gpu['usage']:.2f}%\n"
        f"VRAM: {gpu['vram_used']:.2f}GB/{gpu['vram_total']:.2f}GB\n"
        f"RAM: {ram['used']:.2f}GB/{ram['total']:.2f}GB"
    )
