import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def inside_git_repo():
    try:
        _git("rev-parse", "--is-inside-work-tree")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("not running inside a git checkout")


def test_no_file_under_data_private_is_tracked(inside_git_repo):
    """Personal statements live in data/private/ and must never be committed."""
    assert _git("ls-files", "data/private").strip() == ""


def test_data_private_is_gitignored(inside_git_repo):
    result = subprocess.run(["git", "check-ignore", "-q", "data/private/real_labeled.csv"], cwd=ROOT)
    assert result.returncode == 0


def test_data_private_is_excluded_from_docker_builds():
    assert "data/private" in (ROOT / ".dockerignore").read_text().splitlines()
