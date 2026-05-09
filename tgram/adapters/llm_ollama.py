import ollama

CHAT_MODEL  = "gemma4:26b"
EMBED_MODEL = "nomic-embed-text-v2-moe:latest"
EMBED_DIM   = 768


class OllamaAdapter:
    def __init__(self, host: str = "http://localhost:11434"):
        self._client = ollama.Client(host=host)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batch embed texts. Returns list of 768-dim vectors."""
        resp = self._client.embed(model=EMBED_MODEL, input=texts)
        return resp["embeddings"]

    def chat(self, messages: list[dict], *, model: str = CHAT_MODEL,
             stream: bool = False, think: bool = True):
        """Call Ollama chat completion.

        messages — list of {"role": "system"|"user"|"assistant", "content": str}
        stream   — if True, returns an iterator of response chunks
        think    — qwen3 emits <think>…</think> before the answer;
                   set False to suppress it for faster/cleaner output
        """
        options = {} if think else {"think": False}
        if stream:
            # Wrap Ollama chunks to expose .choices[0].delta.content
            # so the caller can use the same code as LiteLLM streams.
            raw = self._client.chat(model=model, messages=messages,
                                    stream=True, options=options)
            return _ollama_to_litellm_stream(raw)
        resp = self._client.chat(model=model, messages=messages, options=options)
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
