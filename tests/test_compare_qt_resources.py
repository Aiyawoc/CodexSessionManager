from __future__ import annotations

import runpy
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

compare_resources = cast(
    Callable[[Path, Path], None],
    runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/compare_qt_resources.py"),
        run_name="compare_qt_resources_test",
    )["compare_resources"],
)


def _write_resource(path: Path, *, timestamp: bytes, data: bytes = b"payload") -> None:
    tree_prefix = bytes(range(14))
    path.write_text(
        "\n".join(
            (
                f"qt_resource_data = {data!r}",
                "qt_resource_name = b'name'",
                f"qt_resource_struct = {(tree_prefix + timestamp)!r}",
            )
        ),
        encoding="utf-8",
    )


def test_compare_resources_ignores_only_v3_timestamps(tmp_path: Path) -> None:
    actual = tmp_path / "actual.py"
    expected = tmp_path / "expected.py"
    _write_resource(actual, timestamp=b"12345678")
    _write_resource(expected, timestamp=b"abcdefgh")

    compare_resources(actual, expected)


def test_compare_resources_rejects_payload_changes(tmp_path: Path) -> None:
    actual = tmp_path / "actual.py"
    expected = tmp_path / "expected.py"
    _write_resource(actual, timestamp=b"12345678", data=b"changed")
    _write_resource(expected, timestamp=b"abcdefgh")

    with pytest.raises(ValueError, match="qt_resource_data"):
        compare_resources(actual, expected)
