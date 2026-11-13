import json

import httpx
import pytest

from src import llm


@pytest.fixture
def deepseek_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    # These must never override the explicitly configured DeepSeek client.
    monkeypatch.setenv("OPENAI_API_KEY", "test-unrelated-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid")


def test_deepseek_configuration_and_overrides(deepseek_env, monkeypatch):
    client = llm.get_llm()
    assert client.model_name == "deepseek-flash"
    assert client.openai_api_base == "https://api.deepseek.com"
    assert client.openai_api_key.get_secret_value() == "test-deepseek-key"
    assert client.extra_body == {"thinking": {"type": "disabled"}}
    assert client.use_responses_api is False
    assert client.max_retries == 0
    assert client.request_timeout == 60.0
    monkeypatch.setenv("DEEPSEEK_MODEL", "custom-deepseek-model")
    assert llm.get_llm().model_name == "custom-deepseek-model"
    explicit = llm.get_llm(model="explicit-model", temperature=0.3)
    assert explicit.model_name == "explicit-model"
    assert explicit.temperature == 0.3


@pytest.mark.parametrize("key", [None, "", "   "])
def test_missing_deepseek_key_is_clear(deepseek_env, monkeypatch, key):
    if key is None:
        monkeypatch.delenv("DEEPSEEK_API_KEY")
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", key)
    with pytest.raises(RuntimeError, match="Missing DEEPSEEK_API_KEY"):
        llm.get_llm()


def test_chat_deepseek_wire_requests_and_tool_round_trip(deepseek_env, client, monkeypatch):
    """Use real ChatOpenAI serialization, graph, tools and SQLite; mock only HTTP.

    The customer is Alice, who owns order 1001, so the ownership-scoped tool
    returns the delivered status. The customer-facing response redacts tool args.
    """
    requests = []

    def respond(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer test-deepseek-key"
        body = json.loads(request.content)
        requests.append(body)
        assert body["model"] == "deepseek-flash"
        assert body["thinking"] == {"type": "disabled"}
        if len(requests) == 1:
            assert "tools" not in body
            message = {"role": "assistant", "content": "ORDER"}
        elif len(requests) == 2:
            schemas = {t["function"]["name"]: t["function"] for t in body["tools"]}
            assert schemas["get_order_status"]["parameters"]["properties"]["order_id"]["type"] == "integer"
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "lookup-1001",
                        "type": "function",
                        "function": {"name": "get_order_status", "arguments": '{"order_id": 1001}'},
                    }
                ],
            }
        else:
            assert len(requests) == 3
            assistant, tool_result = body["messages"][-2:]
            assert assistant["tool_calls"][0]["id"] == "lookup-1001"
            assert tool_result["role"] == "tool"
            assert tool_result["tool_call_id"] == "lookup-1001"
            assert "delivered" in tool_result["content"]
            message = {"role": "assistant", "content": "Your order 1001 has been delivered."}
        return httpx.Response(
            200,
            json={
                "id": f"chat-{len(requests)}",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    original_client = llm.ChatOpenAI
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:

        def mock_client(**kwargs):
            return original_client(**kwargs, http_client=transport)

        monkeypatch.setattr(llm, "ChatOpenAI", mock_client)
        client.set_principal("alice")
        response = client.post("/chat", json={"message": "Where is order 1001?"})
        assert response.status_code == 200
        result = response.json()

    assert len(requests) == 3
    assert result["agent"] == "order"
    assert result["reply"] == "Your order 1001 has been delivered."
    # Redacted trace: tool name and agent only, no internal args/results.
    assert result["trace"] == [{"agent": "order", "tool": "get_order_status"}]
    assert result["usage"]["total_tokens"] == 45
    assert result["cached"] is False
