import os
import signal
import subprocess
import sys
import threading
import time
import pytest

from rundown.processes import OperationCancelled, run_command


def test_cancelled_before_start_does_not_execute_command(tmp_path):
    marker = tmp_path / "started"
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(OperationCancelled):
        run_command(
            [sys.executable, "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).touch()", str(marker)],
            cancel_event=cancelled,
        )

    assert not marker.exists()


def test_run_command_returns_captured_output():
    result = run_command(
        [sys.executable, "-c", "print('ready')"], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "ready"


def test_timeout_terminates_real_process_quickly():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.15)
    assert time.monotonic() - started < 3


@pytest.mark.skipif(os.name != "posix", reason="process groups are a POSIX cancellation path")
def test_cancellation_reaches_child_process_group(tmp_path):
    ready = tmp_path / "child-ready"
    terminated = tmp_path / "child-terminated"
    cancelled = threading.Event()
    child_code = (
        "import signal,sys,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, lambda *_: (time.sleep(0.15), Path(sys.argv[2]).touch(), sys.exit(0))); "
        "Path(sys.argv[1]).touch(); time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]); "
        "time.sleep(30)"
    )

    def cancel_when_ready() -> None:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancelled.set()

    trigger = threading.Thread(target=cancel_when_ready)
    trigger.start()
    with pytest.raises(OperationCancelled):
        run_command(
            [sys.executable, "-c", parent_code, child_code, str(ready), str(terminated)],
            cancel_event=cancelled,
        )
    trigger.join(timeout=1)

    deadline = time.monotonic() + 2
    while not terminated.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    assert terminated.exists()


@pytest.mark.skipif(os.name != "posix", reason="process groups are a POSIX cancellation path")
def test_cancellation_kills_term_ignoring_child_after_parent_exits(tmp_path):
    ready = tmp_path / "child-ready"
    survived = tmp_path / "child-survived"
    pid_path = tmp_path / "child-pid"
    cancelled = threading.Event()
    child_code = (
        "import os,signal,sys,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "Path(sys.argv[1]).write_text(str(os.getpid())); "
        "Path(sys.argv[2]).touch(); time.sleep(1); "
        "Path(sys.argv[3]).touch(); time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3],sys.argv[4]], "
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "time.sleep(30)"
    )

    def cancel_when_ready() -> None:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        cancelled.set()

    trigger = threading.Thread(target=cancel_when_ready)
    trigger.start()
    child_pid = None
    started = time.monotonic()
    try:
        with pytest.raises(OperationCancelled):
            run_command(
                [
                    sys.executable,
                    "-c",
                    parent_code,
                    child_code,
                    str(pid_path),
                    str(ready),
                    str(survived),
                ],
                cancel_event=cancelled,
            )
        trigger.join(timeout=1)
        assert ready.exists()
        assert time.monotonic() - started >= 0.45
        child_pid = int(pid_path.read_text())

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            pytest.fail("TERM-ignoring child remained alive after cancellation")
        assert not survived.exists()
    finally:
        trigger.join(timeout=1)
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
