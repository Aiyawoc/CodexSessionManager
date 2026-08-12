"""Render the repository SVG icon as a Windows ICO for Nuitka."""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def build_icon(source: Path, output: Path, *, size: int = 256) -> None:
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"invalid SVG icon: {source}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    try:
        renderer.render(painter, QRectF(0, 0, size, size))
    finally:
        painter.end()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output), "ICO"):
        raise RuntimeError(f"Qt could not write Windows icon: {output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("assets/app-icon.svg"))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    build_icon(arguments.source, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
