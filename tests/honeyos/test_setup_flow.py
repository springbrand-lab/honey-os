from __future__ import annotations

import json
import urllib.request

import yaml

from honeyos.cli.bootstrap import activate_home
from honeyos.companion.config import initialize_home
from honeyos.companion.setup import ModelChoice, configure_model, run_setup, validate_model_key


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_configure_model_keeps_key_out_of_yaml(tmp_path):
    initialize_home(tmp_path)
    choice = ModelChoice(
        provider="openrouter",
        model="z-ai/glm-5.2",
        base_url="https://openrouter.ai/api/v1",
        key_env="OPENROUTER_API_KEY",
    )

    configure_model(tmp_path, choice, "secret-value")

    config_text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    config = yaml.safe_load(config_text)
    assert config["model"] == {
        "default": "z-ai/glm-5.2",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_mode": "chat_completions",
    }
    assert "secret-value" not in config_text
    assert "OPENROUTER_API_KEY=secret-value" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")


def test_custom_model_uses_named_provider_key_env_at_runtime(monkeypatch, tmp_path):
    initialize_home(tmp_path)
    activate_home(tmp_path)
    choice = ModelChoice(
        provider="custom",
        model="deepseek-v4-flash",
        base_url="https://api.example.com/v1",
        key_env="HONEYOS_MODEL_API_KEY",
    )
    configure_model(tmp_path, choice, "secret-value")
    monkeypatch.setenv("HONEYOS_MODEL_API_KEY", "secret-value")

    from honeyos.runtime.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(requested="honeyos-model")

    assert runtime["provider"] == "custom"
    assert runtime["base_url"] == "https://api.example.com/v1"
    assert runtime["api_key"] == "secret-value"
    assert runtime["model"] == "deepseek-v4-flash"


def test_model_validation_uses_real_non_streaming_chat_completion(monkeypatch):
    observed = {}

    def open_request(request, timeout):
        observed["request"] = request
        observed["timeout"] = timeout
        return _Response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_probe",
                                    "type": "function",
                                    "function": {
                                        "name": "honeyos_compatibility_probe",
                                        "arguments": '{"value":"honeyos"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", open_request)
    choice = ModelChoice(
        provider="custom",
        model="test-model",
        base_url="https://api.example.com/v1",
        key_env="HONEYOS_MODEL_API_KEY",
    )

    validate_model_key(choice, "valid-key")

    request = observed["request"]
    body = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "https://api.example.com/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer valid-key"
    assert body["model"] == "test-model"
    assert body["stream"] is False
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "honeyos_compatibility_probe",
                "description": "Verify that this model can call HoneyOS tools.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    assert "call the honeyos_compatibility_probe tool" in body["messages"][0]["content"]


def test_model_validation_rejects_chat_only_model_without_tool_calls(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I would call honeyos_compatibility_probe.",
                        }
                    }
                ]
            }
        ),
    )
    choice = ModelChoice(
        provider="custom",
        model="deepseek-r1",
        base_url="https://api.example.com/v1",
        key_env="HONEYOS_MODEL_API_KEY",
    )

    try:
        validate_model_key(choice, "valid-key")
    except ValueError as exc:
        assert "工具调用" in str(exc)
        assert "Function Calling" in str(exc)
    else:
        raise AssertionError("chat-only model was accepted as an Agent model")


def test_model_validation_rejects_string_instead_of_openai_response(monkeypatch):
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response("data: not-an-openai-response"),
    )
    choice = ModelChoice(
        provider="custom",
        model="test-model",
        base_url="https://api.example.com/v1",
        key_env="HONEYOS_MODEL_API_KEY",
    )

    try:
        validate_model_key(choice, "valid-key")
    except ValueError as exc:
        assert "OpenAI Chat Completions" in str(exc)
    else:
        raise AssertionError("invalid provider response was accepted")


def test_setup_defaults_to_weixin_and_feishu_before_start(tmp_path):
    initialize_home(tmp_path)
    events = []
    answers = iter(["", "https://api.example.com/v1", "test-model", ""])

    result = run_setup(
        tmp_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "valid-key",
        validate_fn=lambda choice, key: events.append(
            ("validate", choice.provider, key)
        ),
        weixin_setup_fn=lambda home: events.append(("weixin", home)) or 0,
        feishu_setup_fn=lambda home: events.append(("feishu", home)) or 0,
        gateway_run_fn=lambda command, *, home, arguments=(): events.append(
            ("gateway", command, tuple(arguments), home)
        )
        or 0,
        ready_check_fn=lambda home: events.append(("ready", home)) or True,
    )

    assert result == 0
    assert events == [
        ("validate", "custom", "valid-key"),
        ("weixin", tmp_path.resolve()),
        ("feishu", tmp_path.resolve()),
        ("gateway", "install", ("--no-start-now",), tmp_path.resolve()),
        ("gateway", "start", (), tmp_path.resolve()),
        ("ready", tmp_path.resolve()),
    ]


def test_setup_stops_before_weixin_when_key_validation_fails(tmp_path, capsys):
    initialize_home(tmp_path)
    events = []
    answers = iter(["", "https://api.example.com/v1", "test-model"])

    result = run_setup(
        tmp_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "bad-key",
        validate_fn=lambda _choice, _key: (_ for _ in ()).throw(
            ValueError("API Key 无效")
        ),
        weixin_setup_fn=lambda home: events.append(home) or 0,
        feishu_setup_fn=lambda home: events.append(home) or 0,
        gateway_run_fn=lambda command, *, home, arguments=(): 0,
        ready_check_fn=lambda _home: True,
    )

    assert result == 1
    assert events == []
    assert "API Key 无效" in capsys.readouterr().err


def test_setup_can_select_feishu_only(tmp_path):
    initialize_home(tmp_path)
    events = []
    answers = iter(["", "https://api.example.com/v1", "test-model", "2"])

    result = run_setup(
        tmp_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "valid-key",
        validate_fn=lambda _choice, _key: None,
        weixin_setup_fn=lambda home: events.append(("weixin", home)) or 0,
        feishu_setup_fn=lambda home: events.append(("feishu", home)) or 0,
        gateway_run_fn=lambda _command, *, home, arguments=(): 0,
        ready_check_fn=lambda _home: True,
    )

    assert result == 0
    assert events == [("feishu", tmp_path.resolve())]


def test_setup_can_start_with_local_web_only(tmp_path):
    initialize_home(tmp_path)
    events = []
    answers = iter(["", "https://api.example.com/v1", "test-model", "4"])

    result = run_setup(
        tmp_path,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "valid-key",
        validate_fn=lambda _choice, _key: None,
        weixin_setup_fn=lambda home: events.append(("weixin", home)) or 0,
        feishu_setup_fn=lambda home: events.append(("feishu", home)) or 0,
        gateway_run_fn=lambda command, *, home, arguments=(): events.append(
            ("gateway", command, tuple(arguments), home)
        )
        or 0,
        ready_check_fn=lambda home: events.append(("ready", home)) or True,
    )

    assert result == 0
    assert events == [
        ("gateway", "install", ("--no-start-now",), tmp_path.resolve()),
        ("gateway", "start", (), tmp_path.resolve()),
        ("ready", tmp_path.resolve()),
    ]
