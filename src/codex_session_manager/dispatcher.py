"""Single executable dispatcher shared by standalone desktop bundles."""

from __future__ import annotations

import sys
from io import TextIOWrapper
from typing import Literal, cast


def _configure_windows_stdio(
    *,
    platform: str = sys.platform,
    streams: tuple[object, ...] | None = None,
) -> None:
    """Make native Windows CLI and Hook output deterministic and Unicode-safe."""

    if platform != "win32":
        return
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        if isinstance(stream, TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def _run_cli(arguments: list[str]) -> int:
    import click
    import typer

    from codex_session_manager.cli import app

    command = typer.main.get_command(app)
    try:
        result = command.main(args=arguments, prog_name="csm", standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return int(exc.exit_code)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    return int(result) if isinstance(result, int) else 0


def main() -> int:
    _configure_windows_stdio()
    arguments = sys.argv[1:]
    if not arguments:
        from codex_session_manager.gui.main import run_gui

        return run_gui()
    if arguments[0] == "cli":
        return _run_cli(arguments[1:])
    if (
        len(arguments) == 2
        and arguments[0] == "hook"
        and arguments[1]
        in {
            "precompact",
            "postcompact",
        }
    ):
        from codex_session_manager.hooks import run_hook

        mode = cast(Literal["precompact", "postcompact"], arguments[1])
        return run_hook(mode)
    if arguments[0] == "--thread" and len(arguments) == 2:
        from codex_session_manager.gui.main import run_gui

        return run_gui(thread_id=arguments[1])
    return _run_cli(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
