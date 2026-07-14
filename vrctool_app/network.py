from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any, Dict, List

import psutil

BENCHMARK_NET = ipaddress.ip_network("198.18.0.0/15")
VIRTUAL_KEYWORDS = (
    "vmware",
    "virtual",
    "vbox",
    "hyper-v",
    "loopback",
    "bluetooth",
    "蓝牙",
    "meta",
)
PREFERRED_KEYWORDS = ("ethernet", "以太", "wi-fi", "wifi", "wlan", "无线")


def is_tcp_port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((host, int(port)))
    except OSError:
        return False
    return True


def _interface_score(name: str, ip: str, loopback: bool) -> tuple:
    ip_obj = ipaddress.ip_address(ip)
    lowered = name.lower()
    score = 0
    if loopback:
        score += 100
    if ip_obj.is_link_local:
        score += 80
    if ip_obj in BENCHMARK_NET:
        score += 70
    if any(keyword in lowered for keyword in VIRTUAL_KEYWORDS):
        score += 35
    if ip_obj.is_private and not ip_obj.is_link_local and ip_obj not in BENCHMARK_NET:
        score -= 20
    if any(keyword in lowered for keyword in PREFERRED_KEYWORDS):
        score -= 10
    return (score, name, ip)


def get_network_interfaces() -> List[Dict[str, Any]]:
    interfaces: List[Dict[str, Any]] = []
    seen = set()

    for name, addresses in psutil.net_if_addrs().items():
        for address in addresses:
            if getattr(address, "family", None) != socket.AF_INET:
                continue
            ip = address.address
            if not ip or ip in seen:
                continue
            seen.add(ip)
            ip_obj = ipaddress.ip_address(ip)
            interfaces.append(
                {
                    "name": name,
                    "ip": ip,
                    "loopback": ip_obj.is_loopback,
                    "label": f"{name} - {ip}",
                }
            )

    if "127.0.0.1" not in seen:
        interfaces.append(
            {
                "name": "Loopback",
                "ip": "127.0.0.1",
                "loopback": True,
                "label": "Loopback - 127.0.0.1",
            }
        )

    interfaces.sort(key=lambda item: _interface_score(item["name"], item["ip"], item["loopback"]))
    return interfaces


def pick_default_lan_ip() -> str:
    for item in get_network_interfaces():
        ip_obj = ipaddress.ip_address(item["ip"])
        lowered = item["name"].lower()
        if item["loopback"] or ip_obj.is_link_local or ip_obj in BENCHMARK_NET:
            continue
        if any(keyword in lowered for keyword in VIRTUAL_KEYWORDS):
            continue
        return item["ip"]
    for item in get_network_interfaces():
        if not item["loopback"] and not ipaddress.ip_address(item["ip"]).is_link_local:
            return item["ip"]
    return "127.0.0.1"
