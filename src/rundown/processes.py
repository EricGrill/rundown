"""Bounded subprocess cancellation for background research jobs."""
from __future__ import annotations

import os
import signal
import subprocess
from threading import Event, Thread
from time import monotonic, sleep
from typing import Any


class OperationCancelled(RuntimeError):
    """The user cancelled work; callers must not retry or fall back."""


def check_cancelled(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled("Cancelled by user.")


def _terminate(process: subprocess.Popen) -> None:
    grace_deadline = monotonic() + 0.5
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        # The group leader can exit on TERM while a descendant that redirected
        # its stdio remains alive. Give every descendant the full TERM grace
        # period even when wait observed the leader's quick exit.
        while True:
            try:
                os.killpg(process.pid, 0)
            except (ProcessLookupError, PermissionError):
                break
            remaining = grace_deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(0.01, remaining))
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    elif process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def run_command(
    args: list[str], *, cancel_event: Event | None = None,
    timeout: float | None = None, **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run with subprocess.run semantics, checking cancellation every 100 ms."""
    check_cancelled(cancel_event)
    capture = kwargs.pop("capture_output", False)
    check = kwargs.pop("check", False)
    input_data = kwargs.pop("input", None)
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input_data is not None:
        kwargs["stdin"] = subprocess.PIPE
    if os.name == "posix":
        kwargs["start_new_session"] = True
    started = monotonic()
    with subprocess.Popen(args, **kwargs) as process:
        # CPython 3.11 can stop feeding stdin after communicate(input=...) times
        # out and is retried with input=None. Give one worker ownership of all
        # pipes and monitor completion separately, so input is sent exactly once.
        completed = Event()
        output: list[tuple[Any, Any]] = []
        errors: list[BaseException] = []

        def communicate() -> None:
            try:
                output.append(process.communicate(input=input_data))
            except BaseException as exc:
                errors.append(exc)
            finally:
                completed.set()

        communication = Thread(target=communicate, daemon=True, name="rundown-subprocess-io")
        communication.start()
        try:
            while True:
                check_cancelled(cancel_event)
                if completed.is_set():
                    break
                remaining = None if timeout is None else timeout - (monotonic() - started)
                if remaining is not None and remaining <= 0:
                    assert timeout is not None
                    raise subprocess.TimeoutExpired(args, timeout)
                completed.wait(min(0.1, remaining) if remaining is not None else 0.1)
            check_cancelled(cancel_event)
            if errors:
                raise errors[0]
            stdout, stderr = output[0]
        except BaseException:
            _terminate(process)
            raise
        finally:
            communication.join(timeout=1)
        result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
