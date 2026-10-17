"""Checks against the real mirrors. Run on demand: ``pytest -m network``."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from vcbuilder.resources import lock_path
from vcbuilder.sources import load_lock

LOCK = load_lock(lock_path())
GIT_MIRRORS = [(source.name, url, source.commit) for source in (LOCK.revc, LOCK.librw) for url in source.urls]


@pytest.mark.network
@pytest.mark.parametrize("name,url,commit", GIT_MIRRORS, ids=[f"{n}:{u}" for n, u, _ in GIT_MIRRORS])
def test_every_git_mirror_contains_its_pinned_commit(name, url, commit):
    """Mirror rule (spec section 5): the pinned commit must be reachable from a branch of the mirror.

    The mirror is cloned without trees or blobs, so only commits that its own refs reach are
    present; ``branch --contains`` then proves reachability rather than just object presence.
    """
    with tempfile.TemporaryDirectory() as scratch:
        clone = Path(scratch) / "mirror.git"
        subprocess.run(
            ["/usr/bin/git", "clone", "--quiet", "--bare", "--filter=tree:0", url, str(clone)],
            check=True,
            timeout=600,
        )
        branches = subprocess.run(
            ["/usr/bin/git", "-C", str(clone), "branch", "--contains", commit],
            capture_output=True,
            text=True,
        )
        assert branches.returncode == 0 and branches.stdout.strip(), f"{commit} is not on any branch of {url}"


ARCHIVE_URLS = [(a.name, url, a.sha256) for a in LOCK.archives for url in a.urls]


@pytest.mark.network
@pytest.mark.parametrize("name,url,digest", ARCHIVE_URLS, ids=[f"{n}:{u}" for n, u, _ in ARCHIVE_URLS])
def test_every_archive_url_serves_the_pinned_file(name, url, digest, tmp_path):
    target = tmp_path / "download"
    subprocess.run(["/usr/bin/curl", "--fail", "--location", "--silent", "--show-error", "-o", str(target), url],
                   check=True, timeout=600)
    import hashlib

    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
