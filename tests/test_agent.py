"""Tests for src/agent.py"""
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import yaml
from model import Model
from agent import Agent


# ============================================================================
#  Helpers
# ============================================================================

def _write_yaml(path: str, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f)


@pytest.fixture
def test_model():
    """A basic Model instance for testing."""
    return Model(
        name="test-model",
        base_url="https://api.example.com",
        model_id="test-v1",
        api_key="sk-test",
    )


# ============================================================================
#  Agent.from_yaml
# ============================================================================

class TestAgentFromYaml:
    def test_loads_basic_agent(self, temp_dir, test_model):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "test-agent",
            "model": "test-model",
            "system_prompt": "You are helpful.",
            "tools": ["bash"],
        })
        registry = {"test-model": test_model}
        agent = Agent.from_yaml(yaml_path, model_registry=registry)
        assert agent.name == "test-agent"
        assert agent.model == test_model
        assert agent.system_prompt == "You are helpful."
        assert agent.tool_names == ["bash"]
        assert agent.max_turns == 1000  # default

    def test_model_by_file_path(self, temp_dir, test_model):
        """When model ref is a path to a YAML file, load it."""
        model_yaml = os.path.join(temp_dir, "model.yaml")
        _write_yaml(model_yaml, {
            "name": "loaded-model",
            "base_url": "https://api.example.com",
            "model_id": "v1",
        })
        agent_yaml = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(agent_yaml, {
            "name": "agent",
            "model": model_yaml,
            "system_prompt": "Be helpful.",
        })
        agent = Agent.from_yaml(agent_yaml, model_registry={})
        assert agent.model.name == "loaded-model"

    def test_model_not_in_registry_or_fs(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": "nonexistent-model",
            "system_prompt": "Hi",
        })
        with pytest.raises(ValueError, match="not found in registry"):
            Agent.from_yaml(yaml_path, model_registry={})

    def test_inline_model_definition(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {
                "name": "inline-model",
                "base_url": "https://api.inline.com",
                "model_id": "inline-v1",
            },
            "system_prompt": "Hi",
        })
        agent = Agent.from_yaml(yaml_path)
        assert agent.model.name == "inline-model"
        assert agent.model.base_url == "https://api.inline.com"

    def test_invalid_model_type(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": 42,  # invalid
            "system_prompt": "Hi",
        })
        with pytest.raises(ValueError, match="Invalid 'model'"):
            Agent.from_yaml(yaml_path)

    def test_system_prompt_from_file(self, temp_dir):
        prompt_file = os.path.join(temp_dir, "prompt.txt")
        with open(prompt_file, "w") as f:
            f.write("Loaded from file!")

        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {
                "name": "m", "base_url": "https://x.com", "model_id": "x",
            },
            "system_prompt_file": "prompt.txt",
        })
        agent = Agent.from_yaml(yaml_path)
        assert agent.system_prompt == "Loaded from file!"

    def test_system_prompt_overrides_file(self, temp_dir):
        prompt_file = os.path.join(temp_dir, "prompt.txt")
        with open(prompt_file, "w") as f:
            f.write("File prompt")

        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {
                "name": "m", "base_url": "https://x.com", "model_id": "x",
            },
            "system_prompt": "Literal prompt",
            "system_prompt_file": "prompt.txt",
        })
        agent = Agent.from_yaml(yaml_path)
        assert agent.system_prompt == "Literal prompt"

    def test_system_prompt_file_not_found(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {
                "name": "m", "base_url": "https://x.com", "model_id": "x",
            },
            "system_prompt_file": "nonexistent.txt",
        })
        with pytest.raises(ValueError, match="not found"):
            Agent.from_yaml(yaml_path)

    def test_missing_name(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "model": {"name": "m", "base_url": "https://x.com", "model_id": "x"},
        })
        with pytest.raises(ValueError, match="name"):
            Agent.from_yaml(yaml_path)

    def test_missing_model(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
        })
        with pytest.raises(ValueError, match="model"):
            Agent.from_yaml(yaml_path)

    def test_not_a_dict(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, ["not", "a", "dict"])
        with pytest.raises(ValueError, match="dict"):
            Agent.from_yaml(yaml_path)

    def test_cwd_template_substitution(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {"name": "m", "base_url": "https://x.com", "model_id": "x"},
            "system_prompt": "Working dir: {cwd}",
            "cwd": "/custom/cwd",
        })
        agent = Agent.from_yaml(yaml_path)
        assert f"Working dir: {agent._cwd}" in agent.system_prompt

    def test_default_cwd(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {"name": "m", "base_url": "https://x.com", "model_id": "x"},
            "system_prompt": "CWD: {cwd}",
        })
        agent = Agent.from_yaml(yaml_path)
        assert os.getcwd() in agent.system_prompt

    def test_custom_max_turns(self, temp_dir):
        yaml_path = os.path.join(temp_dir, "agent.yaml")
        _write_yaml(yaml_path, {
            "name": "agent",
            "model": {"name": "m", "base_url": "https://x.com", "model_id": "x"},
            "system_prompt": "Hi",
            "max_turns": 42,
        })
        agent = Agent.from_yaml(yaml_path)
        assert agent.max_turns == 42


# ============================================================================
#  Agent._get_tool_schemas
# ============================================================================

class TestGetToolSchemas:
    def test_returns_schemas(self, test_model):
        agent = Agent(
            name="test",
            model=test_model,
            tool_names=["bash", "read_file"],
        )
        schemas = agent._get_tool_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "bash" in names
        assert "read_file" in names

    def test_no_tools(self, test_model):
        agent = Agent(name="test", model=test_model)
        assert agent._get_tool_schemas() == []

    def test_unrecognized_tool_ignored(self, test_model):
        agent = Agent(
            name="test",
            model=test_model,
            tool_names=["bash", "ghost_tool"],
        )
        schemas = agent._get_tool_schemas()
        assert len(schemas) == 1


# ============================================================================
#  Agent.agent_turn
# ============================================================================

class TestAgentTurn:
    @pytest.fixture
    def agent(self, test_model):
        return Agent(
            name="test-agent",
            model=test_model,
            system_prompt="You are a test agent.",
            tool_names=["bash"],
        )

    def test_simple_text_response(self, agent):
        """When the model returns content and no tool calls, the loop ends.
        The final non-tool-call response is printed but NOT appended to messages."""
        with patch.object(agent.model, "chat", return_value=("Hello user!", [])):
            messages = []
            result = agent.agent_turn(messages, "Hi")

            # The user message should be appended
            assert result[0]["role"] == "user"
            assert result[0]["content"] == "Hi"
            # Only the user message is in the returned list
            # (final assistant response without tool_calls is not appended)
            assert len(result) == 1

    def test_with_tool_call(self, agent):
        """When the model returns a tool call, it should be executed.
        The final text-only response is printed but not appended to messages."""
        tool_call = {
            "id": "tc1",
            "function": {"name": "bash", "arguments": '{"command":"echo hello"}'},
        }
        with patch.object(agent.model, "chat") as mock_chat:
            mock_chat.side_effect = [
                ("", [tool_call]),           # turn 1: tool call
                ("Done!", []),               # turn 2: final response (no tool calls)
            ]

            with patch("tools._check_bash_permission", return_value=True):
                messages = []
                result = agent.agent_turn(messages, "Run command")

            assert mock_chat.call_count == 2

            # messages should contain: user, assistant (with tool_calls), tool
            # The final "Done!" response (no tool_calls) is printed but NOT appended
            roles = [m["role"] for m in result]
            assert roles == ["user", "assistant", "tool"]

    def test_max_turns_limit(self, agent):
        """After max_turns, stop even if model keeps returning tool calls."""
        agent.max_turns = 3
        tool_call = {
            "id": "tc1",
            "function": {"name": "bash", "arguments": '{"command":"echo x"}'},
        }
        # Always return a tool call — should stop after 3 turns
        with patch.object(agent.model, "chat", return_value=("", [tool_call])), \
             patch("tools._check_bash_permission", return_value=True):
            messages = []
            result = agent.agent_turn(messages, "Go")

            # user + 3*(assistant + tool) = 1 + 6 = 7 messages
            assert len(result) == 7

    def test_no_content_no_tool_calls(self, agent, capsys):
        """When model returns nothing, still print a message."""
        with patch.object(agent.model, "chat", return_value=("", [])):
            messages = []
            agent.agent_turn(messages, "Hi")
        captured = capsys.readouterr()
        assert "(no text output)" in captured.out


# ============================================================================
#  Agent.chat_loop
# ============================================================================

class TestChatLoop:
    @pytest.fixture
    def agent(self, test_model):
        return Agent(
            name="chat-agent",
            model=test_model,
            system_prompt="Be helpful.",
        )

    def test_exit_on_quit(self, agent):
        """Typing 'quit' should exit the loop."""
        with patch("builtins.input", side_effect=["quit"]), \
             patch.object(agent.model, "chat") as mock_chat:
            agent.chat_loop()
            mock_chat.assert_not_called()

    def test_exit_on_exit(self, agent):
        with patch("builtins.input", side_effect=["exit"]), \
             patch.object(agent.model, "chat") as mock_chat:
            agent.chat_loop()
            mock_chat.assert_not_called()

    def test_exit_on_eof(self, agent):
        """EOFError triggers sys.exit(0). We don't patch sys.exit so it
        raises SystemExit which we catch."""
        with patch("builtins.input", side_effect=EOFError), \
             patch.object(agent.model, "chat") as mock_chat:
            with pytest.raises(SystemExit) as exc_info:
                agent.chat_loop()
            assert exc_info.value.code == 0
            mock_chat.assert_not_called()

    def test_exit_on_keyboard_interrupt(self, agent):
        """KeyboardInterrupt triggers sys.exit(0)."""
        with patch("builtins.input", side_effect=KeyboardInterrupt), \
             patch.object(agent.model, "chat") as mock_chat:
            with pytest.raises(SystemExit) as exc_info:
                agent.chat_loop()
            assert exc_info.value.code == 0
            mock_chat.assert_not_called()

    def test_empty_input_is_skipped(self, agent):
        """Empty inputs should be ignored."""
        with patch("builtins.input", side_effect=["", "  ", "exit"]), \
             patch.object(agent.model, "chat") as mock_chat:
            agent.chat_loop()
            mock_chat.assert_not_called()

    def test_processes_one_message(self, agent):
        """A single message should be processed."""
        with patch("builtins.input", side_effect=["Hello", "quit"]), \
             patch.object(agent.model, "chat", return_value=("Hi there!", [])):
            agent.chat_loop()

    def test_system_prompt_appended(self, agent, test_model):
        """The system prompt should be the first message."""
        agent2 = Agent(
            name="chat-agent",
            model=test_model,
            system_prompt="You are a bot.",
        )
        with patch("builtins.input", side_effect=["Hello", "quit"]), \
             patch.object(agent2.model, "chat", return_value=("Hi!", [])) as mock_chat:
            agent2.chat_loop()
            # The messages list passed to chat should start with the system prompt
            call_args = mock_chat.call_args[0][0]
            assert call_args[0]["role"] == "system"
            assert call_args[0]["content"] == "You are a bot."

    def test_no_system_prompt(self, agent, test_model):
        """When no system prompt, messages should start empty."""
        agent2 = Agent(
            name="chat-agent",
            model=test_model,
        )
        with patch("builtins.input", side_effect=["Hello", "quit"]), \
             patch.object(agent2.model, "chat", return_value=("Hi!", [])) as mock_chat:
            agent2.chat_loop()
            call_args = mock_chat.call_args[0][0]
            assert call_args[0]["role"] == "user"
