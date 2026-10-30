from unittest.mock import MagicMock
import pytest

from tgram.adapters.llm_litellm import LiteLLMAdapter, resolve, _fake_stream
from tgram.adapters.llm_ollama import OllamaAdapter, NUM_CTX, CONTEXT_CHARS, _ollama_to_litellm_stream


def test_ollama_adapter_config():
    adapter = OllamaAdapter()
    assert adapter.context_chars == 12000
    assert NUM_CTX == 12288

    mock_client = MagicMock()
    adapter._client = mock_client

    # Test non-streaming chat passes options with num_ctx
    mock_resp = MagicMock()
    mock_resp.message.content = "Response from model"
    mock_client.chat.return_value = mock_resp

    res = adapter.chat([{"role": "user", "content": "hi"}], think=False)
    assert res == "Response from model"
    mock_client.chat.assert_called_once_with(
        model="gemma4:26b",
        messages=[{"role": "user", "content": "hi"}],
        think=False,
        options={"num_ctx": 12288},
    )


def test_ollama_stream_adapter_chunking():
    # Mock raw ollama chunk
    mock_chunk = MagicMock()
    mock_chunk.message.content = "streaming piece"

    stream = _ollama_to_litellm_stream([mock_chunk])
    chunk = next(stream)
    assert chunk.choices[0].delta.content == "streaming piece"


def test_litellm_adapter_config():
    adapter = LiteLLMAdapter()
    assert adapter.context_chars == 24000
    assert resolve("flash") == "gemini/gemini-2.5-flash-lite"
    assert resolve("local") == "ollama/gemma4:26b"
    assert resolve("custom/model") == "custom/model"


def test_litellm_fake_stream():
    stream = _fake_stream("complete answer")
    chunk = next(stream)
    assert chunk.choices[0].delta.content == "complete answer"
