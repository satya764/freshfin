import freshfin.llm as llm


def test_openai_session_tool_round_trip(monkeypatch):
    sent = []

    def fake_post(url, body, headers, timeout, retries=4):
        sent.append(body)
        if len(sent) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {
                                        "name": "get_reported_values",
                                        "arguments": '{"ticker": "MSFT", "metric": "revenue"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
            }
        return {"choices": [{"message": {"content": '{"value": 1}'}}], "usage": {}}

    monkeypatch.setattr(llm, "post_json", fake_post)
    tool = {"name": "get_reported_values", "description": "d", "input_schema": {"type": "object"}}
    session = llm.OpenAICompatibleClient("http://x/v1").start("qwen3-16k", "sys", "q", [tool])
    reply = session.step()
    assert reply.tool_calls[0].args == {"ticker": "MSFT", "metric": "revenue"}
    assert reply.input_tokens == 50
    session.add_tool_results([("c1", '{"values": []}')])
    assert session.step().text == '{"value": 1}'
    assert sent[0]["messages"][0]["content"].endswith("/no_think")
    assert sent[0]["tools"][0]["function"]["name"] == "get_reported_values"
    assert sent[1]["messages"][-2] == {"role": "tool", "tool_call_id": "c1", "content": '{"values": []}'}


def test_anthropic_session_keeps_blocks_and_ignores_thinking(monkeypatch):
    sent = []

    def fake_post(url, body, headers, timeout, retries=4):
        sent.append(body)
        return {
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "s"},
                {"type": "text", "text": "Checking."},
                {"type": "tool_use", "id": "t1", "name": "get_reported_values", "input": {"ticker": "A"}},
            ],
            "usage": {"input_tokens": 7, "output_tokens": 3},
        }

    monkeypatch.setattr(llm, "post_json", fake_post)
    session = llm.AnthropicClient("key").start("claude-haiku-5-5", "sys", "q", None)
    reply = session.step()
    assert reply.text == "Checking." and reply.tool_calls[0].id == "t1"
    session.add_tool_results([("t1", "{}")])
    assert session.messages[1]["content"][0]["type"] == "thinking"  # passed back unchanged
    assert session.messages[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "{}"}
    assert "tools" not in sent[0]


def test_anthropic_needs_key():
    import pytest

    with pytest.raises(ValueError):
        llm.AnthropicClient("")
