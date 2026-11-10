"""Run the whole Voltix system on this machine, with virtual hardware.

    python scripts/run_local.py            # server + virtual board + firmware
    python scripts/run_local.py --gui      # ... plus the meter's touchscreen GUI (Tkinter)

What it starts (all logs are interleaved here, prefixed by process name):

    server     FastAPI + web app      http://127.0.0.1:8000/app/
    board      virtual meter board    http://127.0.0.1:9000/      (the physical world)
    sampler    src/RPi/api.py         reads the virtual ADE9000 over virtual SPI
    sync       src/RPi/sync.py        store-and-forward to the server
    relay      src/RPi/relay.py       WebSocket relay control, drives virtual GPIOs
    failures   src/RPi/failure_log.py power-failure logger
    gui        src/RPi/app.py         (with --gui)

First run also creates src/Server/.env (SECRET_KEY) and provisions a device
(src/RPi/device.env). Stop everything with Ctrl+C.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "src" / "Server"
BOARD = ROOT / "src" / "VirtualDevice"
RPI = ROOT / "src" / "RPi"
PY = sys.executable
COLORS = {"server": "36", "board": "35", "sampler": "32", "sync": "34", "relay": "33", "failures": "31", "gui": "37"}
print_lock = threading.Lock()


def log(name: str, line: str) -> None:
    with print_lock:
        print(f"\033[{COLORS.get(name, '0')}m{name:>8} |\033[0m {line}", flush=True)


def run_once(args: list[str], cwd: Path) -> str:
    out = subprocess.run([PY, *args], cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"{' '.join(args)} failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout.strip()


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_http(url: str, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def start(name: str, args: list[str], cwd: Path, env: dict) -> subprocess.Popen:
    proc = subprocess.Popen([PY, *args], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)

    def pump():
        for line in proc.stdout:
            log(name, line.rstrip())
        log(name, f"exited with code {proc.wait()}")

    threading.Thread(target=pump, daemon=True).start()
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gui", action="store_true", help="also start the Tkinter touchscreen GUI")
    parser.add_argument("--server-port", type=int, default=8000)
    parser.add_argument("--board-port", type=int, default=9000)
    parser.add_argument("--device-id", default="meter-001")
    args = parser.parse_args()

    busy = [p for p in (args.server_port, args.board_port) if port_in_use(p)]
    if busy:
        sys.exit(f"Port(s) {', '.join(map(str, busy))} already in use - is another run_local.py still running? "
                 "Stop it (Ctrl+C in its terminal) or pass --server-port / --board-port.")

    server_url = f"http://127.0.0.1:{args.server_port}"
    board_url = f"http://127.0.0.1:{args.board_port}"

    # One-time setup.
    log("setup", run_once(["manage.py", "init-env"], SERVER))
    log("setup", run_once(["manage.py", "provision-device", "--device-id", args.device_id, "--name", "Virtual meter",
                           "--env-out", str(RPI / "device.env"), "--server-url", server_url], SERVER))

    env = os.environ | {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    fw_env = env | {"VOLTIX_HAL": "virtual", "SIM_URL": board_url, "SERVER_URL": server_url,
                    "GUI_GEOMETRY": os.getenv("GUI_GEOMETRY", "1600x900")}

    procs = [
        start("server", ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(args.server_port),
                         "--log-level", "warning"], SERVER, env),
        start("board", ["-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(args.board_port),
                        "--log-level", "warning"], BOARD, env),
    ]
    if not wait_http(f"{server_url}/api/health") or not wait_http(f"{board_url}/health"):
        log("setup", "server or virtual board did not come up - see the logs above")
    procs += [
        start("sampler", ["api.py"], RPI, fw_env),
        start("sync", ["sync.py"], RPI, fw_env),
        start("relay", ["relay.py"], RPI, fw_env),
        start("failures", ["failure_log.py"], RPI, fw_env),
    ]
    if args.gui:
        procs.append(start("gui", ["app.py"], RPI, fw_env))

    code, link = run_once(["claim.py"], RPI).splitlines()[-2:]
    banner = [
        "",
        "Voltix is running with virtual hardware:",
        f"  Web app           {server_url}/app/",
        f"  Virtual board     {board_url}/   (switch appliances, inject faults)",
        f"  API docs          {server_url}/docs",
        "",
        "  First time? Register the meter with this one-time link (valid 10 min):",
        f"  {link}",
        "  (new code any time: python src/RPi/claim.py)",
        "",
        "Press Ctrl+C to stop everything.",
        "",
    ]
    for line in banner:
        log("setup", line)

    try:
        while all(p.poll() is None for p in procs[:2]):
            time.sleep(0.5)
        log("setup", "server or board stopped; shutting down")
    except KeyboardInterrupt:
        log("setup", "stopping...")
    finally:
        for p in procs:
            if p.poll() is None:
                if os.name == "nt":
                    p.terminate()
                else:
                    p.send_signal(signal.SIGINT)
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
