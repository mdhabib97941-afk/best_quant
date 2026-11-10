"""
Titan Quant System - Telegram Alert Daemon Loop (Remediated Architecture)

Provides robust, non-blocking parallel scheduling, subprocess execution timeout enforcement,
exit code verification, and exponential backoff for Telegram alert sentinels:
- Zone Unlock & Retest Scanner (telegram_day_unlock_trader.py)
- Whale Lifecycle & Iceberg Sentinel (whale_lifecycle_sentinel.py)

Remediates:
- F23: Missing subprocess execution timeouts (enforces 45s deadline per task)
- F24: Monolithic sequential execution and loop drift (ThreadPoolExecutor parallel scheduling)
- F25: Unchecked exit codes and silent failures (exponential backoff & status tracking)
"""

import os
import sys
import time
import signal
import argparse
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import concurrent.futures

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Base directories
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CORE_DIR)

# Default timing parameters (seconds)
DEFAULT_SCAN_INTERVAL = 60.0
DEFAULT_TIMEOUT = 45.0
DEFAULT_MAX_BACKOFF = 300.0
DEFAULT_BACKOFF_FACTOR = 2.0


@dataclass
class ScheduledTask:
    name: str
    script_path: str
    interval: float = DEFAULT_SCAN_INTERVAL
    timeout: float = DEFAULT_TIMEOUT
    max_backoff: float = DEFAULT_MAX_BACKOFF
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR

    # Runtime state
    consecutive_failures: int = 0
    consecutive_timeouts: int = 0
    total_runs: int = 0
    total_successes: int = 0
    last_run_time: float = 0.0
    last_success_time: float = 0.0
    last_duration: float = 0.0
    last_exit_code: Optional[int] = None
    last_error: Optional[str] = None
    next_run_time: float = 0.0
    is_running: bool = False


@dataclass
class TaskResult:
    task_name: str
    success: bool
    exit_code: int
    duration: float
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None
    timed_out: bool = False


def build_subprocess_env() -> Dict[str, str]:
    """Construct a clean, robust environment for child Python subprocesses."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    
    # Ensure CORE_DIR and PROJECT_ROOT are at head of PYTHONPATH
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [CORE_DIR, PROJECT_ROOT]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def execute_task(task: ScheduledTask, env: Optional[Dict[str, str]] = None) -> TaskResult:
    """
    Executes a single scheduled task in an isolated subprocess with timeout enforcement,
    capturing stdout/stderr, verifying exit codes, and applying exponential backoff.
    """
    if env is None:
        env = build_subprocess_env()

    task.is_running = True
    task.last_run_time = time.time()
    task.total_runs += 1
    start_ts = time.time()

    try:
        res = subprocess.run(
            [sys.executable, task.script_path],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=task.timeout,
            cwd=CORE_DIR,
            env=env
        )
        duration = time.time() - start_ts
        task.last_duration = duration
        task.last_exit_code = res.returncode

        if res.returncode == 0:
            # Task succeeded
            task.consecutive_failures = 0
            task.consecutive_timeouts = 0
            task.total_successes += 1
            task.last_success_time = time.time()
            task.last_error = None
            task.next_run_time = time.time() + task.interval

            # Log outputs if present
            if res.stdout and res.stdout.strip():
                print(f"[{task.name}]\n{res.stdout.strip()}")
            if res.stderr and res.stderr.strip():
                print(f"[{task.name} STDERR]\n{res.stderr.strip()}")

            return TaskResult(
                task_name=task.name,
                success=True,
                exit_code=0,
                duration=duration,
                stdout=res.stdout,
                stderr=res.stderr
            )
        else:
            # Task returned non-zero exit code (F25)
            task.consecutive_failures += 1
            backoff = min(task.interval * (task.backoff_factor ** (task.consecutive_failures - 1)), task.max_backoff)
            task.next_run_time = time.time() + backoff
            task.last_error = f"Exit code {res.returncode}"

            print(
                f"❌ [{task.name}] Failed with exit code {res.returncode} "
                f"(duration: {duration:.1f}s, consecutive failures: {task.consecutive_failures}). "
                f"Backing off for {backoff:.1f}s."
            )
            if res.stdout and res.stdout.strip():
                print(f"[{task.name} STDOUT]\n{res.stdout.strip()}")
            if res.stderr and res.stderr.strip():
                print(f"[{task.name} STDERR]\n{res.stderr.strip()}")

            return TaskResult(
                task_name=task.name,
                success=False,
                exit_code=res.returncode,
                duration=duration,
                stdout=res.stdout,
                stderr=res.stderr,
                error_message=f"Subprocess exited with code {res.returncode}"
            )

    except subprocess.TimeoutExpired as te:
        # Task exceeded execution timeout deadline (F23)
        duration = time.time() - start_ts
        task.last_duration = duration
        task.consecutive_failures += 1
        task.consecutive_timeouts += 1
        task.last_exit_code = -1
        backoff = min(task.interval * (task.backoff_factor ** (task.consecutive_failures - 1)), task.max_backoff)
        task.next_run_time = time.time() + backoff
        task.last_error = f"TimeoutExpired after {te.timeout}s"

        partial_stdout = te.stdout or ""
        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode('utf-8', errors='replace')
        partial_stderr = te.stderr or ""
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode('utf-8', errors='replace')

        print(
            f"⏱️ [{task.name}] Timed out after {te.timeout}s (consecutive failures: {task.consecutive_failures}). "
            f"Backing off for {backoff:.1f}s."
        )
        if partial_stdout.strip():
            print(f"[{task.name} PARTIAL STDOUT]\n{partial_stdout.strip()}")
        if partial_stderr.strip():
            print(f"[{task.name} PARTIAL STDERR]\n{partial_stderr.strip()}")

        return TaskResult(
            task_name=task.name,
            success=False,
            exit_code=-1,
            duration=duration,
            stdout=partial_stdout,
            stderr=partial_stderr,
            error_message=f"TimeoutExpired after {te.timeout}s",
            timed_out=True
        )

    except Exception as exc:
        duration = time.time() - start_ts
        task.last_duration = duration
        task.consecutive_failures += 1
        backoff = min(task.interval * (task.backoff_factor ** (task.consecutive_failures - 1)), task.max_backoff)
        task.next_run_time = time.time() + backoff
        task.last_error = str(exc)

        print(
            f"💥 [{task.name}] Unexpected error: {exc} "
            f"(consecutive failures: {task.consecutive_failures}). Backing off for {backoff:.1f}s."
        )
        return TaskResult(
            task_name=task.name,
            success=False,
            exit_code=-2,
            duration=duration,
            error_message=str(exc)
        )

    finally:
        task.is_running = False


class TelegramDaemonScheduler:
    """
    Non-blocking, drift-compensated scheduler for Telegram alerting subprocesses.
    Dispatches tasks concurrently via ThreadPoolExecutor when their scheduled next_run_time arrives.
    """

    def __init__(
        self,
        tasks: List[ScheduledTask],
        parallel: bool = True,
        max_workers: int = 4
    ):
        self.tasks = tasks
        self.parallel = parallel
        self.max_workers = max(1, max_workers)
        self.stop_event = threading.Event()
        self.env = build_subprocess_env()

    def run_once(self) -> Dict[str, TaskResult]:
        """Runs all tasks once synchronously or in parallel, returning their results."""
        results = {}
        if self.parallel and len(self.tasks) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(self.tasks), self.max_workers)) as executor:
                future_to_task = {
                    executor.submit(execute_task, task, self.env): task
                    for task in self.tasks
                }
                for future in concurrent.futures.as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        results[task.name] = future.result()
                    except Exception as e:
                        results[task.name] = TaskResult(
                            task_name=task.name,
                            success=False,
                            exit_code=-3,
                            duration=0.0,
                            error_message=str(e)
                        )
        else:
            for task in self.tasks:
                results[task.name] = execute_task(task, self.env)
        return results

    def run_loop(self):
        """Runs continuous event-driven tick loop until stop_event is set."""
        print(f"🚀 Starting Telegram Sentinel Daemon Loop...")
        print(f"   - Parallel scheduling: {self.parallel}")
        print(f"   - Managed tasks: {[t.name for t in self.tasks]}")
        print(f"   - Press Ctrl+C to stop.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Initial run time is now
            now = time.time()
            for t in self.tasks:
                t.next_run_time = now

            while not self.stop_event.is_set():
                now = time.time()
                for task in self.tasks:
                    if now >= task.next_run_time and not task.is_running:
                        if self.parallel:
                            executor.submit(execute_task, task, self.env)
                        else:
                            execute_task(task, self.env)

                # Sleep 1.0s or wake up instantly on stop_event
                self.stop_event.wait(timeout=1.0)

        print("🛑 Telegram Daemon scheduler stopped cleanly.")

    def stop(self):
        """Signals the daemon to stop."""
        self.stop_event.set()


def create_default_tasks(
    interval: float = DEFAULT_SCAN_INTERVAL,
    timeout: float = DEFAULT_TIMEOUT,
    max_backoff: float = DEFAULT_MAX_BACKOFF
) -> List[ScheduledTask]:
    """Factory creating the production scheduled tasks."""
    unlock_path = os.path.join(CORE_DIR, "telegram_day_unlock_trader.py")
    whale_path = os.path.join(CORE_DIR, "whale_lifecycle_sentinel.py")
    squeeze_path = os.path.join(CORE_DIR, "short_squeeze_sentinel.py")
    long_squeeze_path = os.path.join(CORE_DIR, "long_squeeze_sentinel.py")
    anti_move_path = os.path.join(CORE_DIR, "anti_market_move_tracker.py")

    return [
        ScheduledTask(
            name="ZoneUnlockTrader",
            script_path=unlock_path,
            interval=interval,
            timeout=timeout,
            max_backoff=max_backoff
        ),
        ScheduledTask(
            name="WhaleLifecycleSentinel",
            script_path=whale_path,
            interval=interval,
            timeout=timeout,
            max_backoff=max_backoff
        ),
        ScheduledTask(
            name="ShortSqueezeSentinel",
            script_path=squeeze_path,
            interval=30.0,
            timeout=timeout,
            max_backoff=max_backoff
        ),
        ScheduledTask(
            name="LongSqueezeSentinel",
            script_path=long_squeeze_path,
            interval=30.0,
            timeout=timeout,
            max_backoff=max_backoff
        ),
        ScheduledTask(
            name="AntiMarketMoveSentinel",
            script_path=anti_move_path,
            interval=60.0,
            timeout=timeout,
            max_backoff=max_backoff
        )
    ]


def main():
    parser = argparse.ArgumentParser(description="Titan Quant System - Telegram Alert Daemon Loop")
    parser.add_argument("--interval", type=float, default=DEFAULT_SCAN_INTERVAL, help="Base scan interval in seconds (default: 60.0)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-task subprocess timeout in seconds (default: 45.0)")
    parser.add_argument("--max-backoff", type=float, default=DEFAULT_MAX_BACKOFF, help="Maximum backoff interval in seconds (default: 300.0)")
    parser.add_argument("--sequential", action="store_true", help="Force sequential task execution instead of parallel ThreadPool")
    parser.add_argument("--once", action="store_true", help="Run each task once and exit (for testing and verification)")
    parser.add_argument("--test", action="store_true", help="Run each task once and exit (alias for --once)")
    args = parser.parse_args()

    tasks = create_default_tasks(
        interval=args.interval,
        timeout=args.timeout,
        max_backoff=args.max_backoff
    )
    scheduler = TelegramDaemonScheduler(
        tasks=tasks,
        parallel=not args.sequential,
        max_workers=len(tasks)
    )

    def handle_signal(sig, frame):
        print("\n🛑 Shutdown signal received. Gracefully stopping daemon...")
        scheduler.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.once or args.test:
        print("⚡ Executing one-shot daemon cycle...")
        results = scheduler.run_once()
        all_passed = all(r.success for r in results.values())
        print(f"One-shot cycle completed. All passed: {all_passed}")
        sys.exit(0 if all_passed else 1)
    else:
        scheduler.run_loop()


if __name__ == '__main__':
    main()
