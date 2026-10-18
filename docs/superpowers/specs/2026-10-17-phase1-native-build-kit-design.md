# Phase 1 — Native macOS Build Kit for reVC

Date: 2026-10-17
Status: implemented on 2026-10-17 (implementation notes are in §4, §5, §6.2, §6.4, §8, §9
and §10); on 2026-10-17 criteria 5 and 6 of §1.1 were checked (the automated tests, including the
network test, pass), the CLI built and installed `reVC.app` end to end, and the packaged
Builder was launched; criterion 1 (the Builder's wizard driven from Finder) and
criteria 2–4 (gameplay) await the owner

## 1. Goal

Let a person who owns the GTA Vice City (PC) game files produce a native macOS build of
the game on their own Mac, without using the Terminal.

The product is a **build kit**, not the game. It is a PySide6 desktop app (the
*Builder*) plus a Python build engine (`vcbuilder`). The Builder takes the user's game
folder, downloads the reVC source code, compiles it on the user's machine and installs
the resulting `reVC.app`.

Phase 1 renders through librw's existing OpenGL 3 backend. Phase 2 (separate spec)
replaces it with a new Metal backend; nothing in this spec depends on Phase 2.

### 1.1 Success criteria

Phase 1 is done when, on the owner's Mac (Apple M3 Pro, macOS 27), starting from the game
files extracted from the local validation copy (§9):

1. The Builder, launched from Finder, produces `reVC.app` without the user typing any
   command.
2. `reVC.app` launches by double-click, reaches the main menu, starts a new game, plays
   the first mission, saves, quits, relaunches and loads the save.
3. Sound effects and radio stations play. The validation copy lacks the radio stations
   (§9), so with it only sound effects and mission dialogue can be checked; the radio
   half of this criterion needs game files from another source, such as a Steam copy.
4. Keyboard + mouse work; a connected game controller works if one is available.
5. `otool -L` on every Mach-O file inside `reVC.app` shows no path under `/opt/homebrew`,
   `/usr/local` or `/opt/local` (proof that no Homebrew/MacPorts library leaked in). The
   owner's Mac has Homebrew's `mpg123` installed, so this criterion is exercised for
   real, not vacuously.
6. All automated tests of §11 pass, including the on-demand network test, run with the
   `gui` and `dev` extras installed (without PySide6 the GUI tests are skipped) and after
   a build (without the Builder's reVC checkout the patch test is skipped).

### 1.2 Non-goals

- Distributing game assets, a prebuilt reVC binary, or reVC source code in this
  repository.
- A Metal renderer (Phase 2).
- Downloading the game from a Steam account (SteamCMD). Only existing folders are used.
- A hash manifest for the Steam release. Validation in Phase 1 checks presence of
  required files only (§6.2).
- Notarization. The owner has no Apple Developer account (§10).
- Intel Macs as a supported target. They are best-effort: the Builder is universal2 and
  the build compiles for the host architecture, so it is expected to work, but it is not
  tested.

## 2. Constraints and decisions

| Decision | Reason |
|---|---|
| reVC source is fetched at build time from pinned mirrors, never committed here | reVC was the target of a 2021 DMCA notice and lawsuit (settled 2023); keeping it out of this repository keeps the repository out of reach of the same notices |
| GUI toolkit is PySide6 (Qt 6, LGPL) | Owner prefers a Python GUI; PySide6 over PyQt6 for its LGPL licence |
| No Homebrew dependency for end users | Target users are not comfortable with the Terminal |
| Only Apple Command Line Tools (CLT) are required from the user | They install through a standard macOS dialog; they ship `clang`, `git` and the macOS SDK |
| All repository artifacts are in English | Owner's standing rule; GUI strings are English with a Brazilian Portuguese translation |
| Minimum macOS: 13 (Ventura) | Applies to the Builder; reVC itself declares 11.0 for arm64 |

## 3. Facts about upstream reVC this design relies on

Verified by reading mirror `mrxenginner/reVC`, branch `miami`, commit
`a26fff4af555a8a425ac9f17d1dd718d00d1f942` (2026-10-02), and its librw submodule:

- **F1** — CMake already builds a `reVC.app` bundle on macOS
  (`src/CMakeLists.txt`, `MACOSX_BUNDLE`), copies `gamefiles/` into
  `Contents/Resources/gamefiles`, copies dependency dylibs into `Contents/Frameworks`,
  runs `install_name_tool -change <dylib path> @rpath/<file name>` on the executable,
  sets the rpath to `@executable_path/../Frameworks`, and signs the bundle ad hoc
  (identity `-`) when no signing identity is configured. At run time, when a file is
  opened read-only, a file found under `Contents/Resources/gamefiles` takes the place of
  the same file in the game folder (`myfopen` and `CFileMgr::ResolveBundledGameFile`,
  `src/core/FileMgr.cpp`).
- **F2** — macOS dependencies are OpenAL (`libopenal.1.dylib`), mpg123
  (`libmpg123.0.dylib`) and GLFW (`libglfw.3.dylib`). Opus and libsndfile are off by
  default (`REVC_WITH_OPUS`, `REVC_WITH_LIBSNDFILE`). GLFW is librw's default window
  library on macOS (`LIBRW_GL3_GFXLIB`, librw `CMakeLists.txt`).
- **F3** — With a non-Xcode generator, the dylib to bundle for each dependency is read
  from `REVC_MACOS_<DEP>_DYLIBS` (`<DEP>` ∈ `OPENAL`, `MPG123`, `GLFW`). The top-level
  `CMakeLists.txt` searches fixed MacPorts and Homebrew paths and, when it finds the
  dylib there, assigns `REVC_MACOS_<DEP>_DYLIBS` as a normal variable — which hides any
  cache variable of the same name passed with `-D`. If any of the three ends up undefined, bundling is
  silently skipped. Consequence: on a Mac with Homebrew's `mpg123`, the Homebrew dylib
  would be bundled and linked. This design therefore patches reVC (§8 stage 5).
- **F4** — User files live in `~/Library/Application Support/reVC/`
  (`GetMacOSUserFilesFolder`, `src/skel/crossplatform.cpp`). This holds `reVC.ini` and
  the save games. This path holds only while `FINAL` is not defined; `FINAL` turns on
  `USE_MY_DOCUMENTS` (`src/core/config.h`), which moves user files elsewhere. The CMake
  build does not define `FINAL` or `MASTER`. A side effect of a non-`FINAL` build is that
  reVC's debug menu is compiled in; upstream's CMake-based macOS nightly builds have the
  same property.
- **F5** — The game root is resolved in this order (`FindGameRoot`,
  `src/core/FileMgr.cpp`): the executable's directory; three levels above it (the folder
  that contains `reVC.app`); the current working directory; the `[General] GamePath`
  key of `reVC.ini`; otherwise an `osascript` folder picker. A folder is accepted as a
  game root when `data/gta_vc.dat` and `models/gta3.img` exist in it (case-insensitive
  lookup).
- **F6** — The vendored librw is a git submodule at `vendor/librw` pointing to
  `https://github.com/mrxenginner/librw.git`, pinned by the reVC commit above to
  `0ad67ee226ea51beb3f465cb8857195e4db16029`. reVC also declares submodules `vendor/ogg`,
  `vendor/opus` and `vendor/opusfile`, which are only needed with Opus enabled.

If a later pin moves to a different reVC commit, F1–F6 must be re-verified against it
before the pin is accepted.

## 4. Architecture

```
vice-city-macos/
├── vcbuilder/                 # build engine; no GUI imports
│   ├── __main__.py            # CLI: python -m vcbuilder <game-folder>
│   ├── session.py             # facade used by the CLI and the GUI; owns the build log
│   ├── pipeline.py            # ordered stages, progress events, cancellation
│   ├── events.py              # the typed event stream
│   ├── errors.py              # user-facing errors, each with a stable code
│   ├── runner.py              # subprocesses with streamed output, cancellation, build log
│   ├── paths.py               # Locations: the folders of §6.3 (the platform picks the base folders)
│   ├── preferences.py         # remembered game folder (§7 page 2)
│   ├── resources.py           # locates sources.lock, patches/ and data/ (source tree or bundle)
│   ├── gamefiles.py           # validate a game folder; scan Steam libraries the platform names
│   ├── toolchain.py           # locate the bundled cmake and ninja
│   ├── sources.py             # fetch and verify pinned sources (§8 stage 3)
│   ├── deps.py                # build GLFW, OpenAL Soft, mpg123 into a private prefix (stage 4)
│   ├── compile.py             # restore checkout, apply patches, configure, build (stage 5)
│   ├── install.py             # copy game data, install the app, write GamePath (stage 7)
│   ├── platform/              # everything that differs per operating system
│   │   ├── __init__.py        # current(): the selector; refuses anything but macOS for now
│   │   ├── base.py            # Platform (an ABC, with the shared stage-2 ensure_tools loop),
│   │   │                      # ToolsStatus, POLL_INTERVAL; re-exports install.Copier
│   │   └── macos.py           # MacOSPlatform: CLT, ~/Library layout, APFS clones, bundle checks
│   └── data/
│       ├── required_files.txt # files a game folder must contain (§6.2)
│       └── cmake/             # CMake include files for dependency builds (§8 stage 4)
├── gui/                       # PySide6 Builder; depends on vcbuilder only
│   ├── app.py
│   ├── widgets.py             # shared widgets and the original sunset artwork
│   ├── pages/                 # one module per wizard page (§7)
│   ├── style/                 # Qt style sheet, bundled OFL fonts, window icon
│   └── i18n/                  # Qt .ts/.qm translation (pt_BR; English is the source language)
├── pyproject.toml             # package metadata; exact Python dependency pins (§5)
├── sources.lock               # pinned sources (§5)
├── patches/                   # patches applied on top of reVC (§8 stage 5)
├── packaging/                 # PyInstaller spec, build script and icon for the Builder app
├── tests/
└── README.md
```

**Boundary.** `vcbuilder` does all build work: every file-system change, network access
and subprocess of the pipeline, including the CLT check and install request. It reports
progress through a typed event stream (`StageStarted`, `Progress`, `LogLine`,
`StageFailed`, `StageFinished`). The GUI subscribes to it and never runs a command
itself; apart from reading its own style, font and translation files and checking that
a dropped path is a folder, its only direct system access is through Qt — the folder dialog, drag and drop, the clipboard, and
`QDesktopServices` to open the app or reveal it in Finder. The CLI renders the same events as text.
This keeps every build behaviour testable without Qt.

**Platform seam.** Inside `vcbuilder`, everything specific to macOS that the build does
sits behind the `Platform` interface in `vcbuilder/platform/base.py`, implemented by
`macos.py`: toolchain detection and install (the CLT, `xcode-select`, the `clang` check);
the installed layout — the app destination and the base folders for the Builder's data,
reVC's user files, the cache and the logs (`paths.Locations` derives `game`, `reVC.ini`
and the cache subfolders from them the same way on every platform) — and where the build
puts the app; the directory copier (`cp -cR`, an APFS clone,
or `cp -R`) and the volume name in the disk-space message — the clone-then-copy sequence
and the free-space check themselves are platform-neutral (§6.3); the shared-library file
names and the per-library check of stage 4 (`otool -D`); the platform-specific CMake
definitions of stages 4 and 5 (architectures, ignore-prefix paths, and for stage 4 the
deployment target and OpenAL Soft's audio backends and compiler workaround, for stage 5
`REVC_MACOS_*`); app bundle
verification (`otool`, `codesign`, the quarantine attribute); the Steam search locations
(CrossOver and Whisky bottles); the environment the compilers run in (package managers
removed from `PATH`, and the variables that point at them dropped); and the host
architecture.

The pipeline, source and lock handling, game-file validation, the dependency build
orchestration, INI editing, the event stream, the CLI and the GUI contain no
platform-specific logic. `BuildSession` obtains the platform from the single selector
`vcbuilder.platform.current()`, which raises an "unsupported platform" error on anything
but macOS, and passes it down to the pipeline stages (tests pass a fake one instead). The
seam exists so that a Linux, and later an Android, target can be added as another
implementation without touching the rest of the build logic; neither is implemented.
Outside the seam, a new target would still need attention in these places:
- user-facing text in `errors.py`, the GUI and the CLI, which names the Command Line
  Tools, Xcode, Finder and "this Mac";
- the Done page's "Play", which opens the installed `.app` with `QDesktopServices`, which
  starts it only because LaunchServices treats a bundle as an app;
- `sources.py` and `compile.py`, which run `/usr/bin/git` with
  `PATH=/usr/bin:/bin:/usr/sbin:/sbin` and no user or system git configuration, and
  `sources.py`, which downloads with `/usr/bin/curl` in the inherited environment (so
  proxy variables apply) — the CLT's git on macOS, the usual locations on Linux; Android
  has neither;
- `deps.py`, whose dependency set and SONAME versions are the ones reVC bundles on macOS
  (F2), with the mpg123 `SOVERSION` include that exists for that file name;
- `toolchain.py`, which finds CMake and Ninja inside a PyInstaller bundle at the layout
  `packaging/` creates, and `packaging/` itself, which builds a macOS app.

**CLI.** Intended for developers. It needs Python 3.12 or later with the package
installed (`pip install .`), which pulls the same pinned `cmake` and `ninja` wheels the
Builder bundles; the GUI and packaging dependencies are optional extras (`.[gui]`,
`.[package]`). The Python 3.9 that ships with the CLT is not supported.

## 5. Pinned sources (`sources.lock`)

TOML file. Each entry has a name, a list of URLs, and an exact pin: a commit SHA for
git sources, a version plus SHA-256 for release archives.

- `revc` — git; mirrors in priority order, starting with
  `https://github.com/mrxenginner/reVC.git`; commit
  `a26fff4af555a8a425ac9f17d1dd718d00d1f942`.
- `librw` — git mirrors for the `vendor/librw` submodule, starting with the URL in
  reVC's `.gitmodules`. The commit is the one the reVC pin records (F6), which stage 3
  checks against the gitlink in the reVC checkout. The Builder does not use
  `git submodule`, which would only try the `.gitmodules` URL: it fetches the pinned
  commit from the mirrors in `sources.lock` into a nested repository at `vendor/librw`.
  Only this submodule is fetched; `vendor/ogg`, `vendor/opus` and `vendor/opusfile` are not
  fetched (F6).
- `glfw`, `openal-soft`, `mpg123` — release archives (tarballs; GLFW publishes its source
  release only as a `.zip`). Each records an exact version, one or more download URLs and
  a SHA-256. The versions are the newest stable releases as of 2026-10-17: GLFW 3.5.1,
  OpenAL Soft 1.25.2 and mpg123 1.33.7. Each builds with CMake for arm64 (verified on
  macOS 27 with the AppleClang 21 of Xcode 27, deployment target 11.0; a Mac with only the
  Command Line Tools was not tested) and produces the file name reVC expects
  (F2); mpg123 and OpenAL Soft need the
  dependency-specific settings listed in §8 stage 4.

The Python dependencies are pinned to exact versions in `pyproject.toml`: `cmake` (3.24
or later: stages 4 and 5 need 3.23 for `CMAKE_IGNORE_PREFIX_PATH`, and stage 4 configures
with `cmake --fresh`, added in 3.24; 4.4.4 is pinned) and `ninja` as required
dependencies, `PySide6-Essentials` 6.9.3 in the `gui` extra and `PyInstaller` in the
`package` extra. `PySide6-Essentials` is the core subset of PySide6 (it also carries
modules such as QtNetwork and QtSvg); the Builder itself uses only QtCore, QtGui and
QtWidgets. It is pinned to 6.9 because that is the newest series whose
binaries all run on macOS 13: from 6.10 on, the wheels are tagged `macosx_13_0` (6.12:
`macosx_14_0`), but their PySide6 and shiboken6 libraries declare a minimum of macOS 15.0
(`otool -l`, `minos`), while every 6.9.3 binary declares 12.0. Do not add the full
`PySide6` package.

**Mirror rule.** A URL may be listed for a git source only if the pinned commit is
reachable from it. A test (§11) checks every listed mirror against the pinned commit.
As of 2026-10-17 the only mirrors that contain the pins are GitHub forks in the same fork
network as `mrxenginner/reVC` and `mrxenginner/librw`; no mirror outside GitHub was
found, so the extra mirrors do not protect against a takedown of that network.

**Integrity.** For git sources, after checkout `git rev-parse HEAD` must equal the
pinned SHA, and `git -C vendor/librw rev-parse HEAD` must equal the librw pin. For
release archives, the SHA-256 must match before extraction.

**Fallback vs. mismatch.** A mirror that cannot be reached, or does not have the pinned
commit, is skipped and the next one is tried. Content that was downloaded but does not
match its pin stops the whole build: the download is deleted and no further mirror is
tried, because a mismatch means something is wrong with the source, not with the
network.

## 6. Game files

### 6.1 Sources the user can choose

1. **A folder** chosen with the native folder dialog or dragged onto the window.
2. **A detected Steam install.** The Builder scans these locations and lists every match:
   - `~/Library/Application Support/CrossOver/Bottles/*/drive_c/Program Files (x86)/Steam/steamapps/common/Grand Theft Auto Vice City`
   - `~/Library/Containers/com.isaacmarovitz.Whisky/Bottles/*/drive_c/Program Files (x86)/Steam/steamapps/common/Grand Theft Auto Vice City`

   Only the default Steam library inside each bottle is scanned. Users with other library
   folders pick the folder manually.

Both kinds of source go through the same validation.

### 6.2 Validation

`required_files.txt` lists paths relative to the game root, compared case-insensitively.
It must contain at least `data/gta_vc.dat` and `models/gta3.img`, which reVC itself
requires (F5). The full list was derived during implementation: every file reVC opens
by fixed path during start-up and a new game, found by observing and reading the reVC
build run against the validation copy (§9). Files that only some releases have are not
in the list, and neither are files whose presence in a real install could not be
confirmed.

The list shipped for the pinned commit (131 paths) was derived by tracing every file the
built reVC opened while starting up and running the opening of a new game against the
validation copy, plus the loading-screen textures `main.cpp` picks by name
(`txd/loadsc0`–`12`, `splash1`–`3`) and the intro textures (`txd/intro1`–`4`). It leaves out
files reVC generates in the game folder (`models/txd.img`, `models/txd.dir`,
`audio/sound.cache`, `data/CAPS.DAT`), files `reVC.app` bundles itself (F1), and the radio
stations (`audio/*.adf`) and the streamed MP3s (cutscene and ambience audio,
`audio/*.mp3`): reVC only warns when they are missing, and the validation copy lacks them
(§9), so their names could not be confirmed against a real install. Mission dialogue is in
`audio/*.wav`, which the validation copy has. The 131 entries themselves were confirmed
only against the validation copy, which is a repack: a file it has but a Steam or retail
install lacks would make that install "Incomplete". Checking the list against a Steam
copy is open (§12).

The result shown to the user is one of:

- **Valid** — every required file is present.
- **Installer** — neither `data/gta_vc.dat` nor `models/gta3.img` is present, and the
  folder directly contains a file with an installer or archive extension (`.exe`, `.msi`,
  `.bin`, `.cab`, `.iso`, `.rar`, `.zip`, `.7z`, `.arc`, `.catalyst`). The message says it
  looks like an installer and asks the user to install the game first and choose the
  installed folder.
- **Not a game folder** — neither marker file is present and the folder does not look
  like an installer. The message suggests choosing the folder that contains `data` and
  `models`.
- **Incomplete** — any other case with missing required files; the first ten are listed,
  and the full list is in the log.
- **Used by the Builder** — the folder overlaps the Builder's own data directory (§6.3
  step 1) and is not its `game` folder; the message asks for the original game folder.

The build cannot start unless the result is *Valid*.

### 6.3 Installed layout

| What | Where | Owner |
|---|---|---|
| Application | `/Applications/reVC.app`, or `~/Applications/reVC.app` when `/Applications` is not writable | Builder |
| Game data | `~/Library/Application Support/reVC Builder/game/` | Builder |
| Settings and saves | `~/Library/Application Support/reVC/` (F4) | reVC |
| Build cache | `~/Library/Caches/reVC Builder/` | Builder |
| Build logs | `~/Library/Logs/reVC Builder/` | Builder |

**Copying the game data.** The copy is needed because the source may be on a removable
drive or inside a bottle the user later deletes. It also has to be writable: on its first
start reVC writes the files listed as generated in §6.2 into the game folder. Steps:

1. If the source is the game data directory `game` itself, skip the remaining copy steps
   (the data is already in place). Otherwise, if
   the source and `~/Library/Application Support/reVC Builder/` overlap — one is the
   other or lies inside it, which covers `game`, `game.new` and `game.old` — stop with an
   error, since the steps below would delete or overwrite the source. Validation (§6.2,
   stage 1 and GUI page 2) already refuses such a folder, so the user can choose another
   before building; the check here is a second line of defence.
2. Delete any `game.new` or `game.old` left next to `game` by an interrupted earlier
   run. Copy into the staging directory `game.new`, first with an APFS clone
   (`/bin/cp -cR`), which uses no extra space.
3. If the clone fails (for example because the source is on another volume), delete the
   partial staging directory, check that the destination volume has at least the size
   of the source folder plus 10 % free, and copy normally (`/bin/cp -R`).
4. Only after the copy has completed, rename `game` to `game.old`, rename `game.new` to
   `game`, then delete `game.old`. A failed or cancelled copy leaves the previous `game`
   untouched.

**Re-running the Builder** replaces `reVC.app` and the game data as above. It never
deletes or changes anything in `~/Library/Application Support/reVC/` except the
`GamePath` lines of `[General]` (§6.4). `reVC.ini` is rewritten atomically: the new contents go to
`reVC.ini.tmp` in the same folder, which is then renamed over the original with the
original's permissions, so an interruption leaves either the old or the new file (and
possibly a stray `reVC.ini.tmp`). A symbolic link at `reVC.ini` is replaced by a regular
file.

### 6.4 Pointing reVC at the data

`reVC.app` lives in an Applications folder and is started by Finder with `/` as its
working directory, so the first three lookups of F5 find no game and reVC reads
`[General] GamePath` from `reVC.ini`. The Builder sets that key to the game data path.
reVC parses the file with mINI compiled case-sensitive (`MINI_CASE_SENSITIVE`,
`src/core/re3.cpp`), which trims whitespace around the value but keeps spaces inside it,
so the Builder always writes the key as `GamePath`, unquoted. The end-to-end run of
2026-10-17 confirmed that reVC, started through LaunchServices, finds the game through a
`GamePath` containing spaces (`…/Application Support/reVC Builder/game`).

The edit is line-based, so every other line of the file — settings, comments, order —
is kept byte for byte, with these additions only: a line terminator after the file's last
line when the Builder appends after it and it has none, and a blank line before a
`[General]` section the Builder creates at the end of a file that is not blank. Section and key are
matched as reVC matches them — case-sensitively, ignoring spaces inside the brackets and
around `=` — so `[general]` is a different section (a `[General]` is added) and a
`gamepath=` line is a different key, left alone. mINI keeps the last value of a repeated
key, so if `[General]` holds several `GamePath` lines, the first is rewritten and the
others are removed. If a `GamePath` line exists in `[General]`, it is replaced; if
`[General]` exists without one, the line is added at the end of that section; if the
section or the file does not exist, it is created.

The `gamefiles/` content reVC needs is already bundled inside `reVC.app` by upstream
CMake (F1), so nothing is written into the user's game data for it.

## 7. Builder GUI

A single-window wizard. Each page maps to pipeline stages (§8).

1. **Welcome** — what the tool does, and that the user must own the game files.
2. **Game files** — "Choose folder…" button, drop area, and a list of detected Steam
   installs (§6.1). Validation runs as soon as a source is chosen; the result is shown
   inline (§6.2). The text says explicitly that the installed game is needed, not the
   installer or the downloaded archive. When the user continues, the folder is saved in
   `preferences.json` in the Builder data directory; when the page opens with no folder
   chosen yet, the saved folder is chosen again if it still exists. When the game data
   directory from an earlier build holds both marker files, a "Use the game already
   installed" button chooses it, which rebuilds without copying (§6.3 step 1).
3. **Tools** — checks for the Command Line Tools with `xcode-select -p`. When it fails,
   an "Install" button runs `xcode-select --install`, which shows Apple's dialog, and the
   page polls `xcode-select -p` every 5 s until it succeeds or the user cancels. Only
   then does it confirm `/usr/bin/clang --version` exits 0. `clang` is never run before
   `xcode-select -p` succeeds, because on a Mac without the tools `/usr/bin/clang` itself
   opens the install dialog. If `xcode-select -p` succeeds but `clang` fails — typically
   a full Xcode whose licence was never accepted — the page says so, suggests opening
   Xcode once, and offers "Check again".
4. **Build** — one progress row per stage, an overall progress bar, a collapsible log
   view, and Cancel.
5. **Done** — where the app was installed, a "Play" button that opens it with
   `QDesktopServices`, which goes through LaunchServices like a Finder double-click, so it
   starts with the same working directory as from Finder (§6.4), and "Show in Finder",
   which opens the folder that contains the app (`QDesktopServices` cannot select it).

Errors replace the current page's content with a plain-language message, a "Copy log"
button and "Try again" (§8).

**Look.** Dark background, neon pink / cyan accents and a retro display font, evoking
the 1980s Miami style. Only original artwork and fonts under the SIL Open Font Licence
are bundled. Nothing from Rockstar or Take-Two (logos, artwork, screenshots, fonts) is
included.

**Language.** UI strings go through Qt's `tr()`. English is the source language; a
Brazilian Portuguese translation ships in Phase 1. The UI follows the macOS system
language and falls back to English.

## 8. Build pipeline

Stages, in order. Each stage is idempotent and uses the build cache, so "Try again"
restarts from the failed stage. Pages 2 and 3 of the GUI perform the checks of stages 1
and 2 step by step through the same engine functions (validation; the tools check, the
install request and the cheap presence check, which page 3 polls with its own timer as
§7 describes), without running those pipeline stages; page 4
runs stages 3 to 7, so "Try again" in the GUI restarts from one of those. The CLI runs all
seven stages; its stage 2 requests the install and polls by itself.

1. **Validate game files** (§6.2).
2. **Check tools** — CLT present (§7 page 3). `cmake` and `ninja` come from the Builder's
   own Python environment (§5).
3. **Fetch sources** — fetch `revc` and its `vendor/librw` submodule, and the three
   dependency archives, applying the fallback and integrity rules of §5.
4. **Build dependencies** — configure and build GLFW, OpenAL Soft and mpg123 as shared
   libraries for the host architecture with CMake and Ninja, installing into
   `~/Library/Caches/reVC Builder/prefix`. Each is configured with
   `CMAKE_INSTALL_NAME_DIR=@rpath`, with examples, tests and utilities off, with the
   same `CMAKE_IGNORE_PREFIX_PATH` and `CMAKE_DISABLE_FIND_PACKAGE_PkgConfig` as stage 5,
   and with `CMAKE_FIND_FRAMEWORK=LAST` so plain libraries win over macOS frameworks.
   The deployment target is 11.0 on arm64 (reVC's own) and 10.15 on x86_64, above reVC's
   own 10.12 as a conservative floor for OpenAL Soft's C++20 code (untested; Intel is best
   effort, §1.2). OpenAL Soft
   requires its CoreAudio backend and has every backend that would use an external
   library (PipeWire, PulseAudio, JACK, PortAudio, SDL2, SDL3 and others) switched off. Two dependency-specific settings are needed:
   - mpg123's CMake port sets no `SOVERSION`, so it produces `libmpg123.dylib`. A CMake
     file shipped with the Builder (`vcbuilder/data/cmake/mpg123-soversion.cmake`, passed
     as `CMAKE_PROJECT_mpg123_INCLUDE`) sets `SOVERSION 0` on the `libmpg123` target, which
     yields `libmpg123.0.dylib`, the name the autotools build produces and reVC expects.
   - OpenAL Soft 1.25 turns `-Wfunction-effects` into an error, and AppleClang 21 (Xcode
     27) reports two such diagnostics in its CoreAudio backend. Pre-seeding the compiler
     check `HAVE_WFUNCTION_EFFECTS=OFF` leaves out both `-Wfunction-effects` and
     `-Werror=function-effects`; the code is unchanged.

   The stage fails unless the prefix then contains `lib/libglfw.3.dylib`,
   `lib/libopenal.1.dylib` and `lib/libmpg123.0.dylib` (F2), each reporting an install
   name of `@rpath/<its file name>` (`otool -D`).
5. **Build reVC** — restore the reVC checkout and `vendor/librw` to their pinned commits
   (`git reset --hard <pin>`, then `git clean -f -d` to remove files a patch added; a
   single `-f` leaves the nested librw repository alone), so a retry never applies a patch
   twice; the CMake build
   directory lives in the build cache outside the checkout, so this does not discard
   compiled objects. Apply `patches/` in file-name order with `git apply`; the first patch
   changes the non-Xcode branch of reVC's top-level `CMakeLists.txt` so that the
   Homebrew/MacPorts search is skipped for any `REVC_MACOS_<DEP>_DYLIBS` already defined
   in the cache (F3). Then configure with Ninja and:
   - `CMAKE_BUILD_TYPE=Release`, `CMAKE_OSX_ARCHITECTURES` = host architecture;
   - `CMAKE_PREFIX_PATH` = the private prefix;
   - `CMAKE_IGNORE_PREFIX_PATH=/opt/homebrew;/usr/local;/opt/local`;
   - `CMAKE_DISABLE_FIND_PACKAGE_PkgConfig=ON`, so a Homebrew `pkg-config` cannot point
     the mpg123 search at Homebrew;
   - `OpenAL_DIR` and `glfw3_DIR` set to the CMake package directories in the prefix
     (reVC's `src/CMakeLists.txt` first calls `find_package(OpenAL CONFIG …)`, which
     honours `OpenAL_DIR`; librw calls `find_package(glfw3)`),
     and `mpg123_INCLUDE_DIR`, `mpg123_LIBRARIES` set to the prefix's header directory
     and dylib (cached values make `find_path`/`find_library` skip their search);
   - `REVC_MACOS_OPENAL_DYLIBS`, `REVC_MACOS_MPG123_DYLIBS`, `REVC_MACOS_GLFW_DYLIBS`
     set to the three dylibs in the prefix.

   Then build.
6. **Verify the bundle** — `Contents/Frameworks` contains the three dylibs; criterion 5
   of §1.1 holds, and no `LC_RPATH` of a Mach-O file in the bundle points under those
   prefixes either; the executables in `Contents/MacOS` link `@rpath/` names of all three
   dylibs (so the bundled copies are the ones used, not, say, Apple's OpenAL framework);
   the bundle has no `com.apple.quarantine` extended attribute (strip it
   if present, since the user built it locally); `codesign --verify --deep --strict`
   passes. On macOS this stage is `MacOSPlatform.verify_app`.
7. **Install** — copy the game data (§6.3), then copy `reVC.app` to its destination
   (§6.3), then write `GamePath` (§6.4). The game data goes first so that a disk-space or
   copy failure stops before anything installed earlier is replaced. The app is copied
   like the game data — clone first, normal copy if the clone fails — into a staging
   folder next to the destination, which then replaces the previous app; no free-space
   check is made for it (it is about 20 MB).

**Errors.**

| Failure | User-facing message | Behaviour |
|---|---|---|
| Every URL of a source unreachable or lacking the pin | Could not download the source code. Check your internet connection. | Stop at stage 3 |
| Downloaded content does not match its pin | The downloaded code did not match the expected version and was discarded for safety. | Delete the download and stop the build (§5). A `git checkout` that fails after the pinned commit was fetched is a local problem, not a mismatch: it is reported with the generic "Something went wrong" message and the checkout is kept |
| Compiler, CMake or patch error | The build failed. Copy the log and include it when asking for help. | Stop; keep the build cache |
| `sources.lock` invalid, or its librw pin differs from the gitlink in the reVC pin | The list of pinned sources is damaged. Download the Builder again. | Stop; nothing is deleted, since the lock, not the download, is at fault |
| Not enough disk space for a normal copy | Not enough free space: *N* GB needed on *volume*. (*N* in the user's number format; *volume* is the volume's name, or "the startup disk", translated) | Stop before copying (§6.3 step 3); `reVC.app` and `GamePath` are not touched |
| User cancels | — (the GUI shows "Build cancelled" with "Try again", which continues from the cancelled stage) | Kill the child process; delete any staging directory; keep the cache consistent |

Every log line from every subprocess is kept in
`~/Library/Logs/reVC Builder/build-<timestamp>.log`, which is what "Copy log" copies.

## 9. Validation copy (local only, not shipped)

The owner's local copy is a Windows repack installer, not an installed game. Its
`.catalyst` files are FreeArc archives compressed with LZMA and encrypted with
AES-256. The key is not the RAR password in `Password.txt`. The installer
`Data_xe.bin` is an Inno Setup 5.5 executable, so the keys are looked for in its script.

Procedure, run only on the developer machine, outside this repository:

1. Extract the Inno Setup script from `Data_xe.bin` with `innoextract`. Nothing from the
   package is executed — not natively and not under Wine.
2. Find the FreeArc passwords in the script (it turned out to hold one per archive).
3. Build a FreeArc unpacker for macOS and extract the game data from the `.catalyst`
   archives into a fresh directory.
4. If the passwords cannot be found or the archives cannot be unpacked, stop and ask the
   owner for game files from another source.

None of these tools, scripts or extracted files enter the repository.

**Outcome (2026-10-17).** The base game was extracted; nothing from the package was
executed. Step 1 needed a workaround: `innoextract` 1.9 extracts the installer's files but
cannot dump the compiled script, so the setup header was decoded with a small script
instead. The compiled `[Code]` section holds one password per archive (step 2).
The unpacker is `unarc` from `seb3773/freearc-c`, extended with FreeArc 0.67 code (DisPack,
TTA, and 0.67's key and IV decoding for archives without the `:f` flag) and built for arm64.
The game data (832 MB) is in a directory next to this repository. Not recoverable on macOS:
the radio stations and the cutscene and ambience MP3s, which the repack compresses with a
closed Windows codec (`msc`). The movies were not extracted either (a proprietary
recompressor); reVC does not play them. With this copy,
success criterion 3 can therefore only be checked for sound effects and mission dialogue;
radio needs game files from another source.

## 10. Distribution of the Builder

- Packaged with PyInstaller as a universal2 `reVC Builder.app` (a universal2 build of
  Python 3.12 or later — the first package used the python.org Python 3.13.7 installer —
  and the `PySide6-Essentials`, `cmake` and `ninja` wheels), ad-hoc signed, zipped.
- Not notarized. The README explains how to open it the first time through
  **System Settings → Privacy & Security → Open Anyway**, with placeholders where the
  owner will add screenshots.
- Because a downloaded, un-notarized app may run translocated from a read-only path,
  the Builder never writes inside its own bundle; all writes go to the locations in
  §6.3.

## 11. Testing

**Unit tests (pytest), no network, no compiler:**

- `gamefiles`: valid tree, wrong folder, missing files, mixed-case names; Steam
  detection over fake CrossOver and Whisky bottles, including no bottles and several.
- `sources`: lock-file parsing; integrity check with a matching and a wrong SHA; mirror
  fallback order with fake unreachable mirrors; a mismatch stops without trying the next
  mirror.
- `install`: `GamePath` edit on a file with comments, other sections, mixed-case keys,
  spaces around `=`, an existing `GamePath`, `[General]` without `GamePath`, no
  `[General]`, and no file — every other line unchanged byte for byte; source equal to
  `game`, and sources overlapping the Builder data directory (`game.new`, a folder inside
  `game`, the Builder data directory's parent); leftover `game.new`/`game.old` removed;
  clone-then-copy fallback; free-space check; a failed copy leaves the previous `game`
  intact.
- `pipeline`: stage ordering, resumption from a failed stage, cancellation.
- `compile`: the configure command line contains every variable listed in §8 stage 5;
  the restore-and-patch step of stage 5, run twice on a local test git repository,
  applies the patches cleanly both times.

**GUI tests (pytest-qt):** page flow from Welcome to Done with a fake engine; the error
page shows the message and copies the log; the Tools page never runs `clang` while
`xcode-select -p` fails, and shows the licence hint when `clang` fails afterwards.

**Network test (marked, run on demand):** every mirror listed in `sources.lock`
contains its pinned commit (§5, mirror rule), and every archive URL serves a file with
the pinned SHA-256.

The implementation adds unit tests beyond this list for the dependency build commands,
the toolchain checks, the subprocess runner, the CLI and the platform seam (the selector
refuses other systems; the pipeline runs against a fake platform). One unit test checks
that `patches/` applies to the Builder's own reVC checkout in the build cache; it reads
that checkout only and is skipped on a machine that has none.

**End-to-end (manual, owner's machine):** the six success criteria of §1.1.

## 12. Open decisions and checks (do not block implementation)

- Decided: this repository's own code is under the MIT License; bundled third-party
  components are listed in `THIRD_PARTY_NOTICES.md` and their licence texts ship in the
  app. The repository is hosted at https://github.com/rootless-dev/revc-builder, with CI
  and tag-driven releases in `.github/workflows/ci.yml`.
- Checking `required_files.txt` (§6.2) and the radio half of criterion 3 against a Steam
  or retail install, and building on a Mac that has only the Command Line Tools (§5).
