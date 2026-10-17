from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from tests.conftest import commit_all, git, make_repo
from vcbuilder.errors import IntegrityError, LockError, SourceUnavailableError
from vcbuilder.resources import lock_path
from vcbuilder.runner import CommandRunner
from vcbuilder.sources import (
    ArchiveSource,
    GitSource,
    MirrorUnavailable,
    extract_archive,
    fetch_archive,
    fetch_git,
    fetch_revc,
    fetch_with_fallback,
    load_lock,
    parse_lock,
    sha256_file,
    verify_sha256,
)

SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST = "c" * 64

VALID_LOCK = f"""
[sources.revc]
type = "git"
urls = ["https://example.invalid/one/reVC.git", "https://example.invalid/two/reVC.git"]
commit = "{SHA_A}"

[sources.librw]
type = "git"
urls = ["https://example.invalid/one/librw.git"]
commit = "{SHA_B}"
path = "vendor/librw"

[sources.glfw]
type = "archive"
version = "3.5.1"
urls = ["https://example.invalid/glfw-3.5.1.zip"]
sha256 = "{DIGEST}"
"""


def test_parse_lock():
    lock = parse_lock(VALID_LOCK)
    assert lock.revc == GitSource(
        name="revc",
        urls=("https://example.invalid/one/reVC.git", "https://example.invalid/two/reVC.git"),
        commit=SHA_A,
        path=None,
    )
    assert lock.librw.path == "vendor/librw"
    assert lock.librw.commit == SHA_B
    glfw = lock.archive("glfw")
    assert glfw == ArchiveSource(
        name="glfw",
        version="3.5.1",
        urls=("https://example.invalid/glfw-3.5.1.zip",),
        sha256=DIGEST,
    )
    assert glfw.filename == "glfw-3.5.1.zip"


@pytest.mark.parametrize(
    "broken",
    [
        VALID_LOCK.replace(f'commit = "{SHA_A}"', 'commit = "main"'),
        VALID_LOCK.replace(f'sha256 = "{DIGEST}"', 'sha256 = "1234"'),
        VALID_LOCK.replace('urls = ["https://example.invalid/glfw-3.5.1.zip"]', "urls = []"),
        VALID_LOCK.replace('type = "archive"', 'type = "svn"'),
        VALID_LOCK.replace("[sources.librw]", "[sources.other]"),
        "this is not toml = = =",
    ],
)
def test_parse_lock_rejects_invalid_entries(broken):
    with pytest.raises(LockError):
        parse_lock(broken)


def test_repository_lock_file_is_valid():
    lock = load_lock(lock_path())
    assert lock.revc.urls[0] == "https://github.com/mrxenginner/reVC.git"
    assert lock.revc.commit == "a26fff4af555a8a425ac9f17d1dd718d00d1f942"
    assert lock.librw.urls[0] == "https://github.com/mrxenginner/librw.git"
    assert lock.librw.commit == "0ad67ee226ea51beb3f465cb8857195e4db16029"
    assert lock.librw.path == "vendor/librw"
    assert {archive.name for archive in lock.archives} == {"glfw", "openal-soft", "mpg123"}
    for url in [*lock.revc.urls, *lock.librw.urls] + [u for a in lock.archives for u in a.urls]:
        assert url.startswith("https://")


def test_sha256_matching_and_wrong(tmp_path):
    path = tmp_path / "blob"
    path.write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    assert sha256_file(path) == digest
    assert verify_sha256(path, digest)
    assert verify_sha256(path, digest.upper())
    assert not verify_sha256(path, "0" * 64)


def test_fallback_tries_mirrors_in_order_until_one_works():
    tried = []

    def attempt(url):
        tried.append(url)
        if url != "c":
            raise MirrorUnavailable(f"{url} unreachable")
        return "fetched from c"

    assert fetch_with_fallback(["a", "b", "c", "d"], attempt) == "fetched from c"
    assert tried == ["a", "b", "c"]


def test_fallback_gives_up_when_every_mirror_is_unreachable():
    tried = []

    def attempt(url):
        tried.append(url)
        raise MirrorUnavailable("down")

    with pytest.raises(SourceUnavailableError):
        fetch_with_fallback(["a", "b"], attempt)
    assert tried == ["a", "b"]


def test_mismatch_stops_without_trying_the_next_mirror():
    tried = []

    def attempt(url):
        tried.append(url)
        if url == "a":
            raise MirrorUnavailable("down")
        raise IntegrityError("wrong content")

    with pytest.raises(IntegrityError):
        fetch_with_fallback(["a", "b", "c"], attempt)
    assert tried == ["a", "b"]


def _archive_source(data: bytes, urls: list[str], digest: str | None = None) -> ArchiveSource:
    return ArchiveSource(
        name="dep",
        version="1.0",
        urls=tuple(urls),
        sha256=digest or hashlib.sha256(data).hexdigest(),
    )


def test_fetch_archive_with_matching_sha(tmp_path):
    data = b"archive bytes"
    source = _archive_source(data, ["https://mirror.invalid/dep-1.0.tar.gz"])

    def download(url, destination: Path):
        destination.write_bytes(data)

    archive = fetch_archive(source, tmp_path, download=download)
    assert archive == tmp_path / "dep-1.0.tar.gz"
    assert archive.read_bytes() == data


def test_fetch_archive_skips_unreachable_mirrors(tmp_path):
    data = b"archive bytes"
    source = _archive_source(data, ["https://down.invalid/dep-1.0.tar.gz", "https://up.invalid/dep-1.0.tar.gz"])
    tried = []

    def download(url, destination: Path):
        tried.append(url)
        if "down" in url:
            destination.write_bytes(b"partial")
            raise MirrorUnavailable("connection refused")
        destination.write_bytes(data)

    archive = fetch_archive(source, tmp_path, download=download)
    assert tried == list(source.urls)
    assert archive.read_bytes() == data


def test_fetch_archive_with_wrong_sha_deletes_download_and_stops(tmp_path):
    source = _archive_source(b"expected", ["https://a.invalid/dep-1.0.tar.gz", "https://b.invalid/dep-1.0.tar.gz"])
    tried = []

    def download(url, destination: Path):
        tried.append(url)
        destination.write_bytes(b"tampered")

    with pytest.raises(IntegrityError):
        fetch_archive(source, tmp_path, download=download)
    assert tried == ["https://a.invalid/dep-1.0.tar.gz"]
    assert list(tmp_path.iterdir()) == []


def test_fetch_archive_reuses_a_verified_download(tmp_path):
    data = b"cached"
    source = _archive_source(data, ["https://a.invalid/dep-1.0.tar.gz"])
    (tmp_path / "dep-1.0.tar.gz").write_bytes(data)

    def download(url, destination):
        raise AssertionError("must not download again")

    assert fetch_archive(source, tmp_path, download=download).read_bytes() == data


def test_fetch_archive_replaces_a_corrupt_cached_download(tmp_path):
    data = b"good"
    source = _archive_source(data, ["https://a.invalid/dep-1.0.tar.gz"])
    (tmp_path / "dep-1.0.tar.gz").write_bytes(b"truncated")

    def download(url, destination):
        destination.write_bytes(data)

    assert fetch_archive(source, tmp_path, download=download).read_bytes() == data


def test_fetch_archive_downloads_file_urls_with_curl(tmp_path):
    data = b"served locally"
    served = tmp_path / "served" / "dep-1.0.tar.gz"
    served.parent.mkdir()
    served.write_bytes(data)
    source = _archive_source(data, [(tmp_path / "missing" / "dep-1.0.tar.gz").as_uri(), served.as_uri()])
    downloads = tmp_path / "downloads"
    archive = fetch_archive(source, downloads, runner=CommandRunner(emit=lambda event: None))
    assert archive.read_bytes() == data


def _tarball(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:bz2") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_extract_tarball_returns_its_top_directory(tmp_path):
    archive = tmp_path / "dep-1.0.tar.bz2"
    _tarball(archive, {"dep-1.0/CMakeLists.txt": b"project(dep)", "dep-1.0/src/a.c": b"int a;"})
    root = extract_archive(archive, tmp_path / "src")
    assert root == tmp_path / "src" / "dep-1.0"
    assert (root / "src" / "a.c").read_bytes() == b"int a;"


def test_extract_zip_and_reextract_is_idempotent(tmp_path):
    archive = tmp_path / "dep-1.0.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("dep-1.0/CMakeLists.txt", "project(dep)")
    first = extract_archive(archive, tmp_path / "src")
    (first / "stale.txt").write_text("left over")
    second = extract_archive(archive, tmp_path / "src")
    assert second == first
    assert not (second / "stale.txt").exists()


def test_extract_rejects_paths_outside_the_destination(tmp_path):
    archive = tmp_path / "evil-1.0.tar.bz2"
    _tarball(archive, {"evil-1.0/ok.txt": b"ok", "../escaped.txt": b"bad"})
    with pytest.raises(IntegrityError):
        extract_archive(archive, tmp_path / "src")
    assert not (tmp_path / "escaped.txt").exists()
    assert not archive.exists(), "rejected content is deleted"


# --- git sources, against local repositories (no network) ------------------------


@pytest.fixture
def upstream(tmp_path):
    """A reVC-like repository whose vendor/librw gitlink points at a librw repository."""
    librw = tmp_path / "remote" / "librw"
    librw_first = make_repo(librw, {"CMakeLists.txt": "project(librw)\n"})
    (librw / "later.txt").write_text("later\n")
    commit_all(librw, "later librw commit")

    revc = tmp_path / "remote" / "reVC"
    make_repo(revc, {"CMakeLists.txt": "project(reVC)\n"})
    git("update-index", "--add", "--cacheinfo", f"160000,{librw_first},vendor/librw", cwd=revc)
    git("commit", "-q", "-m", "add librw gitlink", cwd=revc)  # not commit_all: the gitlink has no work tree
    revc_pin = git("rev-parse", "HEAD", cwd=revc)
    (revc / "newer.txt").write_text("newer\n")
    git("add", "newer.txt", cwd=revc)
    git("commit", "-q", "-m", "newer reVC commit", cwd=revc)
    return {"revc": revc, "revc_pin": revc_pin, "librw": librw, "librw_pin": librw_first}


def test_fetch_git_falls_back_to_a_mirror_that_has_the_commit(tmp_path, upstream):
    without_commit = tmp_path / "remote" / "empty"
    make_repo(without_commit, {"README": "no pinned commit here\n"})
    source = GitSource(
        name="revc",
        urls=(
            (tmp_path / "remote" / "unreachable").as_uri(),
            without_commit.as_uri(),
            upstream["revc"].as_uri(),
        ),
        commit=upstream["revc_pin"],
    )
    dest = tmp_path / "checkout"
    runner = CommandRunner(emit=lambda event: None)
    fetch_git(source, dest, runner, stage="fetch")
    assert git("rev-parse", "HEAD", cwd=dest) == upstream["revc_pin"]
    assert not (dest / "newer.txt").exists()


def test_fetch_git_reports_unavailable_when_no_mirror_has_the_commit(tmp_path, upstream):
    source = GitSource(name="revc", urls=((tmp_path / "nowhere").as_uri(),), commit=upstream["revc_pin"])
    with pytest.raises(SourceUnavailableError):
        fetch_git(source, tmp_path / "checkout", CommandRunner(emit=lambda event: None), stage="fetch")


def test_fetch_revc_initialises_only_the_librw_submodule_at_its_pin(tmp_path, upstream):
    revc = GitSource("revc", (upstream["revc"].as_uri(),), upstream["revc_pin"])
    librw = GitSource("librw", (upstream["librw"].as_uri(),), upstream["librw_pin"], path="vendor/librw")
    runner = CommandRunner(emit=lambda event: None)
    checkout = fetch_revc(revc, librw, tmp_path / "src" / "reVC", runner, stage="fetch")
    assert git("rev-parse", "HEAD", cwd=checkout) == upstream["revc_pin"]
    assert git("rev-parse", "HEAD", cwd=checkout / "vendor" / "librw") == upstream["librw_pin"]
    assert not (checkout / "vendor" / "librw" / "later.txt").exists()

    # A second run reuses the checkout and still ends on the pins.
    fetch_revc(revc, librw, checkout, runner, stage="fetch")
    assert git("rev-parse", "HEAD", cwd=checkout / "vendor" / "librw") == upstream["librw_pin"]


def test_fetch_revc_rejects_a_lock_whose_librw_pin_disagrees_with_revc(tmp_path, upstream):
    revc = GitSource("revc", (upstream["revc"].as_uri(),), upstream["revc_pin"])
    librw = GitSource("librw", (upstream["librw"].as_uri(),), "0" * 40, path="vendor/librw")
    with pytest.raises(LockError):
        fetch_revc(revc, librw, tmp_path / "src" / "reVC", CommandRunner(emit=lambda event: None), stage="fetch")
