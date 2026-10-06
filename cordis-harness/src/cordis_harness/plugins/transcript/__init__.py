"""Transcript plugin: conversation history persistence."""
import json
from pathlib import Path
from typing import Any, Mapping

from cordis import Service

name = 'transcript'


class TranscriptService(Service):
    """Manages conversation message history with optional JSONL file persistence.

    When a ``path`` is provided in the config, messages are appended to a JSONL
    file (one JSON object per line) and reloaded on startup so sessions can be
    resumed.  Without a path the service operates purely in memory.
    """

    def __init__(self, ctx, config: dict[str, Any] | None = None):
        super().__init__(ctx, 'transcript')
        self._path: Path | None = None
        raw_path = (config or {}).get('path')
        if raw_path:
            self._path = Path(raw_path)
        self._messages: list[Mapping[str, Any]] = []
        if self._path is not None:
            self._load()

    @property
    def messages(self) -> list[Mapping[str, Any]]:
        """Return a shallow copy of the current message history."""
        return list(self._messages)

    def append(self, message: Mapping[str, Any]) -> None:
        """Append a message to the transcript.

        The message is added to the in-memory list and, when file persistence
        is configured, appended as a single JSON line to the backing file.
        """
        self._messages.append(message)
        if self._path is not None:
            self._save_append(message)

    def clear(self) -> None:
        """Clear all messages from the transcript.

        When file persistence is configured the backing file is truncated.
        """
        self._messages.clear()
        if self._path is not None:
            try:
                self._path.write_text('', encoding='utf-8')
            except OSError as exc:
                self.ctx.logger.error(
                    f"Failed to truncate transcript file {self._path}: {exc}"
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read existing JSONL file line by line into the in-memory list."""
        assert self._path is not None
        if not self._path.is_file():
            return
        try:
            text = self._path.read_text(encoding='utf-8')
        except OSError as exc:
            self.ctx.logger.error(
                f"Failed to read transcript file {self._path}: {exc}"
            )
            return
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                message = json.loads(stripped)
            except json.JSONDecodeError as exc:
                self.ctx.logger.warn(
                    f"Skipping malformed JSON at {self._path}:{lineno}: {exc}"
                )
                continue
            self._messages.append(message)

    def _save_append(self, message: Mapping[str, Any]) -> None:
        """Append one JSON-encoded line to the backing file."""
        assert self._path is not None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(message, ensure_ascii=False) + '\n')
        except OSError as exc:
            self.ctx.logger.error(
                f"Failed to append to transcript file {self._path}: {exc}"
            )


def apply(ctx, config):
    """Plugin entry point: instantiate and register the TranscriptService."""
    TranscriptService(ctx, config)
