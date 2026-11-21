#!/usr/bin/env python3
"""在 macOS/Linux 上启动真实服务，检查 DNS、看板和进程收尾。"""
from __future__ import annotations

import http.client
import json
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "app" / "cli.py"


def free_port(sock_type: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, sock_type) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def cli(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    result = subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"cli {args[0]} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    return result


def tcp_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def query_redirect(port: int) -> str:
    transaction = os.urandom(2)
    qname = b"".join(bytes((len(label),)) + label for label in
                    b"api-prd.vn.cloud.tesla.cn".split(b".")) + b"\0"
    question = qname + struct.pack("!HH", 1, 1)
    packet = transaction + struct.pack("!5H", 0x0100, 1, 0, 0, 0) + question
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(packet, ("127.0.0.1", port))
        response, _ = sock.recvfrom(4096)
    if response[:2] != transaction or struct.unpack("!H", response[6:8])[0] != 1:
        raise RuntimeError("DNS did not return one answer")
    return socket.inet_ntoa(response[-4:])


def check_dashboard(port: int) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/api/state")
        response = conn.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"dashboard returned HTTP {response.status}")
        state = json.loads(body)
        if "car_status" not in state or "car_conns" not in state:
            raise RuntimeError("dashboard state response is incomplete")
        if not state["car_status"]["l2"]:
            raise RuntimeError("dashboard ping check did not reach loopback")
    finally:
        conn.close()


def main() -> int:
    if os.name == "nt":
        raise RuntimeError("platform_smoke.py is intended for macOS/Linux runners")

    https_port = free_port()
    dns_port = free_port(socket.SOCK_DGRAM)
    dashboard_port = free_port()
    while dashboard_port == https_port:
        dashboard_port = free_port()
    args = (
        "start", "--ip", "127.0.0.1", "--dns-bind", "127.0.0.1",
        "--https-port", str(https_port), "--dns-port", str(dns_port),
        "--dashboard-port", str(dashboard_port), "--car-ip", "127.0.0.1",
    )
    try:
        cli(*args, timeout=45)
        if not tcp_open(https_port):
            raise RuntimeError("mitmproxy did not open its configured port")
        if query_redirect(dns_port) != "127.0.0.1":
            raise RuntimeError("DNS redirect returned an unexpected address")
        check_dashboard(dashboard_port)
        status = cli("status", "--https-port", str(https_port), "--dns-port", str(dns_port),
                     "--dashboard-port", str(dashboard_port))
        if not all(name in status.stdout for name in ("mitm", "dns", "panel")):
            raise RuntimeError("status did not report all three services")
    finally:
        cli("stop", timeout=20)
    if tcp_open(https_port) or tcp_open(dashboard_port):
        raise RuntimeError("stop left a TCP service listening")
    try:
        query_redirect(dns_port)
    except OSError:
        pass
    else:
        raise RuntimeError("stop left the DNS service responding")
    print("macOS/Linux service smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
