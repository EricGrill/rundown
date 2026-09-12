"""Tests for Markdown export functionality."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from rundown.export import export_markdown, format_summary_table, _format_repo
from rundown.models import Repo, Status


@pytest.fixture
def sample_repos() -> list[Repo]:
    """Create sample repos for testing."""
    return [
        Repo(
            id=1,
            full_name="test/awesome",
            owner="test",
            name="awesome",
            url="https://github.com/test/awesome",
            description="An awesome project",
            stars=1000,
            forks=100,
            language="Python",
            license="MIT",
            topics=["python", "awesome", "tool"],
            status=Status.PRESENT,
            present_score=85.0,
            score_reason="freshness(+25): 3d ago | stars(+10): 1,000★",
            hook="The best tool for X",
            who_for="Developers who need Y",
            problem="Solving the Z problem",
            why_now="Just released v2.0",
            demo_path="https://demo.example.com",
            flags=["trending", "sponsor"],
            notes="Worth mentioning the CLI",
        ),
        Repo(
            id=2,
            full_name="test/simple",
            owner="test",
            name="simple",
            url="https://github.com/test/simple",
            description="A simple library",
            stars=50,
            language="JavaScript",
            status=Status.PRESENT,
            present_score=60.0,
            score_reason="freshness(+20): 10d ago",
        ),
    ]


class TestExportMarkdown:
    """Tests for export_markdown function."""
    
    def test_export_basic(self, sample_repos: list[Repo]):
        """Test basic export generates valid markdown."""
        content = export_markdown(sample_repos)
        
        assert "# Rundown" in content
        assert "test/awesome" in content
        assert "test/simple" in content
    
    def test_export_includes_title(self, sample_repos: list[Repo]):
        """Test export includes custom title."""
        content = export_markdown(sample_repos, title="My Rundown")
        assert "# My Rundown" in content
    
    def test_export_includes_date(self, sample_repos: list[Repo]):
        """Test export includes generation date."""
        content = export_markdown(sample_repos)
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in content
    
    def test_export_includes_github_links(self, sample_repos: list[Repo]):
        """Test export includes GitHub links."""
        content = export_markdown(sample_repos)
        assert "https://github.com/test/awesome" in content
        assert "https://github.com/test/simple" in content
    
    def test_export_includes_scores(self, sample_repos: list[Repo]):
        """Test export includes scores by default."""
        content = export_markdown(sample_repos, include_scores=True)
        assert "85" in content
        assert "60" in content
        assert "Score:" in content
    
    def test_export_excludes_scores(self, sample_repos: list[Repo]):
        """Test export can exclude scores."""
        content = export_markdown(sample_repos, include_scores=False)
        assert "📊 Score:" not in content
    
    def test_export_includes_card_fields(self, sample_repos: list[Repo]):
        """Test export includes card fields."""
        content = export_markdown(sample_repos)
        assert "The best tool for X" in content
        assert "Developers who need Y" in content
        assert "Solving the Z problem" in content
        assert "Just released v2.0" in content
    
    def test_export_includes_flags(self, sample_repos: list[Repo]):
        """Test export includes flags."""
        content = export_markdown(sample_repos)
        assert "trending" in content
        assert "sponsor" in content
    
    def test_export_includes_notes(self, sample_repos: list[Repo]):
        """Test export includes notes as blockquote."""
        content = export_markdown(sample_repos)
        assert "> Worth mentioning the CLI" in content
    
    def test_export_includes_demo_path(self, sample_repos: list[Repo]):
        """Test export includes demo path."""
        content = export_markdown(sample_repos)
        assert "https://demo.example.com" in content
    
    def test_export_includes_topics(self, sample_repos: list[Repo]):
        """Test export includes topics."""
        content = export_markdown(sample_repos)
        assert "python" in content
        assert "awesome" in content
    
    def test_export_to_file(self, sample_repos: list[Repo]):
        """Test export writes to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "rundown.md"
            content = export_markdown(sample_repos, output=output_path)
            
            assert output_path.exists()
            assert output_path.read_text() == content
    
    def test_export_creates_parent_dirs(self, sample_repos: list[Repo]):
        """Test export creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "dir" / "rundown.md"
            export_markdown(sample_repos, output=output_path)
            
            assert output_path.exists()
    
    def test_export_empty_list(self):
        """Test export handles empty repo list."""
        content = export_markdown([])
        assert "# Rundown" in content
        assert "---" in content
    
    def test_export_archived_repo(self):
        """Test export shows archived indicator."""
        repo = Repo(
            id=1,
            full_name="old/archived",
            owner="old",
            name="archived",
            url="https://github.com/old/archived",
            archived=True,
            status=Status.PRESENT,
        )
        content = export_markdown([repo])
        assert "Archived" in content or "🗄️" in content


class TestFormatRepo:
    """Tests for _format_repo function."""
    
    def test_format_repo_basic(self, sample_repos: list[Repo]):
        """Test formatting a single repo."""
        lines = _format_repo(sample_repos[0])
        content = "\n".join(lines)
        
        assert "test/awesome" in content
        assert "---" in content
    
    def test_format_repo_uses_hook_over_description(self, sample_repos: list[Repo]):
        """Test that hook is preferred over description."""
        lines = _format_repo(sample_repos[0])
        content = "\n".join(lines)
        
        assert "The best tool for X" in content
    
    def test_format_repo_fallback_to_description(self, sample_repos: list[Repo]):
        """Test fallback to description when no hook."""
        lines = _format_repo(sample_repos[1])
        content = "\n".join(lines)
        
        assert "A simple library" in content


class TestSummaryTable:
    """Tests for format_summary_table function."""
    
    def test_summary_table_headers(self, sample_repos: list[Repo]):
        """Test summary table includes headers."""
        table = format_summary_table(sample_repos)
        
        assert "| Repo |" in table
        assert "| Score |" in table
        assert "| Status |" in table
        assert "| Language |" in table
        assert "| Stars |" in table
    
    def test_summary_table_rows(self, sample_repos: list[Repo]):
        """Test summary table includes repo rows."""
        table = format_summary_table(sample_repos)
        
        assert "awesome" in table
        assert "simple" in table
        assert "85" in table
        assert "present" in table
    
    def test_summary_table_empty(self):
        """Test summary table handles empty list."""
        table = format_summary_table([])
        assert "| Repo |" in table
        assert table.count("\n") == 1


class TestStatusCounts:
    """Tests for status count summary."""
    
    def test_status_counts_in_export(self):
        """Test export includes status counts."""
        repos = [
            Repo(id=1, full_name="a/a", owner="a", name="a", url="", status=Status.PRESENT),
            Repo(id=2, full_name="b/b", owner="b", name="b", url="", status=Status.PRESENT),
            Repo(id=3, full_name="c/c", owner="c", name="c", url="", status=Status.SHORTLIST),
        ]
        content = export_markdown(repos)
        
        assert "3 repos" in content
