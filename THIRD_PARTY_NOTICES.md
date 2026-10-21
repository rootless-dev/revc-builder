# Third-party notices

reVC Builder's own code is under the MIT License (`LICENSE`). The packaged
`reVC Builder.app` also contains the third-party components below, each under its own
licence. Their licence texts are in `Contents/Resources/licenses/` inside the app.

| Component | Licence | Source |
|---|---|---|
| Qt 6 and PySide6 / Shiboken6 (PySide6-Essentials 6.9.3) | LGPL-3.0 (`LGPL-3.0.txt`, which builds on `GPL-3.0.txt`) | https://code.qt.io/cgit/pyside/pyside-setup.git/ and https://download.qt.io/official_releases/QtForPython/ |
| Python 3.13 runtime | Python Software Foundation License (`Python-LICENSE.txt`) | https://www.python.org/downloads/source/ |
| CMake 4.4.4 (PyPI `cmake` wheel) | BSD-3-Clause (`CMake-LICENSE_BSD_3.txt`); the wheel packaging is Apache-2.0 (`CMake-wheel-LICENSE_Apache_20.txt`) | https://cmake.org/download/ and https://github.com/scikit-build/cmake-python-distributions |
| Ninja 1.13.2 (PyPI `ninja` wheel) | Apache-2.0 (`Ninja-LICENSE_Apache_20.txt`) | https://github.com/ninja-build/ninja |
| Monoton and Audiowide fonts | SIL Open Font License 1.1 (`OFL.txt` next to each font in `gui/style/fonts/`) | https://fonts.google.com/ |

## Qt and PySide6 under the LGPL

Qt and PySide6 are used unmodified. They are shipped as separate dynamic libraries — the
Qt frameworks in `Contents/Frameworks/PySide6/Qt/lib/` and the PySide6/Shiboken6 modules
in `Contents/Frameworks/PySide6/` and `Contents/Frameworks/shiboken6/` — so they can be
replaced with compatible versions you build yourself. Their complete corresponding source code is
available from the source links above for the exact version listed.

## Source code from reVC and librw in the app

The app carries the patches and overlay files it applies to reVC and librw at build time
(`patches/` and `renderers/`, in `Contents/Resources/vcbuilder/data/`):

- The WGPU driver in `renderers/wgpu/librw/files/src/wgpu/` and the frame-dump patch in
  `renderers/gl3/librw/patches/` are adapted from librw's OpenGL 3 backend,
  Copyright (c) 2014 aap, under the MIT License; the files keep that notice. librw:
  https://github.com/aap/librw (the pinned mirror is listed in `sources.lock`).
- The patches contain short excerpts of reVC's and librw's source as context, and
  `renderers/wgpu/revc/files/src/extras/shaders/wgpu/` holds WGSL translations of three of
  reVC's fragment shaders (colour filter, contrast, screen droplets). reVC is distributed
  under the licence in its repository's `LICENSE.md` (MIT with an additional condition).

## Not included

The app does not contain reVC, librw, GLFW, OpenAL Soft or mpg123 as programs or as
complete source trees. The Builder downloads their source code on your Mac at build time
from the pinned locations in `sources.lock`, and they keep their own licences.

The prebuilt wgpu renderer library (`rwgpu`) is not part of the app either: a build with
`--renderer wgpu` downloads it from this repository's releases. Its archive contains
`THIRD_PARTY_LICENSES.txt` with the licences of the Rust crates linked into it (wgpu and
its dependencies, under MIT and Apache-2.0 terms).
