"""Fetch and verify the pinned sources (spec sections 5 and 8, stage 3)."""

from __future__ import annotations

import hashlib
import re
import shutil
import tarfile
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, TypeVar
from urllib.parse import urlparse

from vcbuilder.errors import BuildError, IntegrityError, LockError, SourceUnavailableError
from vcbuilder.runner import CommandFailed, CommandRunner

GIT = "/usr/bin/git"
CURL = "/usr/bin/curl"

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".zip")

T = TypeVar("T")


class MirrorUnavailable(Exception):
    """A mirror could not be reached or does not have the pinned content; try the next."""


@dataclass(frozen=True)
class GitSource:
    name: str
    urls: tuple[str, ...]
    commit: str
    path: str | None = None


@dataclass(frozen=True)
class ArchiveSource:
    name: str
    version: str
    urls: tuple[str, ...]
    sha256: str

    @property
    def filename(self) -> str:
        return PurePosixPath(urlparse(self.urls[0]).path).name


@dataclass(frozen=True)
class Lock:
    revc: GitSource
    librw: GitSource
    archives: tuple[ArchiveSource, ...]

    def archive(self, name: str) -> ArchiveSource:
        for archive in self.archives:
            if archive.name == name:
                return archive
        raise KeyError(name)


# --- lock file ------------------------------------------------------------------------


def load_lock(path: Path) -> Lock:
    return parse_lock(Path(path).read_text(encoding="utf-8"))


def parse_lock(text: str) -> Lock:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise LockError(f"sources.lock is not valid TOML: {error}") from error
    entries = data.get("sources")
    if not isinstance(entries, dict):
        raise LockError("sources.lock has no [sources.*] tables")

    git_sources: dict[str, GitSource] = {}
    archives: list[ArchiveSource] = []
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise LockError(f"sources.{name} is not a table")
        urls = entry.get("urls")
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) and u for u in urls):
            raise LockError(f"sources.{name}.urls must be a non-empty list of strings")
        kind = entry.get("type")
        if kind == "git":
            commit = entry.get("commit", "")
            if not isinstance(commit, str) or not _COMMIT.match(commit):
                raise LockError(f"sources.{name}.commit must be a full 40-character commit SHA")
            git_sources[name] = GitSource(name, tuple(urls), commit, entry.get("path"))
        elif kind == "archive":
            digest = entry.get("sha256", "")
            version = entry.get("version", "")
            if not isinstance(digest, str) or not _SHA256.match(digest):
                raise LockError(f"sources.{name}.sha256 must be 64 hexadecimal characters")
            if not isinstance(version, str) or not version:
                raise LockError(f"sources.{name}.version is required")
            names = {PurePosixPath(urlparse(url).path).name for url in urls}
            if len(names) != 1 or not next(iter(names)).endswith(_ARCHIVE_SUFFIXES):
                raise LockError(f"sources.{name}.urls must all name the same archive file")
            archives.append(ArchiveSource(name, version, tuple(urls), digest.lower()))
        else:
            raise LockError(f"sources.{name}.type must be 'git' or 'archive'")

    for required in ("revc", "librw"):
        if required not in git_sources:
            raise LockError(f"sources.lock must define the git source '{required}'")
    if not git_sources["librw"].path:
        raise LockError("sources.librw.path must name the submodule path inside reVC")
    return Lock(git_sources["revc"], git_sources["librw"], tuple(archives))


# --- fallback and integrity --------------------------------------------------------------


def fetch_with_fallback(
    urls: Iterable[str], attempt: Callable[[str], T], log: Callable[[str], None] = lambda text: None
) -> T:
    """Try ``attempt`` on each URL in order.

    ``MirrorUnavailable`` moves on to the next URL. Any other exception — notably
    ``IntegrityError`` — propagates immediately, so a mismatch never tries another mirror.
    """
    problems = []
    for url in urls:
        try:
            return attempt(url)
        except MirrorUnavailable as problem:
            problems.append(f"{url}: {problem}")
            log(f"Mirror skipped: {url}: {problem}")
    raise SourceUnavailableError("; ".join(problems) or "no URLs listed")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> bool:
    return sha256_file(path) == expected.lower()


# --- archives ---------------------------------------------------------------------------


def curl_downloader(runner: CommandRunner, stage: str) -> Callable[[str, Path], None]:
    def download(url: str, destination: Path) -> None:
        result = runner.run(
            [CURL, "--fail", "--location", "--silent", "--show-error", "--retry", "2",
             "--connect-timeout", "30", "-o", destination, url],
            stage=stage,
            check=False,
        )
        if result.returncode != 0:
            raise MirrorUnavailable(f"curl exited with {result.returncode}")

    return download


def fetch_archive(
    source: ArchiveSource,
    downloads: Path,
    *,
    download: Callable[[str, Path], None] | None = None,
    runner: CommandRunner | None = None,
    stage: str = "fetch",
) -> Path:
    """Return a verified copy of ``source`` in ``downloads``, downloading it if needed."""
    if download is None:
        if runner is None:
            raise ValueError("either download or runner is required")
        download = curl_downloader(runner, stage)
    downloads.mkdir(parents=True, exist_ok=True)
    final = downloads / source.filename
    if final.is_file():
        if verify_sha256(final, source.sha256):
            return final
        final.unlink()
    partial = downloads / (source.filename + ".part")

    def attempt(url: str) -> Path:
        partial.unlink(missing_ok=True)
        try:
            download(url, partial)
        except MirrorUnavailable:
            partial.unlink(missing_ok=True)
            raise
        if not partial.is_file():
            raise MirrorUnavailable("nothing was downloaded")
        actual = sha256_file(partial)
        if actual != source.sha256:
            partial.unlink(missing_ok=True)
            raise IntegrityError(f"{source.filename} from {url}: SHA-256 {actual}, expected {source.sha256}")
        partial.rename(final)
        return final

    return fetch_with_fallback(source.urls, attempt, _logger(runner, stage))


def extract_archive(archive: Path, destination_parent: Path) -> Path:
    """Extract ``archive`` into ``destination_parent`` and return its single top directory.

    Extraction goes to a temporary directory first, so an interrupted run never leaves a
    half-extracted tree in place; an existing extraction is replaced.
    """
    destination_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".extract-", dir=destination_parent))
    try:
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.namelist():
                    _check_member(member)
                bundle.extractall(staging)
        else:
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    _check_member(member.name)
                bundle.extractall(staging, filter="data")
        tops = [entry for entry in staging.iterdir()]
        if len(tops) != 1 or not tops[0].is_dir():
            raise IntegrityError(f"{archive.name} does not contain exactly one top-level directory")
        target = destination_parent / tops[0].name
        if target.exists():
            shutil.rmtree(target)
        tops[0].rename(target)
        return target
    except IntegrityError:
        archive.unlink(missing_ok=True)  # spec section 5: rejected content is deleted
        raise
    except (tarfile.TarError, zipfile.BadZipFile) as error:
        archive.unlink(missing_ok=True)
        raise IntegrityError(f"could not extract {archive.name}: {error}") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _logger(runner: CommandRunner | None, stage: str) -> Callable[[str], None]:
    if runner is None:
        return lambda text: None
    return lambda text: runner.log(stage, text)


def _check_member(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise IntegrityError(f"archive member escapes the destination: {name}")


# --- git ------------------------------------------------------------------------------------


def _git(runner: CommandRunner, repo: Path, *args: str, stage: str, check: bool = True):
    return runner.run([GIT, "-C", repo, *args], stage=stage, check=check, env=git_environment())


def git_environment() -> dict[str, str]:
    """Run git without the user's or system configuration, prompts or pagers."""
    return {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ADVICE": "0",
        "LC_ALL": "C",
    }


def _has_commit(runner: CommandRunner, repo: Path, commit: str, stage: str) -> bool:
    if not (repo / ".git").exists():
        return False
    return _git(runner, repo, "cat-file", "-e", f"{commit}^{{commit}}", stage=stage, check=False).returncode == 0


def fetch_git(source: GitSource, dest: Path, runner: CommandRunner, *, stage: str) -> Path:
    """Make ``dest`` a checkout of ``source.commit``, trying each mirror in order."""
    dest.mkdir(parents=True, exist_ok=True)
    if not (dest / ".git").exists():
        _git(runner, dest, "init", "--quiet", stage=stage)

    if not _has_commit(runner, dest, source.commit, stage):

        def attempt(url: str) -> None:
            result = _git(
                runner, dest, "fetch", "--quiet", "--depth", "1", "--no-tags", url, source.commit,
                stage=stage, check=False,
            )
            if result.returncode != 0:
                raise MirrorUnavailable(f"git fetch exited with {result.returncode}")

        fetch_with_fallback(source.urls, attempt, _logger(runner, stage))

    try:
        _git(runner, dest, "-c", "advice.detachedHead=false", "checkout", "--quiet", "--force", "--detach",
             source.commit, stage=stage)
    except CommandFailed as failure:
        # The commit was fetched, so this is a local problem (disk full, a stale lock file),
        # not a content mismatch: keep the checkout and report it as a plain failure.
        raise BuildError(str(failure)) from failure
    head = _git(runner, dest, "rev-parse", "HEAD", stage=stage).output.strip()
    if head != source.commit:
        shutil.rmtree(dest, ignore_errors=True)
        raise IntegrityError(f"{source.name}: HEAD is {head}, expected {source.commit}")
    return dest


def recorded_submodule_commit(runner: CommandRunner, repo: Path, path: str, *, stage: str) -> str:
    output = _git(runner, repo, "ls-tree", "HEAD", path, stage=stage).output.strip()
    # "160000 commit <sha>\t<path>"
    fields = output.split()
    if len(fields) < 3 or fields[0] != "160000" or fields[1] != "commit":
        raise IntegrityError(f"{path} is not a submodule in the reVC checkout")
    return fields[2]


def fetch_revc(revc: GitSource, librw: GitSource, dest: Path, runner: CommandRunner, *, stage: str) -> Path:
    """Fetch reVC and only its ``vendor/librw`` submodule, both at their pins (spec F6)."""
    fetch_git(revc, dest, runner, stage=stage)
    assert librw.path is not None
    recorded = recorded_submodule_commit(runner, dest, librw.path, stage=stage)
    if recorded != librw.commit:
        raise LockError(f"reVC records {librw.path} at {recorded}, but sources.lock pins {librw.commit}")
    fetch_git(librw, dest / librw.path, runner, stage=stage)
    return dest
