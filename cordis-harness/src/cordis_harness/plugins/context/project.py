"""Project context: working directory and instructions."""
from pathlib import Path


class ProjectContext:
    """Provides system context about the current project."""

    def __init__(self, project_dir: str = ".", instructions_file: str = "CLAUDE.md"):
        self._project_dir = Path(project_dir).resolve()
        self._instructions_file = instructions_file

    def text(self) -> str:
        """Return system prompt text about the working environment."""
        parts = []
        parts.append(f"Working directory: {self._project_dir}")

        # Read instructions file if it exists
        instructions_path = self._project_dir / self._instructions_file
        if instructions_path.exists():
            content = instructions_path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"\nProject instructions ({self._instructions_file}):\n{content}")

        return "\n".join(parts)
