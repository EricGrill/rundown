"""Bounded subprocess cancellation for background research jobs."""
from __future__ import annotations

import os
import signal
import subprocess
from threading import Event
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
        process.communicate(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    if os.name == "posix":
        # The group leader can exit on TERM while a descendant that redirected
        # its stdio remains alive. Give every descendant the full TERM grace
        # period even when communicate observed the leader's quick exit.
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
    process.communicate()


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
        try:
            while True:
                check_cancelled(cancel_event)
                remaining = None if timeout is None else timeout - (monotonic() - started)
                if remaining is not None and remaining <= 0:
                    assert timeout is not None
                    raise subprocess.TimeoutExpired(args, timeout)
                try:
                    stdout, stderr = process.communicate(
                        input=input_data, timeout=min(0.1, remaining) if remaining is not None else 0.1,
                    )
                    break
                except subprocess.TimeoutExpired:
                    input_data = None
            check_cancelled(cancel_event)
        except BaseException:
            _terminate(process)
            raise
        result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
