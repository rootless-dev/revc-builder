"""Errors the pipeline reports to the user.

Every ``BuildError`` carries a stable ``code`` (the GUI translates by code), an English
``user_message`` for the CLI and the log, and a technical ``detail`` for the log.
"""

from __future__ import annotations


class BuildError(Exception):
    code = "internal"
    default_message = "Something went wrong. Copy the log and include it when asking for help."

    def __init__(self, detail: str = "", *, user_message: str | None = None, **params: object) -> None:
        super().__init__(detail or user_message or self.default_message)
        self.detail = detail
        self.params = params
        self.user_message = user_message or self.default_message.format(**params)

    def __str__(self) -> str:
        return f"{self.user_message} ({self.detail})" if self.detail else self.user_message


class LockError(BuildError):
    code = "lock"
    default_message = "The list of pinned sources is damaged. Download the Builder again."


class SourceUnavailableError(BuildError):
    code = "source_unavailable"
    default_message = "Could not download the source code. Check your internet connection."


class IntegrityError(BuildError):
    code = "integrity"
    default_message = "The downloaded code did not match the expected version and was discarded for safety."


class CompileError(BuildError):
    code = "compile"
    default_message = "The build failed. Copy the log and include it when asking for help."


class BundleError(CompileError):
    code = "bundle"


class DiskSpaceError(BuildError):
    code = "disk_space"
    default_message = "Not enough free space: {needed_gb} GB needed on {volume}."


class GameFilesError(BuildError):
    code = "game_files"
    default_message = "The selected folder does not contain a complete copy of the game."


class NotGameFolderError(GameFilesError):
    code = "not_game_folder"
    default_message = "Not a game folder. Choose the folder that contains the data and models folders."


class IncompleteGameError(GameFilesError):
    code = "incomplete_game"
    default_message = "The game folder is incomplete. {count} required files are missing, for example: {examples}."


class ToolsError(BuildError):
    code = "tools_missing"
    default_message = "The Apple Command Line Tools are not installed."


class ClangFailedError(ToolsError):
    code = "clang_failed"
    default_message = (
        "The Command Line Tools are installed, but the compiler does not run. If Xcode is "
        "installed, open it once and accept its licence, then try again."
    )


class InstallOverlapError(BuildError):
    code = "install_overlap"
    default_message = "Choose the original game folder, not a folder used by the Builder itself."


class UnsupportedPlatformError(BuildError):
    code = "unsupported_platform"
    default_message = "This operating system is not supported yet. reVC Builder currently runs on macOS only."


class InstallError(BuildError):
    code = "install"
    default_message = "Could not install the game. Copy the log and include it when asking for help."
