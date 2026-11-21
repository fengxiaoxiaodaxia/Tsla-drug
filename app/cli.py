#!/usr/bin/env python3
"""跨平台启动热点模式里的代理、DNS 和看板进程。"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
STATE_FILE = LOGS / "platform_services.json"
SERVICE_MARKERS = {
    "mitm": "fsd_mock.py",
    "dns": "dns_sink.py",
    "panel": "fsd_panel.py",
}


def _mitmdump() -> str:
    exe = "mitmdump.exe" if os.name == "nt" else "mitmdump"
    candidate = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin") / exe
    return str(candidate) if candidate.is_file() else (shutil.which("mitmdump") or str(candidate))


def _read_state() -> dict:
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _command_line(pid: int) -> str | None:
    proc_cmd = Path(f"/proc/{pid}/cmdline")
    try:
        return proc_cmd.read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        pass
    try:
        result = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                capture_output=True, text=True, timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _managed_process(service: str, entry: dict) -> bool:
    try:
        pid = int(entry["pid"])
        os.kill(pid, 0)
    except (KeyError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        pass
    command = _command_line(pid)
    return bool(command and SERVICE_MARKERS[service] in command)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _tcp_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _wait_for_port(port: int, process: subprocess.Popen, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _tcp_open(port):
            return True
        time.sleep(0.2)
    return False


def _spawn(service: str, argv: list[str], env: dict) -> tuple[dict, subprocess.Popen]:
    LOGS.mkdir(parents=True, exist_ok=True)
    log_path = LOGS / f"{service}.log"
    with log_path.open("ab", buffering=0) as log:
        log.write((f"\n===== {datetime.now().isoformat(timespec='seconds')} start {service} =====\n").encode())
        process = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)
            if os.name == "nt" else 0,
        )
    entry = {"pid": process.pid, "argv": argv, "started": datetime.now().isoformat(timespec="seconds")}
    return entry, process


def _log_tail(service: str, lines: int = 20) -> str:
    try:
        return "\n".join((LOGS / f"{service}.log").read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return "日志文件不可读"


def _port_owner(port: int) -> str:
    if sys.platform != "darwin" or not shutil.which("lsof"):
        return ""
    try:
        result = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                                capture_output=True, text=True, timeout=3, check=False)
        return (result.stdout or result.stderr).strip() or "无监听进程"
    except (OSError, subprocess.SubprocessError):
        return "lsof 查询失败"


def _stop_process(service: str, entry: dict) -> bool:
    if not _managed_process(service, entry):
        return True
    pid = int(entry["pid"])
    try:
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.2)
        if _pid_alive(pid):
            os.killpg(pid, signal.SIGKILL)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.1)
        return not _pid_alive(pid)
    except OSError as exc:
        print(f"{service}: 停止失败：{exc}")
        return False


def start(args: argparse.Namespace) -> int:
    try:
        ip = ipaddress.ip_address(args.ip)
    except ValueError:
        print(f"无效的 IPv4 地址：{args.ip}")
        return 2
    if ip.version != 4:
        print("--ip 必须是 IPv4 地址。")
        return 2
    if args.car_ip:
        try:
            if ipaddress.ip_address(args.car_ip).version != 4:
                raise ValueError
        except ValueError:
            print("--car-ip 必须是 IPv4 地址。")
            return 2
    if args.dns_bind:
        try:
            if ipaddress.ip_address(args.dns_bind).version != 4:
                raise ValueError
        except ValueError:
            print("--dns-bind 必须是 IPv4 地址。")
            return 2

    env = dict(os.environ)
    env.update({
        "FSD_MOCK_JSON": str(ROOT / "payload.json"),
        "FSD_MOCK_LOG_DIR": str(LOGS),
        "FSD_MOCK_LOG_ALL": "1",
        "FSD_MOCK_MODE_FILE": str(ROOT / "mode.json"),
        "FSD_LOCAL_IPS": ",".join(filter(None, [os.environ.get("FSD_LOCAL_IPS", ""), args.ip])),
        "PYTHONUNBUFFERED": "1",
    })
    mitmdump = _mitmdump()
    if not Path(mitmdump).is_file() and shutil.which(mitmdump) is None:
        print("找不到 mitmdump；请先在当前 Python 虚拟环境安装 app/requirements.txt。")
        return 2

    commands = {
        "mitm": [mitmdump, "-s", str(ROOT / "fsd_mock.py"),
                 "--set", f"confdir={ROOT / 'certs2'}", "--set", "ssl_insecure=true",
                 "--set", "connection_strategy=lazy", "--set", "block_global=false", "--emudhra",
                 "--mode", f"reverse:https://api-prd.vn.cloud.tesla.cn@{args.https_port}"],
        "dns": [sys.executable, str(ROOT / "dns_sink.py"), "--ip", args.ip,
                "--bind", args.dns_bind or args.ip, "--port", str(args.dns_port),
                "--redirect", "api-prd.vn.cloud.tesla.cn"],
        "panel": [sys.executable, str(ROOT / "web" / "fsd_panel.py"), "--port", str(args.dashboard_port),
                  "--https-port", str(args.https_port), "--car-ip", args.car_ip or "",
                  "--car-mac", args.car_mac or ""],
    }
    state = _read_state()
    failures = 0
    for service, argv in commands.items():
        existing = state.get(service)
        if isinstance(existing, dict) and _managed_process(service, existing):
            if existing.get("argv") == argv:
                print(f"{service}: 已运行 (pid {existing['pid']})")
                continue
            print(f"{service}: 配置变化，正在重启 (pid {existing['pid']})")
            if not _stop_process(service, existing):
                failures += 1
                continue
            state.pop(service, None)
            _write_state(state)

        port = {"mitm": args.https_port, "panel": args.dashboard_port}.get(service)
        if port and _tcp_open(port):
            print(f"{service}: 端口 {port} 已被其他进程占用，未启动")
            failures += 1
            continue

        try:
            entry, process = _spawn(service, argv, env)
        except OSError as exc:
            print(f"{service}: 启动失败：{exc}")
            failures += 1
            continue
        state[service] = entry
        _write_state(state)

        if service == "dns":
            time.sleep(0.8)
            ready = _managed_process(service, entry)
        else:
            ready = _wait_for_port(port, process)
        print(f"{service}: {'已启动' if ready else '启动失败'} (pid {entry['pid']})")
        if not ready:
            print(f"{service} 日志尾部:\n{_log_tail(service)}")
            if port:
                print(f"{service} 端口诊断:\n{_port_owner(port)}")
            failures += 1

    return 1 if failures else 0


def status(args: argparse.Namespace) -> int:
    state = _read_state()
    rows = (("mitm", args.https_port), ("dns", args.dns_port), ("panel", args.dashboard_port))
    for service, port in rows:
        entry = state.get(service)
        managed = isinstance(entry, dict) and _managed_process(service, entry)
        if service == "dns":
            detail = f"UDP/{port} 进程运行 (pid {entry['pid']})" if managed else f"UDP/{port} 未运行"
        else:
            detail = f"端口 {port} {'监听中' if _tcp_open(port) else '未监听'}"
            if managed:
                detail += f"，pid {entry['pid']}"
        print(f"{service}: {detail}")
    return 0


def stop(_args: argparse.Namespace) -> int:
    state = _read_state()
    failed = False
    for service in reversed(tuple(SERVICE_MARKERS)):
        entry = state.get(service)
        if not isinstance(entry, dict):
            continue
        if not _managed_process(service, entry):
            state.pop(service, None)
            print(f"{service}: 未发现匹配的托管进程，已清理过期记录")
            continue
        if _stop_process(service, entry):
            state.pop(service, None)
            print(f"{service}: 已停止")
        else:
            failed = True
    _write_state(state)
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="macOS/Linux 热点模式服务管理")
    sub = ap.add_subparsers(dest="action", required=True)
    start_parser = sub.add_parser("start", help="启动代理、DNS 和看板")
    start_parser.add_argument("--ip", required=True, help="本机连接热点的 IPv4 地址")
    start_parser.add_argument("--dns-bind", help="DNS 监听地址，默认与 --ip 相同")
    start_parser.add_argument("--car-ip", help="车机固定 IPv4 地址，用于看板在线检测")
    start_parser.add_argument("--car-mac", help="车机 MAC 地址，用于看板显示")
    start_parser.add_argument("--https-port", type=int, default=443)
    start_parser.add_argument("--dns-port", type=int, default=53)
    start_parser.add_argument("--dashboard-port", type=int, default=8900)
    start_parser.set_defaults(func=start)

    status_parser = sub.add_parser("status", help="查看服务进程和端口")
    status_parser.add_argument("--https-port", type=int, default=443)
    status_parser.add_argument("--dns-port", type=int, default=53)
    status_parser.add_argument("--dashboard-port", type=int, default=8900)
    status_parser.set_defaults(func=status)
    stop_parser = sub.add_parser("stop", help="停止本工具启动的服务进程")
    stop_parser.set_defaults(func=stop)
    args = ap.parse_args()
    if os.name == "nt":
        print("Windows 请继续使用 start_hotspot.ps1、stop_hotspot.ps1 和 start_hotspot.ps1 -Status。")
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
