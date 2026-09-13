"""Real, offline transport checks shared by research harnesses."""
import json
import subprocess
import sys
import threading
import time

import pytest

from rundown.processes import OperationCancelled, run_command


def test_large_prompt_survives_communicate_retries(tmp_path):
    prompt = "Repository context: café, 漢字, $(touch nope)\n" * 20000
    result = run_command(
        [sys.executable, "-c", "import sys,time; time.sleep(0.3); sys.stdout.write(sys.stdin.read())"],
        input=prompt,
        text=True,
        capture_output=True,
        cwd=tmp_path,
        timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout == prompt
    assert not (tmp_path / "nope").exists()


def test_argument_transport_never_expands_shell_syntax(tmp_path):
    prompt = "$(touch escaped); `touch escaped`; $HOME\nquotes: '\""
    result = run_command(
        [sys.executable, "-c", "import json,sys; print(json.dumps(sys.argv[1:]))", prompt],
        text=True,
        capture_output=True,
        cwd=tmp_path,
        timeout=5,
    )
    assert json.loads(result.stdout) == [prompt]
    assert not (tmp_path / "escaped").exists()


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
def test_unconsumed_prompt_does_not_block_termination(tmp_path, cancel):
    event = threading.Event()
    ready = tmp_path / "ready"
    stop = threading.Event()

    def trigger():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline and not stop.wait(0.01):
            pass
        event.set()

    thread = threading.Thread(target=trigger, daemon=True) if cancel else None
    if thread is not None:
        thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(OperationCancelled if cancel else subprocess.TimeoutExpired):
            run_command(
                [
                    sys.executable,
                    "-c",
                    "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(30)",
                    str(ready),
                ],
                input="x" * 2000000,
                text=True,
                capture_output=True,
                cancel_event=event if cancel else None,
                timeout=5 if cancel else 0.5,
                cwd=tmp_path,
            )
        assert ready.exists()
        assert time.monotonic() - started < 7
    finally:
        stop.set()
        if thread is not None:
            thread.join(timeout=1)
