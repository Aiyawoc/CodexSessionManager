# Third-party notices

CodexSessionManager bundles or depends on the following components in packaged builds:

- Qt for Python / PySide6 6.11.1 — LGPLv3/GPLv3/commercial terms; see the licenses shipped by the PySide6 distribution.
- age 1.3.1 — BSD-3-Clause. The official darwin-arm64 release archive is verified by the pinned SHA-256 and Sigsum proof described in `packaging/age-v1.3.1.json` before bundling.
- Nuitka 4.0 — GPLv3 with its Runtime Library Exception for generated binaries. The build applies the tracked `packaging/patches/nuitka-4.0-macos-utf8-path.patch` only after verifying the exact upstream source hash, then restores the installed source.
- Other Python packages are pinned in `uv.lock`; their upstream license metadata remains authoritative for any public distribution review.

The build script copies the complete age license, age verification metadata, this notice, and the Nuitka patch provenance into `CodexSessionManager.app/Contents/Resources/licenses/`. A local ad-hoc build is not represented as a notarized public release.
