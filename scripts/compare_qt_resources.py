#!/usr/bin/env python3
"""Compare generated Qt resources while ignoring checkout-dependent timestamps."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

_RESOURCE_FIELDS = ("qt_resource_data", "qt_resource_name", "qt_resource_struct")
_TREE_ENTRY_SIZE_V3 = 22
_TREE_PAYLOAD_SIZE_V3 = 14


def _resource_fields(path: Path) -> dict[str, bytes]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    fields: dict[str, bytes] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in _RESOURCE_FIELDS:
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, bytes):
            raise TypeError(f"{path}: {target.id} is not bytes")
        fields[target.id] = value

    missing = set(_RESOURCE_FIELDS) - fields.keys()
    if missing:
        raise ValueError(f"{path}: missing resource fields: {', '.join(sorted(missing))}")
    return fields


def _without_v3_timestamps(resource_struct: bytes) -> bytes:
    """Return Qt RCC v3 tree records without their 8-byte mtime fields."""
    if len(resource_struct) % _TREE_ENTRY_SIZE_V3:
        raise ValueError("unexpected Qt resource tree layout; refusing to ignore unknown bytes")
    return b"".join(
        resource_struct[offset : offset + _TREE_PAYLOAD_SIZE_V3]
        for offset in range(0, len(resource_struct), _TREE_ENTRY_SIZE_V3)
    )


def compare_resources(actual: Path, expected: Path) -> None:
    actual_fields = _resource_fields(actual)
    expected_fields = _resource_fields(expected)

    for field in ("qt_resource_data", "qt_resource_name"):
        if actual_fields[field] != expected_fields[field]:
            raise ValueError(f"generated Qt resource payload differs: {field}")

    actual_struct = actual_fields["qt_resource_struct"]
    expected_struct = expected_fields["qt_resource_struct"]
    if actual_struct == expected_struct:
        return
    if _without_v3_timestamps(actual_struct) != _without_v3_timestamps(expected_struct):
        raise ValueError("generated Qt resource tree differs beyond file timestamps")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actual", type=Path)
    parser.add_argument("expected", type=Path)
    args = parser.parse_args()
    compare_resources(args.actual, args.expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
