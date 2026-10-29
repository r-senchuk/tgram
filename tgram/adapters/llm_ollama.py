import ollama

CHAT_MODEL    = "gemma4:26b"
EMBED_MODEL   = "nomic-embed-text-v2-moe:latest"
EMBED_DIM     = 768
CONTEXT_CHARS = 12_000
NUM_CTX       = 12288


class OllamaAdapter:
    context_chars: int = CONTEXT_CHARS

    def __init__(self, host: str = "http://localhost:11434", timeout: float = 5.0, chat_timeout: float = 120.0):
        self.host = host
        self.timeout = timeout
        self.context_chars = CONTEXT_CHARS
        self._embed_client = ollama.Client(host=host, timeout=timeout)
        self._client = ollama.Client(host=host, timeout=chat_timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts. Returns list of 768-dim vectors."""
        resp = self._embed_client.embed(model=EMBED_MODEL, input=texts)
        return resp["embeddings"]

    def chat(self, messages: list[dict], *, model: str = CHAT_MODEL,
             stream: bool = False, think: bool = True):
        """Call Ollama chat completion.

        messages — list of {"role": "system"|"user"|"assistant", "content": str}
        stream   — if True, returns an iterator of response chunks
        think    — passed top-level to control reasoning (<think> tags)
        """
        options = {"num_ctx": NUM_CTX}
        if stream:
            # Wrap Ollama chunks to expose .choices[0].delta.content
            # so the caller can use the same code as LiteLLM streams.
            raw = self._client.chat(model=model, messages=messages,
                                    stream=True, think=think, options=options)
            return _ollama_to_litellm_stream(raw)
        resp = self._client.chat(model=model, messages=messages, think=think, options=options)
        return resp.message.content


class _OllamaChunk:
    """Adapter that gives Ollama chunks the same shape as LiteLLM chunks."""
    class _Delta:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.delta = _OllamaChunk._Delta(content)

    def __init__(self, chunk):
        self.choices = [_OllamaChunk._Choice(chunk.message.content)]


def _ollama_to_litellm_stream(raw):
    for chunk in raw:
        yield _OllamaChunk(chunk)
