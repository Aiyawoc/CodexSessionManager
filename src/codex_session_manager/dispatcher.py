"""Single executable dispatcher used by the standalone macOS bundle."""

from __future__ import annotations

import sys
from typing import Literal, cast


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
