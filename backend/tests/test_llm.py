import json

import pytest
from pydantic import BaseModel

from app.llm import DeepSeekClient


class ExamplePayload(BaseModel):
    value: str


def test_complete_json_rejects_empty_content(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = DeepSeekClient()
    monkeypatch.setattr(client, "_complete", lambda _system, _user: "")

    with pytest.raises(RuntimeError, match="empty content"):
        client.complete_json_with_raw("Return JSON only.", "{}", ExamplePayload)


def test_complete_includes_max_tokens(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"value":"ok"}'},
                    }
                ]
            }

    def fake_post(*_args, **kwargs):
        captured.update(kwargs["json"])
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "123")
    monkeypatch.setattr("app.llm.httpx.post", fake_post)

    client = DeepSeekClient()
    assert client._complete("Return JSON only.", "{}") == '{"value":"ok"}'
    assert captured["max_tokens"] == 123


def test_complete_rejects_length_finish_reason(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"value":"cut off"'},
                    }
                ]
            }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.llm.httpx.post", lambda *_args, **_kwargs: FakeResponse())

    client = DeepSeekClient()
    with pytest.raises(RuntimeError, match="truncated"):
        client._complete("Return JSON only.", "{}")


def test_stream_rejects_length_finish_reason(monkeypatch):
    captured = {}
    streamed_chunks = []

    class FakeStreamResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        def iter_lines(self):
            yield f"data: {json.dumps({'choices': [{'delta': {'content': '{\"value\"'}, 'finish_reason': None}]})}"
            yield f"data: {json.dumps({'choices': [{'delta': {'content': ':\"cut\"'}, 'finish_reason': None}]})}"
            yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'length'}]})}"
            yield "data: [DONE]"

    def fake_stream(*_args, **kwargs):
        captured.update(kwargs["json"])
        return FakeStreamResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("app.llm.httpx.stream", fake_stream)

    client = DeepSeekClient()
    with pytest.raises(RuntimeError, match="truncated"):
        client._complete_stream("Return JSON only.", "{}", streamed_chunks.append)

    assert captured["max_tokens"] == 8192
    assert streamed_chunks == ['{"value"', ':"cut"']
