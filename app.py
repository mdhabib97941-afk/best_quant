"""
Titan Quant System - Master Cloud Entrypoint (Render & Production Web Runner)
=============================================================================
This file serves as the unified entrypoint for cloud hosting (Render, Railway, Docker, VPS).
It simultaneously:
1. Spawns Dragonfly Titan Brain (L2/L3 Orderbook streaming & Gate sentinel) as a resilient background worker.
2. Spawns Telegram Daemon Loop (liquidity & whale alerts) if credentials/env enabled.
3. Hosts the Institutional Quant Web Dashboard on 0.0.0.0:$PORT.
"""

import os
import sys
import time
import signal
import threading
import subprocess

# Ensure core directory is on Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(PROJECT_ROOT, "core")
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

active_subprocesses = []

def cleanup_processes(signum=None, frame=None):
    """Graceful shutdown of all background daemons."""
    print("\n[SYSTEM] Received shutdown signal. Terminating background workers...")
    for proc in active_subprocesses:
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
    sys.exit(0)

def run_resilient_worker(script_name, args=None, env_key="ENABLE_WORKER", default_enabled="true"):
    """Spawns and auto-restarts a core daemon in a supervised thread."""
    is_enabled = os.environ.get(env_key, default_enabled).lower() in ("true", "1", "yes")
    if not is_enabled:
        print(f"[WORKER] {script_name} is disabled via {env_key}=false")
        return

    def worker_loop():
        cmd = [sys.executable, "-u", os.path.join(CORE_DIR, script_name)]
        if args:
            cmd.extend(args)
        
        while True:
            try:
                print(f"[WORKER] Starting {script_name}...")
                proc = subprocess.Popen(
                    cmd,
                    cwd=CORE_DIR,
                    stdout=subprocess.DEVNULL, # keep stdout clean for web requests
                    stderr=subprocess.STDOUT
                )
                active_subprocesses.append(proc)
                proc.wait()
                print(f"[WORKER] {script_name} stopped (code {proc.returncode}). Restarting in 5s...")
            except Exception as e:
                print(f"[WORKER] Exception in {script_name}: {e}")
            time.sleep(5)

    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

if __name__ == '__main__':
    # Register graceful shutdown signals
    signal.signal(signal.SIGINT, cleanup_processes)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, cleanup_processes)

    print("=========================================================================")
    print("           TITAN INSTITUTIONAL QUANT SYSTEM - CLOUD ENGINE               ")
    print("=========================================================================")

    # 1. Start Dragonfly Titan Brain L2/L3 Daemon
    run_resilient_worker(
        script_name="dragonfly_titan_brain.py",
        args=["0"],
        env_key="ENABLE_DRAGONFLY",
        default_enabled="true"
    )

    # 2. Start Telegram Alert Loop Daemon
    run_resilient_worker(
        script_name="telegram_daemon_loop.py",
        args=None,
        env_key="ENABLE_TELEGRAM",
        default_enabled="true"
    )

    # 3. Launch Quant Dashboard Server on Render PORT
    import quant_dashboard_server
    port = int(os.environ.get("PORT", 8585))
    host = "0.0.0.0"
    print(f"[WEB] Titan Quant Dashboard is binding to http://{host}:{port}")
    quant_dashboard_server.run_server(host=host, port=port)
