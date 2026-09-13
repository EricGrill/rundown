from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys

from rundown import db
from rundown.config import load_config
from rundown.mcp_server import MAX_INPUT_LINE_BYTES, PROTOCOL_VERSION, serve


def _frame(request_id: object, method: str, params: object | None = None) -> str:
    request: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return json.dumps(request)


def _initialized() -> str:
    return json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _initialize_params(version: str = PROTOCOL_VERSION) -> dict[str, object]:
    return {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1"},
    }


def _run_in_process(tmp_path: Path, lines: list[str]) -> list[dict[str, object]]:
    config_file = tmp_path / "config" / "rundown.toml"
    config_file.parent.mkdir()
    config_file.write_text('[paths]\ndatabase = "missing.sqlite"\n', encoding="utf-8")
    output = StringIO()
    serve(load_config(config_file), StringIO("\n".join(lines) + "\n"), output)
    return [json.loads(line) for line in output.getvalue().splitlines()]


def test_lifecycle_tools_and_protocol_errors(tmp_path):
    frames = _run_in_process(
        tmp_path,
        [
            "not-json",
            "{}",
            _frame(1, "tools/list"),
            _frame(
                2,
                "initialize",
                _initialize_params("2099-01-01"),
            ),
            _initialized(),
            json.dumps({"jsonrpc": "2.0", "method": "tools/list"}),
            _frame(3, "ping"),
            _frame(4, "tools/list"),
            _frame(5, "missing/method"),
            _frame(
                6,
                "tools/call",
                {"name": "search_saved", "arguments": {"query": "python", "limit": True}},
            ),
            _frame(7, "tools/call", {"name": "missing", "arguments": {}}),
        ],
    )

    assert [frame.get("id") for frame in frames] == [None, None, 1, 2, 3, 4, 5, 6, 7]
    assert frames[0]["error"]["code"] == -32700
    assert frames[1]["error"]["code"] == -32600
    assert frames[2]["error"]["code"] == -32600
    assert frames[3]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert frames[3]["result"]["serverInfo"]["name"] == "rundown"
    assert frames[4]["result"] == {}
    tools = frames[5]["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "search_saved",
        "inspect_repo",
        "recall_decisions",
        "project_digest",
    }
    assert all(tool["annotations"]["readOnlyHint"] is True for tool in tools)
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
    assert frames[6]["error"]["code"] == -32601
    assert frames[7]["error"]["code"] == -32602
    assert "integer" in frames[7]["error"]["message"]
    assert frames[8]["error"]["code"] == -32602
    assert not (tmp_path / "missing.sqlite").exists()


def test_tool_business_error_and_strict_arguments(tmp_path):
    frames = _run_in_process(
        tmp_path,
        [
            _frame(1, "initialize", _initialize_params()),
            _initialized(),
            _frame(
                2,
                "tools/call",
                {"name": "inspect_repo", "arguments": {"full_name": "missing/repo"}},
            ),
            _frame(
                3,
                "tools/call",
                {"name": "search_saved", "arguments": {"query": "x", "surprise": 1}},
            ),
        ],
    )

    business = frames[1]["result"]
    assert business["isError"] is True
    assert business["structuredContent"]["error"]["code"] == "not_found"
    assert json.loads(business["content"][0]["text"]) == business["structuredContent"]
    assert frames[2]["error"]["code"] == -32602
    assert "surprise" in frames[2]["error"]["message"]


def test_oversized_line_is_drained_before_next_frame(tmp_path):
    oversized = "{" + ("x" * MAX_INPUT_LINE_BYTES) + "}"
    frames = _run_in_process(
        tmp_path,
        [oversized, _frame(1, "initialize", _initialize_params())],
    )

    assert frames[0]["error"]["code"] == -32700
    assert frames[1]["id"] == 1


def test_real_subprocess_searches_and_inspects_read_only_catalog(tmp_path):
    config_file = tmp_path / "config" / "rundown.toml"
    config_file.parent.mkdir()
    config_file.write_text('[paths]\ndatabase = "data/catalog.sqlite"\n', encoding="utf-8")
    database = tmp_path / "data" / "catalog.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="acme/queue",
                owner="acme",
                repo="queue",
                url="https://github.com/acme/queue",
                description="Python background jobs",
                language="Python",
            ),
        )
    before = database.stat()
    untouched = tmp_path / "repos"
    requests = [
        _frame(
            1,
            "initialize",
            _initialize_params(),
        ),
        _initialized(),
        _frame(2, "tools/list"),
        _frame(
            3,
            "tools/call",
            {"name": "search_saved", "arguments": {"query": "pythn jobs", "limit": 2}},
        ),
        _frame(
            4,
            "tools/call",
            {"name": "inspect_repo", "arguments": {"full_name": "acme/queue"}},
        ),
        _frame(5, "tools/call", {"name": "recall_decisions", "arguments": {}}),
        _frame(6, "tools/call", {"name": "project_digest", "arguments": {"limit": 1}}),
    ]
    script = (
        "import sys; from pathlib import Path; "
        "from rundown.config import load_config; from rundown.mcp_server import serve; "
        "serve(load_config(Path(sys.argv[1])))"
    )
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_root, environment.get("PYTHONPATH", "")) if item
    )

    completed = subprocess.run(
        [sys.executable, "-c", script, str(config_file)],
        input="\n".join(requests) + "\n",
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [item["id"] for item in responses] == [1, 2, 3, 4, 5, 6]
    search = responses[2]["result"]
    assert search["isError"] is False
    assert search["structuredContent"]["results"][0]["full_name"] == "acme/queue"
    inspection = responses[3]["result"]
    assert inspection["isError"] is False
    assert inspection["structuredContent"]["repository"] == "acme/queue"
    recall = responses[4]["result"]
    assert recall["isError"] is False
    assert recall["structuredContent"]["results"] == []
    digest = responses[5]["result"]
    assert digest["isError"] is False
    assert digest["structuredContent"]["results"][0]["full_name"] == "acme/queue"
    after = database.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert not untouched.exists()


def test_invalid_json_constants_and_recursive_payload_do_not_stop_server(tmp_path):
    frames = _run_in_process(tmp_path, [
        '{"jsonrpc":"2.0","id":NaN,"method":"initialize"}',
        '[' * 20000 + '0' + ']' * 20000,
        _frame(1, 'initialize', _initialize_params()),
        _initialized(),
        _frame(2, 'ping'),
    ])
    assert frames[0]['error']['code'] == -32700
    assert frames[1]['error']['code'] == -32700
    assert frames[-1] == {'jsonrpc': '2.0', 'id': 2, 'result': {}}


def test_nonfinite_saved_score_is_contained_as_tool_error(tmp_path):
    from rundown.config import AppConfig
    config = AppConfig(root=tmp_path)
    with db.session(config.database_path) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(conn, db.RepoInput('a/b', 'a', 'b', 'https://github.com/a/b'))
        conn.execute('UPDATE repos SET relevance_score=? WHERE id=?', (float('inf'), repo_id))
    output = StringIO()
    requests = [_frame(1, 'initialize', _initialize_params()), _initialized(),
                _frame(2, 'tools/call', {'name': 'project_digest', 'arguments': {}}),
                _frame(3, 'ping')]
    serve(config, StringIO('\n'.join(requests) + '\n'), output)
    def reject_constant(value):
        raise AssertionError(value)
    frames = [json.loads(line, parse_constant=reject_constant) for line in output.getvalue().splitlines()]
    assert frames[1]['result']['isError'] is True
    assert frames[-1] == {'jsonrpc': '2.0', 'id': 3, 'result': {}}
