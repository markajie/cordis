"""Python code executor with optional sandboxing.

Pure business logic — no cordis imports. This module provides a persistent
Python namespace for executing code cells, capturing stdout/stderr, and
exposing a tool specification compatible with LLM tool-calling interfaces.

"""

import contextlib
import io
from typing import TypedDict


class ToolSpec(TypedDict):
    """LLM tool specification for the python execution tool."""

    name: str
    description: str
    parameters: dict


class Kernel:
    """Persistent Python namespace for code execution.

    Maintains state across multiple ``run()`` calls so that variables,
    imports, and function definitions persist between cells — mirroring
    an interactive Python session.

    Parameters
    ----------
    sandbox:
        When ``True`` the kernel is considered *confined*: code runs in a
        restricted environment and does not require user approval.  When
        ``False`` every cell should be confirmed by the user before
        execution (the harness is responsible for the confirmation flow;
        this flag is exposed via :pyattr:`confined`).
    timeout:
        Maximum wall-clock seconds a single cell may run.  Currently
        advisory — stored for consumers that implement enforcement.
    """

    TOOL_SPEC: ToolSpec = {
        "name": "python",
        "description": (
            "Run Python in a persistent namespace, in the project directory: "
            "variables, imports and functions stay for later calls. print() "
            "what you want to see; a last expression is shown too. Read and "
            "write files with open() or pathlib, run programs with subprocess."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python code to execute.",
                }
            },
            "required": ["code"],
        },
    }

    def __init__(self, *, sandbox: bool = True, timeout: int = 30) -> None:
        self._sandbox = sandbox
        self._timeout = timeout
        self._namespace: dict = {"__builtins__": __builtins__}

    # -- public read-only properties -----------------------------------------

    @property
    def spec(self) -> ToolSpec:
        """Return the LLM tool specification for this kernel."""
        return self.TOOL_SPEC

    @property
    def confined(self) -> bool:
        """Whether the kernel runs in a sandboxed / confined mode.

        When ``True``, cells execute without user approval because the
        sandbox restricts file-system and network access.  When ``False``,
        the harness should ask the user before running each cell.
        """
        return self._sandbox

    @property
    def timeout(self) -> int:
        """Advisory per-cell timeout in seconds."""
        return self._timeout

    # -- instructions --------------------------------------------------------

    def instructions(self) -> str:
        """Return system-prompt guidance describing the execution environment.

        The text adapts based on whether the kernel is confined so the
        model receives accurate safety information.
        """
        base = (
            "You act by writing Python: your one tool is `python`, and its "
            "`code` runs in a persistent namespace whose working directory is "
            "the project. There is nothing in the namespace but Python: read "
            "and edit files with open() or pathlib, run programs with "
            "subprocess, keep results in variables, and print what you need "
            "to see. Read a traceback and fix the code."
        )

        if self._sandbox:
            where = (
                "Your code runs in a sandbox: it can write only inside the "
                "project directory, cannot reach the network, and cannot read "
                "credentials. Cells run without asking."
            )
        else:
            where = (
                "Your code runs unjailed, with the person's own permissions: "
                "each cell is shown to the person and runs only if they "
                "approve it, so keep cells small and say what they do."
            )

        return f"{base}\n\n{where}"

    # -- execution -----------------------------------------------------------

    def run(self, code: str) -> str:
        """Execute *code* in the persistent namespace and return output.

        Captures both ``stdout`` and ``stderr``.  If the code raises an
        exception the error message is returned instead of propagating,
        so the agent loop always receives a string result.
        """
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exec(code, self._namespace)  # noqa: S102
            output = stdout.getvalue()
            err = stderr.getvalue()
            if err:
                output += f"\n[stderr]\n{err}"
            return output.strip() or "(no output)"
        except Exception as exc:
            return f"Error: {type(exc).__name__}: {exc}"

    # -- lifecycle -----------------------------------------------------------

    def release(self) -> str:
        """Reset the persistent namespace.

        After this call the kernel behaves as if freshly constructed: all
        variables, imports, and definitions are discarded.  Returns a
        human-readable confirmation string.
        """
        self._namespace.clear()
        self._namespace["__builtins__"] = __builtins__
        return "Kernel namespace cleared."
