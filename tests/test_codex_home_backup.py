from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
BACKUP_SCRIPT = PROJECT_ROOT / "scripts" / "backup_codex_home.sh"
AGE_BINARY = PROJECT_ROOT / "vendor" / "age" / "age"


def _run_backup_script(
    *arguments: str, process_probe_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CSM_AGE_BIN"] = str(AGE_BINARY)
    if process_probe_dir is not None:
        environment["PATH"] = f"{process_probe_dir}:{environment['PATH']}"
    return subprocess.run(
        [str(BACKUP_SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    )


@pytest.mark.integration
def test_local_codex_home_snapshot_round_trip_and_no_overwrite(tmp_path: Path) -> None:
    if sys.platform != "darwin":
        pytest.skip("local Codex home snapshot is a macOS acceptance material")
    if not AGE_BINARY.is_file() or not os.access(AGE_BINARY, os.X_OK):
        pytest.skip("the pinned age binary is unavailable")
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        pytest.skip("ssh-keygen is unavailable")

    source = tmp_path / "Codex home with spaces"
    process_probe_dir = tmp_path / "bin"
    process_probe_dir.mkdir()
    process_probe = process_probe_dir / "pgrep"
    process_probe.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    process_probe.chmod(0o700)
    nested = source / "state"
    nested.mkdir(parents=True)
    (source / "config.toml").write_text("[test]\nvalue = 'fixture'\n", encoding="utf-8")
    (source / "auth.json").write_text('{"token":"must not be copied"}\n', encoding="utf-8")
    (nested / "rollout.jsonl").write_text('{"id":"fixture"}\n', encoding="utf-8")
    (source / "state-link").symlink_to("state")

    identity = tmp_path / "age-test-identity"
    subprocess.run(
        [ssh_keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(identity)],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    recipients = tmp_path / "recipients.txt"
    recipients.write_text(
        identity.with_suffix(".pub").read_text(encoding="utf-8").splitlines()[0] + "\n",
        encoding="utf-8",
    )

    inside_backup = source / "rollback snapshot.tar.age"
    refused_inside = _run_backup_script(
        "create",
        "--source",
        str(source),
        "--destination",
        str(inside_backup),
        "--recipients-file",
        str(recipients),
        process_probe_dir=process_probe_dir,
    )
    assert refused_inside.returncode != 0
    assert not inside_backup.exists()

    backup = tmp_path / "rollback snapshot.tar.age"
    created = _run_backup_script(
        "create",
        "--source",
        str(source),
        "--destination",
        str(backup),
        "--recipients-file",
        str(recipients),
        process_probe_dir=process_probe_dir,
    )
    assert created.returncode == 0, created.stderr
    assert backup.is_file()
    assert backup.with_name(backup.name + ".sha256").is_file()
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600

    verified = _run_backup_script(
        "verify",
        "--backup",
        str(backup),
        "--identity-file",
        str(identity),
        process_probe_dir=process_probe_dir,
    )
    assert verified.returncode == 0, verified.stderr

    restored = tmp_path / "restored codex home"
    restored_result = _run_backup_script(
        "restore",
        "--backup",
        str(backup),
        "--identity-file",
        str(identity),
        "--target",
        str(restored),
        "--confirm-restore",
        "RESTORE CODEX HOME",
        process_probe_dir=process_probe_dir,
    )
    assert restored_result.returncode == 0, restored_result.stderr
    assert (restored / "config.toml").read_text(encoding="utf-8") == (
        source / "config.toml"
    ).read_text(encoding="utf-8")
    assert not (restored / "auth.json").exists()
    assert (restored / "state-link").is_symlink()
    assert (restored / "state-link").resolve() == restored / "state"

    duplicate = _run_backup_script(
        "create",
        "--source",
        str(source),
        "--destination",
        str(backup),
        "--recipients-file",
        str(recipients),
        process_probe_dir=process_probe_dir,
    )
    assert duplicate.returncode != 0
    assert "refusing to overwrite" in duplicate.stderr

    non_empty_target = tmp_path / "non-empty target"
    non_empty_target.mkdir()
    marker = non_empty_target / "keep"
    marker.write_text("do not overwrite", encoding="utf-8")
    refused_restore = _run_backup_script(
        "restore",
        "--backup",
        str(backup),
        "--identity-file",
        str(identity),
        "--target",
        str(non_empty_target),
        "--confirm-restore",
        "RESTORE CODEX HOME",
        process_probe_dir=process_probe_dir,
    )
    assert refused_restore.returncode != 0
    assert marker.read_text(encoding="utf-8") == "do not overwrite"
