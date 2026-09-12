"""Tests for the scoring system."""

from datetime import datetime, timedelta, timezone

import pytest

from rundown.config import ScoreWeights
from rundown.models import Repo, Status
from rundown.scoring import (
    calculate_score,
    _calc_freshness,
    _calc_description_quality,
    _calc_readme_signal,
    _calc_stars_normalized,
    _calc_topics_score,
    _calc_issues_ratio,
)


@pytest.fixture
def weights() -> ScoreWeights:
    return ScoreWeights()


@pytest.fixture
def base_repo() -> Repo:
    """Create a base repo for testing."""
    return Repo(
        id=1,
        full_name="test/repo",
        owner="test",
        name="repo",
        url="https://github.com/test/repo",
        description="A test repository for testing",
        stars=100,
        forks=10,
        open_issues=5,
        pushed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc) - timedelta(days=365),
        language="Python",
        license="MIT",
        topics=["python", "testing", "cli"],
        archived=False,
        has_readme=True,
        readme_length=2000,
        status=Status.INBOX,
    )


class TestFreshnessScore:
    """Tests for freshness calculation."""
    
    def test_recent_push_high_score(self, weights: ScoreWeights):
        """Recently pushed repos should score high."""
        pushed_at = datetime.now(timezone.utc)
        score = _calc_freshness(pushed_at, weights.freshness_half_life_days)
        assert score > 90
    
    def test_old_push_low_score(self, weights: ScoreWeights):
        """Old repos should score low."""
        pushed_at = datetime.now(timezone.utc) - timedelta(days=365)
        score = _calc_freshness(pushed_at, weights.freshness_half_life_days)
        assert score < 30
    
    def test_none_pushed_at(self, weights: ScoreWeights):
        """None pushed_at should score 0."""
        score = _calc_freshness(None, weights.freshness_half_life_days)
        assert score == 0
    
    def test_half_life_decay(self, weights: ScoreWeights):
        """Score should be ~50 at half-life."""
        pushed_at = datetime.now(timezone.utc) - timedelta(days=weights.freshness_half_life_days)
        score = _calc_freshness(pushed_at, weights.freshness_half_life_days)
        assert 45 < score < 55


class TestDescriptionQuality:
    """Tests for description quality scoring."""
    
    def test_no_description(self):
        assert _calc_description_quality(None) == 0
        assert _calc_description_quality("") == 0
    
    def test_short_description(self):
        score = _calc_description_quality("Short")
        assert score == 20
    
    def test_medium_description(self):
        score = _calc_description_quality("A medium length description here")
        assert score == 50
    
    def test_good_description(self):
        score = _calc_description_quality("A" * 60)
        assert score == 80
    
    def test_long_description(self):
        score = _calc_description_quality("A" * 150)
        assert score == 100


class TestReadmeSignal:
    """Tests for README scoring."""
    
    def test_no_readme(self):
        assert _calc_readme_signal(False, 0) == 0
    
    def test_readme_exists_unknown_size(self):
        assert _calc_readme_signal(True, 0) == 30
    
    def test_small_readme(self):
        assert _calc_readme_signal(True, 300) == 50
    
    def test_medium_readme(self):
        assert _calc_readme_signal(True, 1500) == 80
    
    def test_large_readme(self):
        assert _calc_readme_signal(True, 5000) == 100


class TestStarsNormalized:
    """Tests for stars scoring with log scale."""
    
    def test_no_stars(self):
        assert _calc_stars_normalized(0) == 0
    
    def test_few_stars(self):
        score = _calc_stars_normalized(10)
        assert 20 < score < 40
    
    def test_moderate_stars(self):
        score = _calc_stars_normalized(100)
        assert 40 < score < 60
    
    def test_many_stars(self):
        score = _calc_stars_normalized(10000)
        assert 90 < score <= 100
    
    def test_viral_stars(self):
        score = _calc_stars_normalized(100000)
        assert score == 100


class TestTopicsScore:
    """Tests for topics scoring."""
    
    def test_no_topics(self):
        assert _calc_topics_score([]) == 0
    
    def test_few_topics(self):
        assert _calc_topics_score(["python"]) == 50
        assert _calc_topics_score(["python", "cli"]) == 50
    
    def test_good_topics(self):
        assert _calc_topics_score(["python", "cli", "tool"]) == 80
    
    def test_many_topics(self):
        topics = ["python", "cli", "tool", "automation", "testing", "devops"]
        assert _calc_topics_score(topics) == 100


class TestIssuesRatio:
    """Tests for issues ratio scoring."""
    
    def test_no_stars(self):
        assert _calc_issues_ratio(10, 0) == 50
    
    def test_low_ratio(self):
        score = _calc_issues_ratio(1, 1000)
        assert score == 100
    
    def test_moderate_ratio(self):
        score = _calc_issues_ratio(50, 500)
        assert score == 80
    
    def test_high_ratio(self):
        score = _calc_issues_ratio(200, 200)
        assert score == 0


class TestCalculateScore:
    """Tests for full score calculation."""
    
    def test_basic_score(self, base_repo: Repo, weights: ScoreWeights):
        """Test that a well-maintained repo gets a good score."""
        score, reason = calculate_score(base_repo, weights)
        assert 50 < score <= 100
        assert "freshness" in reason.lower() or "description" in reason.lower()
    
    def test_archived_penalty(self, base_repo: Repo, weights: ScoreWeights):
        """Archived repos should be penalized."""
        base_repo.archived = False
        score_active, _ = calculate_score(base_repo, weights)
        
        base_repo.archived = True
        score_archived, reason = calculate_score(base_repo, weights)
        
        assert score_archived < score_active
        assert "archived" in reason.lower()
    
    def test_manual_boost_positive(self, base_repo: Repo, weights: ScoreWeights):
        """Positive boost should increase score."""
        base_repo.manual_boost = 0
        score_base, _ = calculate_score(base_repo, weights)
        
        base_repo.manual_boost = 5
        score_boosted, reason = calculate_score(base_repo, weights)
        
        assert score_boosted > score_base
        assert "boost" in reason.lower()
    
    def test_manual_boost_negative(self, base_repo: Repo, weights: ScoreWeights):
        """Negative boost should decrease score."""
        base_repo.manual_boost = 0
        score_base, _ = calculate_score(base_repo, weights)
        
        base_repo.manual_boost = -5
        score_boosted, _ = calculate_score(base_repo, weights)
        
        assert score_boosted < score_base
    
    def test_score_clamped(self, base_repo: Repo, weights: ScoreWeights):
        """Score should be clamped to 0-100."""
        base_repo.manual_boost = 10
        score, _ = calculate_score(base_repo, weights)
        assert 0 <= score <= 100
        
        base_repo.manual_boost = -10
        base_repo.archived = True
        score, _ = calculate_score(base_repo, weights)
        assert 0 <= score <= 100
    
    def test_empty_repo_low_score(self, weights: ScoreWeights):
        """A repo with minimal info should score low."""
        repo = Repo(
            id=1,
            full_name="empty/repo",
            owner="empty",
            name="repo",
            url="https://github.com/empty/repo",
        )
        score, _ = calculate_score(repo, weights)
        assert score < 20
    
    def test_score_reason_includes_top_factors(self, base_repo: Repo, weights: ScoreWeights):
        """Score reason should include top contributing factors."""
        _, reason = calculate_score(base_repo, weights)
        assert "|" in reason
        parts = reason.split("|")
        assert len(parts) >= 1
