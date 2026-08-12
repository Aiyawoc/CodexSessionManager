# Third-party notices

CodexSessionManager bundles or depends on the following components in packaged builds:

- Qt for Python / PySide6 6.11.1 — LGPLv3/GPLv3/commercial terms; see the licenses shipped by the PySide6 distribution.
- age 1.3.1 — BSD-3-Clause. The official darwin-arm64 and windows-amd64 release archives are verified by the pinned SHA-256 and Sigsum proofs described in `packaging/age-v1.3.1.json` and `packaging/age-v1.3.1-windows-amd64.json` before bundling.
- Nuitka 4.0 — GPLv3 with its Runtime Library Exception for generated binaries. The build applies the tracked `packaging/patches/nuitka-4.0-macos-utf8-path.patch` only after verifying the exact upstream source hash, then restores the installed source.
- Other Python packages are pinned in `uv.lock`; their upstream license metadata remains authoritative for any public distribution review.

The build scripts copy the complete age license, age verification metadata, this notice, and the Nuitka license files into each standalone bundle. The macOS build also carries the tracked Nuitka patch provenance. Unsigned or ad-hoc-signed test builds are not represented as notarized or production-ready releases.
