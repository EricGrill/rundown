"""Text-only OpenCode adapter with disposable configuration and deny-all tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .harnesses import HarnessAdapter, HarnessInvocation, HarnessOutput


# Restrict credential routing to reviewed built-in providers, not arbitrary plugins.
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_GENERATIVE_AI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def managed_config_paths() -> tuple[Path, ...]:
    if sys.platform == "darwin":
        import pwd

        try:
            username = pwd.getpwuid(os.getuid()).pw_name
        except KeyError:
            username = "user"
        root = Path("/Library/Application Support/opencode")
        preferences = Path("/Library/Managed Preferences")
        extra = (
            preferences / "ai.opencode.managed.plist",
            preferences / username / "ai.opencode.managed.plist",
        )
    elif sys.platform == "win32":
        root = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "opencode"
        extra = ()
    else:
        root = Path("/etc/opencode")
        extra = ()
    return (root / "opencode.json", root / "opencode.jsonc", *extra)


def opencode_preflight(model: str | None) -> str | None:
    if not model or "/" not in model:
        return "OpenCode isolation requires research.model in provider/model form."
    provider, model_id = model.split("/", 1)
    if provider not in PROVIDER_KEYS or not model_id.strip() or "\x00" in model:
        return "OpenCode supports explicit anthropic, openai, google, or openrouter models."
    for path in managed_config_paths():
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return "Cannot verify the absence of OpenCode system-managed configuration."
        return "OpenCode system-managed configuration can override restrictions; refusing to run."
    if not os.environ.get(PROVIDER_KEYS[provider]):
        return f"OpenCode isolation requires {PROVIDER_KEYS[provider]} in the environment; personal auth files are not loaded."
    return None


def build_opencode(prompt: str, model: str | None, workdir: Path) -> HarnessInvocation:
    from .harnesses import HarnessInvocation

    if problem := opencode_preflight(model):
        raise ValueError(problem)
    assert model is not None
    provider = model.split("/", 1)[0]
    executable = shutil.which("opencode")
    if executable is None:
        raise FileNotFoundError("OpenCode is not installed")
    # An absolute executable still works after replacing PATH and HOME.
    executable = str(Path(executable).absolute())
    env = {"PATH": os.defpath, "NO_COLOR": "1"}
    for key in ("SYSTEMROOT", "WINDIR", "ProgramData"):
        if key in os.environ:
            env[key] = os.environ[key]
    for key, dirname in {
        "HOME": "home", "XDG_CONFIG_HOME": "config", "XDG_DATA_HOME": "data",
        "XDG_CACHE_HOME": "cache", "XDG_STATE_HOME": "state", "TMPDIR": "tmp",
    }.items():
        directory = workdir / dirname
        directory.mkdir(mode=0o700)
        env[key] = str(directory)
    env["TEMP"] = env["TMPDIR"]
    env["TMP"] = env["TMPDIR"]
    # Copy exactly one selected provider credential, never personal config/auth files.
    key = PROVIDER_KEYS[provider]
    env[key] = os.environ[key]
    env.update({
        "OPENCODE_PURE": "true",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "true",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "true",
        "OPENCODE_DISABLE_CLAUDE_CODE": "true",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "true",
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_MODELS_FETCH": "true",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
        "OPENCODE_DISABLE_AUTOCOMPACT": "true",
        "OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER": "true",
    })
    config = {
        "$schema": "https://opencode.ai/config.json",
        "permission": {"*": "deny"},
        "agent": {"rundown": {
            "description": "Text-only research from supplied repository context",
            "mode": "primary", "permission": {"*": "deny"},
        }},
        "enabled_providers": [provider],
        "plugin": [], "mcp": {}, "instructions": [], "share": "disabled",
        "autoupdate": False, "snapshot": False, "lsp": False, "formatter": False,
    }
    config_path = workdir / "rundown.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    env["OPENCODE_CONFIG"] = str(config_path)
    return HarnessInvocation(
        [executable, "run", "--pure", "--format", "json", "--agent", "rundown",
         "--model", model, "--title", "Rundown research"],
        input=prompt, env=env, inherit_env=False,
    )


def decode_opencode(stdout: str) -> HarnessOutput:
    """Decode completed JSONL text parts, never tool output or reasoning."""
    from .harnesses import HarnessOutput

    parts: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("Invalid OpenCode event")
        kind = event.get("type")
        if not isinstance(kind, str):
            raise ValueError("Missing OpenCode event type")
        if kind in {"error", "tool_use"}:
            raise ValueError("OpenCode reported an error or attempted tool use")
        if kind in {"step_start", "step_finish", "reasoning"}:
            continue
        if kind != "text":
            raise ValueError("Unexpected OpenCode event")
        part = event.get("part")
        if not isinstance(part, dict) or not isinstance(part.get("text"), str):
            raise ValueError("Invalid OpenCode text part")
        identifier = part.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("Missing OpenCode text part identifier")
        text = part["text"]
        if identifier in parts and parts[identifier] != text:
            raise ValueError("Conflicting completed OpenCode text parts")
        parts[identifier] = text
    text = "\n".join(parts.values()).strip()
    if not text:
        raise ValueError("OpenCode returned no text")
    # Run events do not attest to the serving model; do not infer it from flags.
    return HarnessOutput(text)


def opencode_adapter() -> HarnessAdapter:
    from .harnesses import HarnessAdapter

    return HarnessAdapter("opencode", "opencode", build_opencode, decode_opencode,
                          preflight=opencode_preflight)
