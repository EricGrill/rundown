"""Tests for GitHub integration."""

import pytest

from rundown.github import parse_repo_identifier


class TestParseRepoIdentifier:
    """Tests for parse_repo_identifier function."""
    
    def test_simple_format(self):
        """Test owner/repo format."""
        owner, name = parse_repo_identifier("octocat/Hello-World")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_https_url(self):
        """Test HTTPS GitHub URL."""
        owner, name = parse_repo_identifier("https://github.com/octocat/Hello-World")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_https_url_with_trailing_slash(self):
        """Test HTTPS URL with trailing slash."""
        owner, name = parse_repo_identifier("https://github.com/octocat/Hello-World/")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_https_url_with_git_suffix(self):
        """Test HTTPS URL with .git suffix."""
        owner, name = parse_repo_identifier("https://github.com/octocat/Hello-World.git")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_http_url(self):
        """Test HTTP GitHub URL."""
        owner, name = parse_repo_identifier("http://github.com/octocat/Hello-World")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_ssh_url(self):
        """Test SSH GitHub URL."""
        owner, name = parse_repo_identifier("git@github.com:octocat/Hello-World.git")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_ssh_url_without_git_suffix(self):
        """Test SSH URL without .git suffix."""
        owner, name = parse_repo_identifier("git@github.com:octocat/Hello-World")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_www_url(self):
        """Test www.github.com URL."""
        owner, name = parse_repo_identifier("https://www.github.com/octocat/Hello-World")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_bare_domain(self):
        """Test github.com without protocol."""
        owner, name = parse_repo_identifier("github.com/octocat/Hello-World")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_with_whitespace(self):
        """Test input with leading/trailing whitespace."""
        owner, name = parse_repo_identifier("  octocat/Hello-World  ")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_complex_url_with_path(self):
        """Test URL with additional path components."""
        owner, name = parse_repo_identifier("https://github.com/octocat/Hello-World/tree/main")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_url_with_issues_path(self):
        """Test URL pointing to issues."""
        owner, name = parse_repo_identifier("https://github.com/octocat/Hello-World/issues/123")
        assert owner == "octocat"
        assert name == "Hello-World"
    
    def test_invalid_format_raises(self):
        """Test invalid format raises ValueError."""
        with pytest.raises(ValueError):
            parse_repo_identifier("not-a-repo")
    
    def test_empty_string_raises(self):
        """Test empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_repo_identifier("")
    
    def test_single_name_raises(self):
        """Test single name without owner raises ValueError."""
        with pytest.raises(ValueError):
            parse_repo_identifier("just-a-name")
    
    def test_hyphenated_names(self):
        """Test repos with hyphens in names."""
        owner, name = parse_repo_identifier("some-org/my-cool-repo")
        assert owner == "some-org"
        assert name == "my-cool-repo"
    
    def test_underscored_names(self):
        """Test repos with underscores in names."""
        owner, name = parse_repo_identifier("some_org/my_cool_repo")
        assert owner == "some_org"
        assert name == "my_cool_repo"
    
    def test_numeric_org(self):
        """Test repos with numeric org names."""
        owner, name = parse_repo_identifier("123/repo")
        assert owner == "123"
        assert name == "repo"
    
    def test_mixed_case(self):
        """Test repos preserve case."""
        owner, name = parse_repo_identifier("MyOrg/MyRepo")
        assert owner == "MyOrg"
        assert name == "MyRepo"
