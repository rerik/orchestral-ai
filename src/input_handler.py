"""
Enhanced terminal input with readline support.

Provides readline-backed input (arrow keys, history navigation) for both
agent.py and team.py, replacing plain input() calls.
"""

import atexit
import os
import sys


def setup_readline(history_file: str = "~/.smart_agent_history") -> None:
    """Configure readline with history persistence.

    Loads previous history from *history_file*, sets a maximum history length
    of 1000 entries, and registers an atexit handler to save history when the
    process exits.

    If the readline module is not available (e.g. on platforms without GNU
    readline or libedit), a warning is printed and the function returns early.
    """
    try:
        import readline  # noqa: F811 – imported for its side effects
    except ImportError:
        print("warning: readline module not available; arrow-key navigation disabled")
        return

    path = os.path.expanduser(history_file)

    # Load existing history (silently skip if file does not exist)
    try:
        readline.read_history_file(path)
    except FileNotFoundError:
        pass

    readline.set_history_length(1000)

    def _save_history(history_path: str = path) -> None:
        """Write the current readline history to *history_path*."""
        try:
            readline.write_history_file(history_path)
        except OSError:
            pass

    atexit.register(_save_history)


def get_input(prompt: str = ">>> ") -> str:
    """Read a line of input from the user.

    Thin wrapper around the built-in input() that strips the result and
    handles EOF / KeyboardInterrupt by cleanly exiting the process.
    """
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
