"""Kernel plugin wiring — registers the ``kernel`` service.

Reads ``sandbox`` and ``timeout`` from the plugin config (``cordis.json`` →
``kernel`` section) and exposes a :class:`~cordis_harness.plugins.kernel.executor.Kernel`
instance as the ``kernel`` service on the context.

The kernel's namespace is cleaned up via ``ctx.fiber.effect()`` so that it
is released when the owning fiber unloads.
"""

from cordis import Service

from .executor import Kernel

name = "kernel"


class KernelService(Service):
    """Cordis service wrapper around the pure :class:`Kernel` executor.

    Registered under the service name ``kernel``; other plugins access it
    as ``ctx.kernel`` and rely on its :pyattr:`spec`, :pyattr:`confined`,
    :pymeth:`instructions`, :pymeth:`run`, and :pymeth:`release` methods.
    """

    def __init__(self, ctx, *, sandbox: bool = True, timeout: int = 30) -> None:
        super().__init__(ctx, "kernel")
        self._impl = Kernel(sandbox=sandbox, timeout=timeout)

        # Ensure the namespace is cleared when the fiber unloads.
        ctx.fiber.effect(self._setup, "kernel-namespace")

    # -- effect setup / cleanup ----------------------------------------------

    def _setup(self):
        """Effect: nothing to allocate; cleanup releases the namespace."""
        return lambda: self._impl.release()

    # -- delegated public API ------------------------------------------------

    @property
    def spec(self):
        """LLM tool specification dict for the ``python`` tool."""
        return self._impl.spec

    @property
    def confined(self) -> bool:
        """Whether code runs in a sandboxed environment."""
        return self._impl.confined

    def instructions(self) -> str:
        """System-prompt guidance for the execution environment."""
        return self._impl.instructions()

    def run(self, code: str) -> str:
        """Execute *code* in the persistent namespace and return output."""
        return self._impl.run(code)

    def release(self) -> str:
        """Reset the persistent namespace."""
        return self._impl.release()


def apply(ctx, config):
    """Plugin entry point — instantiate and register the kernel service."""
    sandbox = config.get("sandbox", True) if isinstance(config, dict) else True
    timeout = config.get("timeout", 30) if isinstance(config, dict) else 30
    KernelService(ctx, sandbox=sandbox, timeout=timeout)
