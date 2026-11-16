"""`uv run chat --executive <id>`: the REPL. It has no logic and calls only the Turn API (P20)."""

import os
import sys
import threading
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console

from dca.app.turn_api import TurnAPI, UnknownExecutive
from dca.cli.render import THEME, Mode, Renderer
from dca.config import Settings
from dca.core.answer import Answer

ApiFactory = Callable[[Settings], TurnAPI]


def _default_api(settings: Settings) -> TurnAPI:
    from dca.app.wiring import build_turn_api

    return build_turn_api(settings)


def detect_mode(*, no_color: bool, plain: bool, ascii_: bool, no_animation: bool, stream: Any) -> Mode:
    tty = bool(getattr(stream, "isatty", lambda: False)())
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    plain = plain or not tty
    return Mode(
        color=not (no_color or plain or "NO_COLOR" in os.environ),
        plain=plain,
        ascii=ascii_ or (bool(encoding) and encoding != "utf8"),
        animation=not (no_animation or plain or "NO_COLOR" in os.environ),
    )


def make_console(mode: Mode, **options: Any) -> Console:
    """With no color, the Console has no color system: it writes no ANSI codes at all (DS4)."""
    return Console(
        theme=THEME,
        no_color=not mode.color,
        color_system="standard" if mode.color else None,
        highlight=False,
        emoji=False,
        **options,
    )


def make_app(api_factory: ApiFactory = _default_api, settings_factory: Callable[[], Settings] = Settings) -> typer.Typer:
    app = typer.Typer(add_completion=False)

    @app.command()
    def chat(
        executive: str = typer.Option(..., "--executive", "-e", help="Your Executive ID from executives.json."),
        no_color: bool = typer.Option(False, "--no-color", help="No colors."),
        plain: bool = typer.Option(False, "--plain", help="Plain text for screen readers and pipes."),
        ascii_: bool = typer.Option(False, "--ascii", help="ASCII symbols only."),
        no_animation: bool = typer.Option(False, "--no-animation", help="Static progress lines."),
    ) -> None:
        """Ask questions about the sales data."""
        mode = detect_mode(no_color=no_color, plain=plain, ascii_=ascii_, no_animation=no_animation, stream=sys.stdout)
        console = make_console(mode)
        settings = settings_factory()
        renderer = Renderer(console, mode, settings.display.header_max_brands)
        api = api_factory(settings)
        try:
            info = api.start_session(executive)
        except UnknownExecutive as error:
            renderer.unknown_executive(error.valid_ids)
            raise typer.Exit(2) from None
        renderer.header(info)
        repl(api, info.session_id, renderer, console)

    return app


def repl(api: TurnAPI, session_id: str, renderer: Renderer, console: Console) -> None:
    pending = False
    number = 0
    while True:
        try:
            line = console.input(renderer.prompt(pending))
        except (EOFError, KeyboardInterrupt):
            break
        text = line.strip()
        if not text:
            continue
        if text.startswith("/"):
            name, _, args = text[1:].partition(" ")
            if name == "exit":
                break
            if name == "help":
                renderer.help()
                continue
            answer = api.command(session_id, name, args.strip())
        else:
            number += 1
            renderer.separator(number)
            status = renderer.start_status()
            try:
                answer = run_turn(api, session_id, text, status.update)
            finally:
                status.stop()
        renderer.answer(answer)
        pending = answer.awaiting_confirmation


def _wait(done: threading.Event) -> None:
    # Not Thread.join(): a KeyboardInterrupt in join() can break the thread state, and
    # is_alive() then returns False before the Turn ends.
    done.wait(0.1)


def run_turn(
    api: TurnAPI, session_id: str, text: str, on_progress: Callable[[str, dict[str, Any]], None] | None = None
) -> Answer:
    """Runs one Turn in a worker thread. Ctrl+C during the Turn cancels only the Turn (cli.md C2)."""
    result: dict[str, Answer] = {}
    done = threading.Event()

    def work() -> None:
        try:
            result["answer"] = api.send_message(session_id, text, on_progress)
        finally:
            done.set()

    threading.Thread(target=work, daemon=True).start()
    while not done.is_set():
        try:
            _wait(done)
        except KeyboardInterrupt:
            api.cancel(session_id)
    return result["answer"]


app = make_app()


def main() -> None:
    app()
