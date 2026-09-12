from rundown import db


def test_upsert_repo_is_idempotent_and_preserves_user_fields(tmp_path):
    database = tmp_path / "app.sqlite"
    repo = db.RepoInput(
        full_name="owner/project",
        owner="owner",
        repo="project",
        url="https://github.com/owner/project",
        description="old",
        language="Python",
        stars=10,
        starred_at="2024-01-02T03:04:05Z",
    )

    with db.session(database) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(conn, repo)
        db.update_repo(
            conn,
            "owner/project",
            tags="agent",
            notes="keep this",
            decision="watch",
            relevance_score=42,
            wiki_path="wiki/repos/owner__project.md",
        )
        db.upsert_repo(
            conn,
            db.RepoInput(
                full_name="owner/project",
                owner="owner",
                repo="project",
                url="https://github.com/owner/project",
                description="new",
                language="Rust",
                stars=25,
                starred_at="2025-06-07T08:09:10Z",
            ),
        )
        rows = conn.execute("SELECT * FROM repos").fetchall()

    assert len(rows) == 1
    assert rows[0]["id"] == repo_id
    assert rows[0]["description"] == "new"
    assert rows[0]["language"] == "Rust"
    assert rows[0]["starred_at"] == "2025-06-07T08:09:10Z"
    assert rows[0]["tags"] == "agent"
    assert rows[0]["notes"] == "keep this"
    assert rows[0]["decision"] == "watch"
    assert rows[0]["relevance_score"] == 42
    assert rows[0]["wiki_path"] == "wiki/repos/owner__project.md"


def test_mark_unstarred_missing_leaves_known_synced_repos(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(conn, db.RepoInput("a/one", "a", "one", "https://github.com/a/one"))
        db.upsert_repo(conn, db.RepoInput("b/two", "b", "two", "https://github.com/b/two"))
        count = db.mark_unstarred_missing(conn, {"a/one"})
        one = db.get_repo(conn, "a/one")
        two = db.get_repo(conn, "b/two")

    assert count == 1
    assert one["starred"] == 1
    assert two["starred"] == 0


def test_mark_unstarred_missing_empty_sync_marks_all_starred_unstarred(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        db.upsert_repo(conn, db.RepoInput("a/one", "a", "one", "https://github.com/a/one"))
        db.upsert_repo(conn, db.RepoInput("b/two", "b", "two", "https://github.com/b/two"))
        count = db.mark_unstarred_missing(conn, set())
        rows = conn.execute("SELECT starred FROM repos ORDER BY full_name").fetchall()

    assert count == 2
    assert [row["starred"] for row in rows] == [0, 0]


def test_init_db_adds_starred_at_to_existing_database(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        conn.executescript(db.SCHEMA.replace("    starred_at TEXT,\n", ""))
        assert "starred_at" not in {
            row["name"] for row in conn.execute("PRAGMA table_info(repos)").fetchall()
        }

        db.init_db(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(repos)").fetchall()}

    assert "starred_at" in columns


def test_init_db_adds_research_fingerprint_to_existing_database(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        conn.executescript(db.SCHEMA.replace("    source_fingerprint TEXT,\n", ""))
        db.init_db(conn)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(research_logs)").fetchall()
        }

    assert "source_fingerprint" in columns


def test_init_db_adds_card_storage_to_existing_database(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        legacy_schema = db.SCHEMA.replace("    card_json TEXT,\n", "").split(
            "CREATE TABLE IF NOT EXISTS repo_cards"
        )[0]
        conn.executescript(legacy_schema)

        db.init_db(conn)
        research_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(research_logs)")
        }
        card_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(repo_cards)")
        }

    assert "card_json" in research_columns
    assert card_columns == {"repo_id", "view", "host_notes"}


def test_repo_card_partial_upserts_preserve_other_field(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(
            conn,
            db.RepoInput("a/one", "a", "one", "https://github.com/a/one"),
        )

        db.save_repo_card(conn, repo_id, host_notes="Opening angle")
        after_notes_only = dict(db.get_repo_card(conn, repo_id))
        db.save_repo_card(conn, repo_id, view="research")
        after_view = dict(db.get_repo_card(conn, repo_id))
        db.save_repo_card(conn, repo_id, host_notes="Revised notes")
        after_notes = dict(db.get_repo_card(conn, repo_id))

    assert after_notes_only == {
        "repo_id": repo_id,
        "view": None,
        "host_notes": "Opening angle",
    }
    assert after_view == {
        "repo_id": repo_id,
        "view": "research",
        "host_notes": "Opening angle",
    }
    assert after_notes == {
        "repo_id": repo_id,
        "view": "research",
        "host_notes": "Revised notes",
    }


def test_notes_only_ignores_legacy_view_default(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        conn.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS repo_cards")[0])
        conn.execute(
            """
            CREATE TABLE repo_cards (
                repo_id INTEGER PRIMARY KEY,
                view TEXT DEFAULT 'host',
                host_notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(repo_id) REFERENCES repos(id)
            )
            """
        )
        db.init_db(conn)
        repo_id = db.upsert_repo(
            conn,
            db.RepoInput("a/one", "a", "one", "https://github.com/a/one"),
        )

        db.save_repo_card(conn, repo_id, host_notes="Use configured default view")
        saved = dict(db.get_repo_card(conn, repo_id))

    assert saved["view"] is None
    assert saved["host_notes"] == "Use configured default view"


def test_repo_card_supports_prior_not_null_view_schema(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        conn.executescript(db.SCHEMA.split("CREATE TABLE IF NOT EXISTS repo_cards")[0])
        conn.execute(
            """
            CREATE TABLE repo_cards (
                repo_id INTEGER PRIMARY KEY,
                view TEXT NOT NULL DEFAULT 'host',
                host_notes TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(repo_id) REFERENCES repos(id)
            )
            """
        )
        db.init_db(conn)
        inherited_repo_id = db.upsert_repo(
            conn,
            db.RepoInput("a/one", "a", "one", "https://github.com/a/one"),
        )
        selected_repo_id = db.upsert_repo(
            conn,
            db.RepoInput("b/two", "b", "two", "https://github.com/b/two"),
        )

        db.save_repo_card(conn, inherited_repo_id, host_notes="Legacy initial note")
        db.save_repo_card(
            conn,
            selected_repo_id,
            view="research",
            host_notes="Research view note",
        )
        db.save_repo_card(conn, selected_repo_id, host_notes="Revised research note")
        inherited = dict(db.get_repo_card(conn, inherited_repo_id))
        selected = dict(db.get_repo_card(conn, selected_repo_id))

    assert inherited["view"] == "host"
    assert inherited["host_notes"] == "Legacy initial note"
    assert selected["view"] == "research"
    assert selected["host_notes"] == "Revised research note"


def test_repo_card_rejects_unknown_view(tmp_path):
    database = tmp_path / "app.sqlite"
    with db.session(database) as conn:
        db.init_db(conn)
        repo_id = db.upsert_repo(
            conn,
            db.RepoInput("a/one", "a", "one", "https://github.com/a/one"),
        )

        try:
            db.save_repo_card(conn, repo_id, view="slides")
        except ValueError as exc:
            assert "host" in str(exc) and "research" in str(exc)
        else:
            raise AssertionError("invalid card view was accepted")
