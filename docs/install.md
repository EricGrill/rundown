# Install and upgrade Rundown

Rundown requires Python 3.11 or newer, Git, and GitHub CLI for star synchronization. Research generation also needs an authenticated Claude, Gemini, or Codex CLI. The offline demo and previously saved research do not need those services.

## Install from GitHub

Use `uv` for an isolated command installation:

```console
uv tool install git+https://github.com/EricGrill/rundown.git
rd doctor
rd demo
```

The equivalent `pipx` command is:

```console
pipx install git+https://github.com/EricGrill/rundown.git
rd doctor
```

<!-- 
## Install from PyPI (coming soon)

Once published, the preferred install will be:

```console
uv tool install gh-rundown
```

Or with pipx:

```console
pipx install gh-rundown
```

The CLI commands remain `rundown` and `rd` regardless of install method.
-->

## Upgrade

```console
uv tool upgrade rundown
```

For `pipx`, run `pipx upgrade rundown`. Rundown applies additive SQLite schema updates when it opens an existing catalog. Back up `data/rundown.sqlite` before moving between major versions.

## Develop and verify

```console
uv venv
uv pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check src tests scripts
.venv/bin/pyright --pythonpath .venv/bin/python
.venv/bin/python scripts/capture_tui.py
.venv/bin/python -m build
.venv/bin/python scripts/verify_release.py dist
```

The demo fixture is bundled in the wheel. `rd demo` uses a temporary database and never reads the normal catalog, calls GitHub, clones repositories, or invokes an AI provider.

When an intentional TUI change has been visually reviewed, refresh the committed SVG baselines and README screenshots with `python scripts/capture_tui.py --update-baselines --png`. The default command compares twelve wide, compact, and modal views against those baselines and never changes files.

## Publish a GitHub release

1. Confirm the version matches in `pyproject.toml` and `src/rundown/__init__.py`.
2. Run the full verification commands above and install the built wheel in a clean environment.
3. Commit the release, then create and push an annotated tag such as `v0.2.0`.
4. The release workflow verifies the tag, rebuilds the artifacts, and creates the GitHub release with the wheel and source distribution.

## Publish to PyPI

> **Note:** The PyPI package name is `gh-rundown` (the name `rundown` is taken by an unrelated project).

### First-time setup (trusted publishing)

1. Create a PyPI account at https://pypi.org/
2. Go to Account Settings → Publishing → Add a new pending publisher
3. Configure trusted publishing:
   - PyPI project name: `gh-rundown`
   - Owner: `EricGrill`
   - Repository: `rundown`
   - Workflow name: `release.yml`
   - Environment name: `pypi` (optional)

### Manual publish (for first release or testing)

```console
python -m build
twine check dist/*
twine upload dist/*
```

### Automated publish via GitHub Actions

After trusted publishing is configured, add to `.github/workflows/release.yml`:

```yaml
- name: Publish to PyPI
  uses: pypa/gh-action-pypi-publish@release/v1
  with:
    packages-dir: dist/
```

### Post-publish verification

```console
pipx install gh-rundown
rd doctor
rd demo
```

## Homebrew installation (planned)

A Homebrew formula will be available via a tap:

```console
brew tap EricGrill/tap
brew install gh-rundown
```

See [Homebrew formula draft](#homebrew-formula-draft) below for the formula template. The tap repository (`EricGrill/homebrew-tap`) needs to be created before this install method works.

## Homebrew formula draft

This formula template can be used once a stable release is tagged and the tap repo exists:

```ruby
class GhRundown < Formula
  include Language::Python::Virtualenv

  desc "Turn GitHub stars into research cards and host briefs in the terminal"
  homepage "https://github.com/EricGrill/rundown"
  url "https://github.com/EricGrill/rundown/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "COMPUTE_AFTER_TAGGING"
  license "MIT"
  head "https://github.com/EricGrill/rundown.git", branch: "main"

  depends_on "python@3.11"

  resource "rich" do
    url "https://files.pythonhosted.org/packages/..."
    sha256 "..."
  end

  resource "textual" do
    url "https://files.pythonhosted.org/packages/..."
    sha256 "..."
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/..."
    sha256 "..."
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Rundown", shell_output("#{bin}/rd --version")
    system bin/"rd", "doctor", "--json"
  end
end
```

To compute resource URLs and SHA256 hashes, use `poet`:

```console
pip install homebrew-pypi-poet
poet gh-rundown
```
