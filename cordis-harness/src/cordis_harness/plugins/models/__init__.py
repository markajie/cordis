"""Models plugin: LLM model service via OpenAI-compatible API.

Wires the ``model`` service onto the cordis context.  Configuration example
(``cordis.json``):

.. code-block:: json

    {
      "models": {
        "default": "gpt-4o",
        "providers": {
          "openai": {
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY"
          }
        }
      }
    }
"""

import os

from cordis import Service

from .llm import OpenAIModel, UnusableModel

name = "models"


class ModelService(Service):
    """Provides ``ctx.model.complete(messages, tools)`` → async chunk iterator."""

    def __init__(self, ctx, config=None):
        super().__init__(ctx, "model")
        cfg = config or {}
        default_model = cfg.get("default", "gpt-4o")
        providers = cfg.get("providers", {})

        self._model = self._resolve(default_model, providers)

    # ------------------------------------------------------------------
    # Resolution helpers (pure-ish; only reads env / config)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(default_model: str, providers: dict) -> OpenAIModel | UnusableModel:
        """Pick the first matching provider and build a model, or return an UnusableModel."""
        for provider_name, provider_cfg in providers.items():
            if provider_name == "openai":
                api_key_env = provider_cfg.get("api_key_env", "OPENAI_API_KEY")
                api_key = provider_cfg.get("api_key") or os.environ.get(api_key_env, "")
                if not api_key:
                    return UnusableModel(
                        default_model,
                        f"No API key found. Set the {api_key_env} environment variable "
                        f"or pass 'api_key' in the provider config.",
                    )
                return OpenAIModel(
                    model_id=default_model,
                    base_url=provider_cfg.get("base_url", "https://api.openai.com/v1"),
                    api_key=api_key,
                )

        return UnusableModel(default_model, "No matching provider configured in models.providers")

    # ------------------------------------------------------------------
    # Public API — mirrors OpenAIModel.complete signature
    # ------------------------------------------------------------------

    async def complete(self, messages: list[dict], tools: list[dict] | None = None):
        """Stream completion chunks from the configured model."""
        async for chunk in self._model.complete(messages, tools):
            yield chunk


def apply(ctx, config):
    """Plugin entry point called by the cordis loader."""
    ModelService(ctx, config)
