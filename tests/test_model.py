"""Tests for src/model.py"""
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import yaml
from model import Model


# ============================================================================
#  Helpers
# ============================================================================

def _write_yaml(path: str, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f)


# ============================================================================
#  Model.from_yaml
# ============================================================================

class TestModelFromYaml:
    def test_loads_basic_model(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test-model",
            "base_url": "https://api.example.com",
            "model_id": "test-v1",
        })
        model = Model.from_yaml(yaml_path)
        assert model.name == "test-model"
        assert model.base_url == "https://api.example.com"
        assert model.model_id == "test-v1"
        assert model.temperature == 0.1  # default
        assert model.max_tokens == 4096  # default

    def test_loads_with_custom_params(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "custom",
            "base_url": "https://api.custom.com",
            "model_id": "custom-v2",
            "temperature": 0.7,
            "max_tokens": 2048,
        })
        model = Model.from_yaml(yaml_path)
        assert model.temperature == 0.7
        assert model.max_tokens == 2048

    def test_missing_required_keys(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "incomplete",
            # missing base_url and model_id
        })
        with pytest.raises(ValueError, match="base_url"):
            Model.from_yaml(yaml_path)

        _write_yaml(yaml_path, {
            "name": "incomplete",
            "base_url": "https://x.com",
        })
        with pytest.raises(ValueError, match="model_id"):
            Model.from_yaml(yaml_path)

    def test_not_a_dict(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, ["not", "a", "dict"])
        with pytest.raises(ValueError, match="dict"):
            Model.from_yaml(yaml_path)

    def test_api_key_from_literal(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "api_key": "sk-literal-key",
        })
        model = Model.from_yaml(yaml_path)
        assert model.api_key == "sk-literal-key"

    def test_api_key_from_env(self, temp_dir, monkeypatch):
        monkeypatch.setenv("MY_API_KEY", "sk-from-env")
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "api_key_env": "MY_API_KEY",
        })
        model = Model.from_yaml(yaml_path)
        assert model.api_key == "sk-from-env"

    def test_api_key_env_not_set(self, temp_dir, monkeypatch):
        """When api_key_env is specified but not set, warn but don't crash."""
        monkeypatch.delenv("NONEXISTENT_KEY", raising=False)
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "api_key_env": "NONEXISTENT_KEY",
        })
        model = Model.from_yaml(yaml_path)
        assert model.api_key == ""

    def test_literal_key_takes_precedence_over_env(self, temp_dir, monkeypatch):
        monkeypatch.setenv("MY_KEY", "env-value")
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "api_key": "literal-value",
            "api_key_env": "MY_KEY",
        })
        model = Model.from_yaml(yaml_path)
        # Literal is set directly, env is only used if api_key is empty
        assert model.api_key == "literal-value"

    def test_custom_headers(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "headers": {
                "X-Custom": "value",
            },
        })
        model = Model.from_yaml(yaml_path)
        assert model.extra_headers["X-Custom"] == "value"
        # Content-Type should be auto-added
        assert model.extra_headers["Content-Type"] == "application/json"

    def test_content_type_preserved(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "headers": {
                "Content-Type": "text/plain",
            },
        })
        model = Model.from_yaml(yaml_path)
        assert model.extra_headers["Content-Type"] == "text/plain"

    def test_invalid_headers_type(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com",
            "model_id": "v1",
            "headers": "not-a-dict",
        })
        with pytest.raises(ValueError, match="headers"):
            Model.from_yaml(yaml_path)

    def test_base_url_trailing_slash_stripped(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "model.yaml")
        _write_yaml(yaml_path, {
            "name": "test",
            "base_url": "https://api.example.com/",
            "model_id": "v1",
        })
        model = Model.from_yaml(yaml_path)
        assert model.base_url == "https://api.example.com"


# ============================================================================
#  Model.chat
# ============================================================================

class TestModelChat:
    @pytest.fixture
    def model(self):
        return Model(
            name="test",
            base_url="https://api.example.com",
            model_id="test-v1",
            api_key="sk-test",
            extra_headers={"Content-Type": "application/json"},
        )

    def test_sends_correct_payload(self, model):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!", "tool_calls": None}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_response) as mock_post:
            content, tool_calls = model.chat([
                {"role": "user", "content": "Hi"}
            ])

            mock_post.assert_called_once()
            payload = mock_post.call_args[1]["json"]
            assert payload["model"] == "test-v1"
            assert payload["temperature"] == 0.1
            assert payload["max_tokens"] == 4096
            assert "tools" not in payload  # no tools passed

        assert content == "Hello!"
        assert tool_calls == []

    def test_includes_tools_when_provided(self, model):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": None, "tool_calls": None}}]
        }
        fake_response.raise_for_status = MagicMock()

        tool_schemas = [{"type": "function", "function": {"name": "bash"}}]
        with patch("requests.post", return_value=fake_response) as mock_post:
            model.chat([{"role": "user", "content": "Hi"}], tools=tool_schemas)

            payload = mock_post.call_args[1]["json"]
            assert payload["tools"] == tool_schemas
            assert payload["tool_choice"] == "auto"

    def test_custom_tool_choice(self, model):
        """tool_choice is only sent when tools list is non-empty (truthy)."""
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": None, "tool_calls": None}}]
        }
        fake_response.raise_for_status = MagicMock()

        tool_schemas = [{"type": "function", "function": {"name": "bash"}}]
        with patch("requests.post", return_value=fake_response) as mock_post:
            model.chat(
                [{"role": "user", "content": "Hi"}],
                tools=tool_schemas,
                tool_choice="required",
            )
            payload = mock_post.call_args[1]["json"]
            assert payload["tool_choice"] == "required"

    def test_returns_tool_calls(self, model):
        tool_calls = [{"id": "tc1", "function": {"name": "bash", "arguments": '{"cmd":"ls"}'}}]
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "Let me run that...", "tool_calls": tool_calls}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_response):
            content, tc = model.chat([{"role": "user", "content": "List files"}])

        assert content == "Let me run that..."
        assert tc == tool_calls

    def test_empty_content_becomes_empty_string(self, model):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": None, "tool_calls": None}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_response):
            content, _ = model.chat([{"role": "user", "content": "Hi"}])

        assert content == ""

    def test_no_api_key_raises(self):
        model = Model(
            name="test",
            base_url="https://api.example.com",
            model_id="test-v1",
            api_key="",  # no key
        )
        with pytest.raises(RuntimeError, match="API key"):
            model.chat([{"role": "user", "content": "Hi"}])

    def test_http_error_propagates(self, model):
        import requests as req_lib
        fake_response = MagicMock()
        fake_response.raise_for_status.side_effect = req_lib.HTTPError("Unauthorized")

        with patch("requests.post", return_value=fake_response):
            with pytest.raises(req_lib.HTTPError, match="Unauthorized"):
                model.chat([{"role": "user", "content": "Hi"}])

    def test_authorization_header_set(self, model):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "ok", "tool_calls": None}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_response) as mock_post:
            model.chat([{"role": "user", "content": "Hi"}])

            headers = mock_post.call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer sk-test"
            assert headers["Content-Type"] == "application/json"

    def test_url_endpoint(self, model):
        fake_response = MagicMock()
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "ok", "tool_calls": None}}]
        }
        fake_response.raise_for_status = MagicMock()

        with patch("requests.post", return_value=fake_response) as mock_post:
            model.chat([{"role": "user", "content": "Hi"}])

            url = mock_post.call_args[0][0]
            assert url == "https://api.example.com/chat/completions"
