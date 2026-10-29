"""LiteLLM adapter — routes to any provider (Gemini, Claude, OpenAI, Ollama, etc.)

Model string examples:
  gemini/gemini-2.0-flash          # Google Gemini (needs GEMINI_API_KEY)
  gemini/gemini-1.5-flash
  anthropic/claude-sonnet-4-7      # Anthropic (needs ANTHROPIC_API_KEY)
  openai/gpt-4o                    # OpenAI (needs OPENAI_API_KEY)
  ollama/qwen3.6:35b-a3b-q4_k_m  # Local Ollama
  openrouter/moonshotai/kimi-k2    # OpenRouter (needs OPENROUTER_API_KEY)
"""

import litellm

# Suppress LiteLLM's verbose success logging
litellm.suppress_debug_info = True

DEFAULT_MODEL = "gemini/gemini-2.5-flash-lite"  # used by CLI `ask` command

# Short aliases → full LiteLLM model strings
ALIASES: dict[str, str] = {
    "flash":  "gemini/gemini-2.5-flash-lite",
    "local":  "ollama/gemma4:26b",
}


def resolve(model: str) -> str:
    return ALIASES.get(model.lower(), model)


# Model prefixes routed via Vertex AI Beta that don't support streaming
_NO_STREAM_PREFIXES = {"gemini/gemma"}


def _fake_stream(content: str):
    """Yield a single chunk that looks like a LiteLLM streaming chunk."""
    class _Delta:
        def __init__(self, c): self.content = c
    class _Choice:
        def __init__(self, c): self.delta = _Delta(c)
    class _Chunk:
        def __init__(self, c): self.choices = [_Choice(c)]
    yield _Chunk(content)


CONTEXT_CHARS = 24_000


class LiteLLMAdapter:
    context_chars: int = CONTEXT_CHARS

    def __init__(self, default_model: str = DEFAULT_MODEL):
        self.default_model = default_model
        self.context_chars = CONTEXT_CHARS

    def chat(self, messages: list[dict], *,
             model: str | None = None,
             stream: bool = False,
             think: bool = True):
        """Same interface as OllamaAdapter.chat().

        think= is ignored for cloud models (only Qwen/Ollama supports it).
        Returns full string if stream=False, else a streaming iterator of chunks.
        """
        resolved = resolve(model or self.default_model)
        # Some models don't support streaming via LiteLLM — fetch non-streaming
        # and wrap in a fake single-chunk stream so callers stay uniform.
        force_no_stream = any(resolved.startswith(p) for p in _NO_STREAM_PREFIXES)
        resp = litellm.completion(
            model=resolved,
            messages=messages,
            stream=stream and not force_no_stream,
        )
        if stream:
            return resp if not force_no_stream else _fake_stream(resp.choices[0].message.content)
        return resp.choices[0].message.content
