"""Check Modal routing and actual request bodies without contacting a server."""
import json
import os

import httpx
import pytest
from pydantic_ai import Agent
from pydantic import BaseModel

from text2sql_mvp.app import models, retrieval, text2sql


@pytest.fixture(autouse=True)
def modal_endpoints(monkeypatch):
    monkeypatch.setenv("FAST_MODEL_BASE_URL", "https://small.example.test/v1")
    monkeypatch.setenv("SQL_MODEL_BASE_URL", "https://large.example.test/v1")


class Answer(BaseModel):
    answer: str


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["small", "large"])
async def test_modal_request(monkeypatch, tier):
    monkeypatch.setenv("MODAL_API_TOKEN", "test-id.test-secret")
    monkeypatch.delenv("REASONING_EFFORT", raising=False)
    model_name = models.FAST_MODEL if tier == "small" else models.SQL_MODEL
    model = models.modal_model(model_name, tier=tier)
    requests = []

    def respond(request):
        requests.append(request)
        body = json.loads(request.content)
        tool = body["tools"][0]["function"]["name"]
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": model_name,
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": tool, "arguments": '{"answer":"ok"}',
                }}],
            }}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(model.client, "_client", client)
        result = await Agent(model, output_type=Answer, model_settings={"max_tokens": 4096}).run("hello")

    assert result.output.answer == "ok"
    request = requests[0]
    url = os.environ["FAST_MODEL_BASE_URL"] if tier == "small" else os.environ["SQL_MODEL_BASE_URL"]
    assert str(request.url) == url + "/chat/completions"
    assert request.headers["authorization"] == "Bearer test-id.test-secret"
    body = json.loads(request.content)
    assert body["model"] == model_name
    assert body["max_completion_tokens"] == 4096
    if tier == "small":
        assert body["reasoning"] == {"enabled": True}
        assert "reasoning_effort" not in body
    else:
        assert body["reasoning_effort"] == "high"
        assert "reasoning" not in body


@pytest.mark.parametrize("token", [None, "", "  "])
def test_missing_modal_token(monkeypatch, token):
    monkeypatch.delenv("MODAL_API_TOKEN", raising=False)
    if token is not None:
        monkeypatch.setenv("MODAL_API_TOKEN", token)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    with pytest.raises(ValueError, match="MODAL_API_TOKEN"):
        models.modal_model(models.FAST_MODEL, tier="small")


@pytest.mark.parametrize("module, getter, cache, tier", [
    (text2sql, "_get_expansion_agent", "_expansion_agent", "small"),
    (text2sql, "_get_answer_agent", "_answer_agent", "small"),
    (text2sql, "_get_sql_agent", "_sql_agent", "large"),
    (retrieval, "_get_expansion_agent", "_expansion_agent", "small"),
])
def test_agent_routes(monkeypatch, module, getter, cache, tier):
    monkeypatch.setenv("MODAL_API_TOKEN", "test-id.test-secret")
    monkeypatch.setattr(module, cache, None)
    agent = getattr(module, getter)()
    expected = os.environ["FAST_MODEL_BASE_URL"] if tier == "small" else os.environ["SQL_MODEL_BASE_URL"]
    assert str(agent.model.client.base_url).rstrip("/") == expected


def test_judge_route(monkeypatch):
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda: None)
    from eval import run_eval

    monkeypatch.setenv("MODAL_API_TOKEN", "test-id.test-secret")
    monkeypatch.setattr(run_eval, "_judge_agent", None)
    agent = run_eval._get_judge_agent()
    assert str(agent.model.client.base_url).rstrip("/") == os.environ["SQL_MODEL_BASE_URL"]
    assert agent.model.model_name == run_eval.EVAL_MODEL


def test_reasoning_override_only_affects_large_model(monkeypatch):
    monkeypatch.setenv("MODAL_API_TOKEN", "test-id.test-secret")
    monkeypatch.setenv("REASONING_EFFORT", "low")
    large = models.modal_model(models.SQL_MODEL, tier="large")
    small = models.modal_model(models.FAST_MODEL, tier="small")
    assert large.settings["extra_body"] == {"reasoning_effort": "low"}
    assert small.settings["extra_body"] == {"reasoning": {"enabled": True}}


@pytest.mark.parametrize("tier, variable", [
    ("small", "FAST_MODEL_BASE_URL"),
    ("large", "SQL_MODEL_BASE_URL"),
])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_modal_endpoint(monkeypatch, tier, variable, value):
    monkeypatch.setenv("MODAL_API_TOKEN", "test-id.test-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://must-not-be-used.example.test/v1")
    monkeypatch.delenv(variable)
    if value is not None:
        monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=variable):
        models.modal_model("test-model", tier=tier)
