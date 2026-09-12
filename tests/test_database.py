"""Tests for database operations."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rundown.database import Database
from rundown.models import Repo, Status


@pytest.fixture
def db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield Database(db_path)


@pytest.fixture
def sample_repo() -> Repo:
    """Create a sample repo for testing."""
    return Repo(
        full_name="test/sample",
        owner="test",
        name="sample",
        url="https://github.com/test/sample",
        description="A sample repo",
        stars=100,
        forks=10,
        open_issues=5,
        pushed_at=datetime.now(timezone.utc),
        language="Python",
        license="MIT",
        topics=["python", "testing"],
        status=Status.INBOX,
        present_score=75.0,
        score_reason="test reason",
    )


class TestRepoOperations:
    """Tests for basic repo CRUD operations."""
    
    def test_upsert_new_repo(self, db: Database, sample_repo: Repo):
        """Test inserting a new repo."""
        saved = db.upsert_repo(sample_repo)
        
        assert saved.id is not None
        assert saved.full_name == "test/sample"
        assert saved.status == Status.INBOX
    
    def test_upsert_existing_repo(self, db: Database, sample_repo: Repo):
        """Test updating an existing repo preserves user fields."""
        saved = db.upsert_repo(sample_repo)
        repo_id = saved.id
        
        db.update_status(repo_id, Status.SHORTLIST)
        db.update_card(repo_id, hook="Test hook", notes="Test notes")
        
        sample_repo.stars = 200
        sample_repo.description = "Updated description"
        updated = db.upsert_repo(sample_repo)
        
        assert updated.id == repo_id
        assert updated.stars == 200
        assert updated.status == Status.SHORTLIST
        assert updated.hook == "Test hook"
        assert updated.notes == "Test notes"
    
    def test_get_repo(self, db: Database, sample_repo: Repo):
        """Test retrieving a repo by full name."""
        db.upsert_repo(sample_repo)
        
        fetched = db.get_repo("test/sample")
        assert fetched is not None
        assert fetched.full_name == "test/sample"
        assert fetched.stars == 100
    
    def test_get_repo_not_found(self, db: Database):
        """Test retrieving a non-existent repo."""
        fetched = db.get_repo("nonexistent/repo")
        assert fetched is None
    
    def test_get_repo_by_id(self, db: Database, sample_repo: Repo):
        """Test retrieving a repo by ID."""
        saved = db.upsert_repo(sample_repo)
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched is not None
        assert fetched.full_name == "test/sample"
    
    def test_list_repos(self, db: Database):
        """Test listing all repos."""
        for i in range(5):
            repo = Repo(
                full_name=f"test/repo{i}",
                owner="test",
                name=f"repo{i}",
                url=f"https://github.com/test/repo{i}",
                present_score=float(i * 20),
            )
            db.upsert_repo(repo)
        
        repos = db.list_repos()
        assert len(repos) == 5
        assert repos[0].present_score > repos[-1].present_score
    
    def test_list_repos_by_status(self, db: Database):
        """Test filtering repos by status."""
        statuses = [Status.INBOX, Status.SHORTLIST, Status.INBOX]
        for i, status in enumerate(statuses):
            repo = Repo(
                full_name=f"test/repo{i}",
                owner="test",
                name=f"repo{i}",
                url=f"https://github.com/test/repo{i}",
                status=status,
            )
            db.upsert_repo(repo)
        
        inbox_repos = db.list_repos(status=Status.INBOX)
        assert len(inbox_repos) == 2
        
        shortlist_repos = db.list_repos(status=Status.SHORTLIST)
        assert len(shortlist_repos) == 1


class TestStatusOperations:
    """Tests for status-related operations."""
    
    def test_update_status(self, db: Database, sample_repo: Repo):
        """Test updating repo status."""
        saved = db.upsert_repo(sample_repo)
        assert saved.status == Status.INBOX
        
        db.update_status(saved.id, Status.SHORTLIST)
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.status == Status.SHORTLIST
    
    def test_status_transitions(self, db: Database, sample_repo: Repo):
        """Test all status transitions are valid."""
        saved = db.upsert_repo(sample_repo)
        
        for status in Status:
            db.update_status(saved.id, status)
            fetched = db.get_repo_by_id(saved.id)
            assert fetched.status == status
    
    def test_count_by_status(self, db: Database):
        """Test counting repos by status."""
        statuses = [Status.INBOX, Status.INBOX, Status.SHORTLIST, Status.PRESENT]
        for i, status in enumerate(statuses):
            repo = Repo(
                full_name=f"test/repo{i}",
                owner="test",
                name=f"repo{i}",
                url=f"https://github.com/test/repo{i}",
                status=status,
            )
            db.upsert_repo(repo)
        
        counts = db.count_by_status()
        assert counts[Status.INBOX] == 2
        assert counts[Status.SHORTLIST] == 1
        assert counts[Status.PRESENT] == 1
        assert counts[Status.HOLD] == 0
        assert counts[Status.SKIP] == 0


class TestCardOperations:
    """Tests for card field operations."""
    
    def test_update_card_fields(self, db: Database, sample_repo: Repo):
        """Test updating individual card fields."""
        saved = db.upsert_repo(sample_repo)
        
        db.update_card(
            saved.id,
            hook="Amazing tool for X",
            who_for="Developers",
            problem="Solves Y problem",
            why_now="Trending now",
        )
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.hook == "Amazing tool for X"
        assert fetched.who_for == "Developers"
        assert fetched.problem == "Solves Y problem"
        assert fetched.why_now == "Trending now"
    
    def test_update_card_partial(self, db: Database, sample_repo: Repo):
        """Test updating only some card fields."""
        saved = db.upsert_repo(sample_repo)
        
        db.update_card(saved.id, hook="First hook")
        db.update_card(saved.id, notes="Some notes")
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.hook == "First hook"
        assert fetched.notes == "Some notes"
    
    def test_update_card_flags(self, db: Database, sample_repo: Repo):
        """Test updating flags as a list."""
        saved = db.upsert_repo(sample_repo)
        
        db.update_card(saved.id, flags=["beta", "sponsor", "trending"])
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.flags == ["beta", "sponsor", "trending"]


class TestBoostOperations:
    """Tests for manual boost operations."""
    
    def test_update_manual_boost(self, db: Database, sample_repo: Repo):
        """Test updating manual boost."""
        saved = db.upsert_repo(sample_repo)
        
        db.update_manual_boost(saved.id, 5)
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.manual_boost == 5
    
    def test_update_manual_boost_negative(self, db: Database, sample_repo: Repo):
        """Test negative manual boost."""
        saved = db.upsert_repo(sample_repo)
        
        db.update_manual_boost(saved.id, -3)
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.manual_boost == -3


class TestScoreOperations:
    """Tests for score operations."""
    
    def test_update_score(self, db: Database, sample_repo: Repo):
        """Test updating score and reason."""
        saved = db.upsert_repo(sample_repo)
        
        db.update_score(saved.id, 85.5, "high freshness | good readme")
        
        fetched = db.get_repo_by_id(saved.id)
        assert fetched.present_score == 85.5
        assert fetched.score_reason == "high freshness | good readme"


class TestDeleteOperations:
    """Tests for delete operations."""
    
    def test_delete_repo(self, db: Database, sample_repo: Repo):
        """Test deleting a repo."""
        saved = db.upsert_repo(sample_repo)
        repo_id = saved.id
        
        assert db.get_repo_by_id(repo_id) is not None
        
        db.delete_repo(repo_id)
        
        assert db.get_repo_by_id(repo_id) is None
