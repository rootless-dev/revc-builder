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

## Not included

The app does not contain reVC, librw, GLFW, OpenAL Soft or mpg123. The Builder downloads
their source code on your Mac at build time from the pinned locations in `sources.lock`,
and they keep their own licences.
