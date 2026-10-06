"""Context plugin: project context service."""
from cordis import Service
from .project import ProjectContext

name = 'context'


class ContextService(Service):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'system')
        cfg = config or {}
        self._impl = ProjectContext(
            project_dir=cfg.get('project_dir', '.'),
            instructions_file=cfg.get('instructions_file', 'CLAUDE.md'),
        )

    def text(self) -> str:
        return self._impl.text()


def apply(ctx, config):
    ContextService(ctx, config)
