"""Research command registry. Builders only prepare commands in an isolated cwd."""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import ResearchSettings

DEFAULT_FALLBACK = ("claude", "gemini", "codex")


@dataclass(frozen=True)
class HarnessInvocation:
    argv: list[str]
    input: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessOutput:
    text: str
    actual_model: str | None = None


def decode_text(stdout: str) -> HarnessOutput:
    return HarnessOutput(stdout.strip())


def decode_json(stdout: str) -> HarnessOutput:
    """Custom JSON envelope: {\"text\": report, \"model\": optional model id}."""
    value = json.loads(stdout)
    if not isinstance(value, dict) or not isinstance(value.get("text"), str):
        raise ValueError("Expected a JSON object with a text string")
    model = value.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError("Invalid reported model")
    return HarnessOutput(value["text"].strip(), model)


@dataclass(frozen=True)
class HarnessAdapter:
    identifier: str
    executable: str
    build: Callable[[str, str | None, Path], HarnessInvocation]
    decode: Callable[[str], HarnessOutput] = decode_text
    supports_model: bool = True


_REGISTRY: dict[str, HarnessAdapter] = {}


def register_harness(adapter: HarnessAdapter) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", adapter.identifier) or adapter.identifier == "auto":
        raise ValueError("Invalid harness identifier")
    if adapter.identifier in _REGISTRY:
        raise ValueError("Duplicate harness identifier")
    _REGISTRY[adapter.identifier] = adapter


def _builtin(identifier: str, args: list[str]) -> HarnessAdapter:
    def build(prompt: str, model: str | None, workdir: Path) -> HarnessInvocation:
        argv = [identifier, *args]
        if model is not None:
            argv.extend(["--model", model])
        if identifier == "gemini":
            argv.extend(["--prompt", prompt])
        else:
            argv.append(prompt)
        return HarnessInvocation(argv)
    return HarnessAdapter(identifier, identifier, build)


register_harness(_builtin("claude", ["--print", "--output-format", "text", "--permission-mode", "dontAsk", "--tools", "", "--no-session-persistence"]))
register_harness(_builtin("gemini", ["--output-format", "text", "--approval-mode", "plan", "--allowed-tools", ""]))
register_harness(_builtin("codex", ["exec", "--sandbox", "read-only", "--config", 'approval_policy="never"', "--disable", "shell_tool", "--config", 'web_search="disabled"', "--ephemeral", "--skip-git-repo-check", "--color", "never"]))


@dataclass(frozen=True)
class CustomHarnessSettings:
    executable: str
    args: tuple[str, ...] = ()
    prompt: str = "stdin"
    output: str = "text"

    def __post_init__(self) -> None:
        if not isinstance(self.executable, str) or not self.executable.strip() or "\x00" in self.executable:
            raise ValueError("custom executable must be a nonblank string")
        if not isinstance(self.args, (list, tuple)) or any(not isinstance(arg, str) or "\x00" in arg for arg in self.args):
            raise ValueError("custom args must be an array of strings")
        if self.prompt not in ("stdin", "argument") or self.output not in ("text", "json"):
            raise ValueError("custom prompt must be stdin/argument and output text/json")
        placeholders = sum(arg == "{prompt}" for arg in self.args)
        if any("{prompt}" in arg and arg != "{prompt}" for arg in self.args):
            raise ValueError("prompt placeholder must occupy an exact argument")
        if placeholders != (1 if self.prompt == "argument" else 0):
            raise ValueError("argument prompt requires exactly one {prompt}; stdin requires none")
        object.__setattr__(self, "args", tuple(self.args))

    def adapter(self, identifier: str) -> HarnessAdapter:
        def build(prompt: str, model: str | None, workdir: Path) -> HarnessInvocation:
            if model is not None:
                raise ValueError("Custom harnesses do not support model overrides")
            return HarnessInvocation(
                [self.executable, *(prompt if arg == "{prompt}" else arg for arg in self.args)],
                input=prompt if self.prompt == "stdin" else None,
            )
        return HarnessAdapter(identifier, self.executable, build, decode_json if self.output == "json" else decode_text, False)


def get_harnesses(settings: ResearchSettings) -> dict[str, HarnessAdapter]:
    adapters = dict(_REGISTRY)
    if not isinstance(settings.custom, dict):
        raise ValueError("research.custom must be a table")
    for name, custom in settings.custom.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or name == "auto" or name in adapters:
            raise ValueError("Invalid or duplicate custom harness identifier")
        if not isinstance(custom, CustomHarnessSettings):
            raise ValueError("Invalid custom harness settings")
        adapters[name] = custom.adapter(name)
    return adapters


def selected_harnesses(settings: ResearchSettings) -> tuple[HarnessAdapter, ...]:
    adapters = get_harnesses(settings)
    order = settings.fallback if settings.provider == "auto" else (settings.provider,)
    if not isinstance(settings.fallback, (tuple, list)) or not settings.fallback:
        raise ValueError("research.fallback must be a nonempty array")
    if any(not isinstance(name, str) or name not in adapters for name in settings.fallback):
        raise ValueError("research.fallback contains an unknown harness")
    if len(set(settings.fallback)) != len(settings.fallback):
        raise ValueError("research.fallback must not contain duplicates")
    if not isinstance(settings.provider, str) or settings.provider not in {*adapters, "auto"}:
        raise ValueError("Unknown research.provider")
    if settings.model is not None and (not isinstance(settings.model, str) or not settings.model.strip()):
        raise ValueError("research.model must be a nonblank string")
    selected = tuple(adapters[name] for name in order)
    if settings.model is not None and any(not adapter.supports_model for adapter in selected):
        raise ValueError("Selected harness does not support model overrides")
    return selected
