"""Offline check of an installed OpenCode's effective Rundown permissions.

This invokes debug commands only. It never starts a research/model request.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rundown.opencode_harness import build_opencode
from rundown.processes import run_command


def main() -> None:
    executable = shutil.which("opencode")
    if not executable:
        raise SystemExit("opencode is not installed")
    with TemporaryDirectory(prefix="rundown-opencode-check-") as directory:
        # A dummy key permits provider discovery in debug agent. Debug commands
        # resolve configuration/tools only and do not request model completions.
        with patch.dict(os.environ, {"OPENAI_API_KEY": "offline-not-a-credential"}):
            invocation = build_opencode("unused", "openai/offline", Path(directory))
        env = dict(invocation.env)

        version = run_command([executable, "--version"], env=env, cwd=directory,
                              text=True, capture_output=True, timeout=30, check=True)
        config_result = run_command([executable, "debug", "config"], env=env, cwd=directory,
                                    text=True, capture_output=True, timeout=30, check=True)
        config = json.loads(config_result.stdout)
        assert config["permission"] == {"*": "deny"}, "Global permissions changed"
        assert not config.get("plugin"), "Plugins loaded"
        assert not config.get("mcp"), "MCP servers loaded"
        result = run_command([executable, "debug", "agent", "rundown"], env=env, cwd=directory,
                             text=True, capture_output=True, timeout=30, check=True)
        agent = json.loads(result.stdout)
        tools = agent.get("tools")
        assert isinstance(tools, dict) and tools, "Debug output has no tool map"
        assert all(value is False for value in tools.values()), "Enabled tools found"
        print(json.dumps({"version": version.stdout.strip(), "tools": tools,
                          "plugins": config.get("plugin", []), "mcp": config.get("mcp", {}),
                          "inference_performed": False}, indent=2))


if __name__ == "__main__":
    main()
