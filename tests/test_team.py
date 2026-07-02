"""Tests for src/team.py"""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import yaml
from model import Model
from agent import Agent
from team import Team


# ============================================================================
#  Helpers
# ============================================================================

def _write_yaml(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f)


def _make_test_model(name="test-model"):
    """A basic Model instance for testing."""
    return Model(
        name=name,
        base_url="https://api.example.com",
        model_id="test-v1",
        api_key="sk-test",
    )


def _make_test_agent(name="test-agent", model=None, system_prompt="You are helpful.", tool_names=None):
    """Create a basic Agent for testing."""
    if model is None:
        model = _make_test_model()
    return Agent(
        name=name,
        model=model,
        system_prompt=system_prompt,
        tool_names=tool_names or [],
    )


def _setup_team_structure(temp_dir, host_config=None, member_configs=None, models=None, team_config=None):
    """Create the directory structure expected by Team.from_yaml.

    Creates configs/ with team.yaml, agents/*.yaml, models/*.yaml.
    Returns the path to team.yaml.
    """
    # team.yaml must be in configs/ so project_root = temp_dir
    configs_dir = os.path.join(temp_dir, "configs")
    agents_dir = os.path.join(configs_dir, "agents")
    models_dir = os.path.join(configs_dir, "models")
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)

    # Write host agent config
    if host_config is None:
        host_config = {
            "name": "host-agent",
            "model": {
                "name": "host-model",
                "base_url": "https://api.host.com",
                "model_id": "host-v1",
                "api_key": "sk-host",
            },
            "system_prompt": "You are a host agent.",
        }
    _write_yaml(os.path.join(agents_dir, "host.yaml"), host_config)

    # Write member agent configs
    if member_configs is None:
        member_configs = [
            {
                "filename": "member1.yaml",
                "config": {
                    "name": "member1",
                    "model": {
                        "name": "member1-model",
                        "base_url": "https://api.m1.com",
                        "model_id": "m1-v1",
                        "api_key": "sk-m1",
                    },
                    "system_prompt": "You are member 1.",
                },
            },
        ]
    for mc in member_configs:
        _write_yaml(os.path.join(agents_dir, mc["filename"]), mc["config"])

    # Write model configs in configs/models/
    if models:
        for model_name, model_data in models.items():
            _write_yaml(os.path.join(models_dir, f"{model_name}.yaml"), model_data)

    # Write team.yaml
    if team_config is None:
        team_config = {
            "name": "test-team",
            "host": {"agent": "configs/agents/host.yaml"},
            "agents": [
                {
                    "name": "member1",
                    "agent": "configs/agents/member1.yaml",
                    "description": "Handles member1 tasks.",
                },
            ],
        }
    team_yaml_path = os.path.join(configs_dir, "team.yaml")
    _write_yaml(team_yaml_path, team_config)
    return team_yaml_path


# ============================================================================
#  Team.from_yaml
# ============================================================================

class TestTeamFromYaml:
    def test_loads_basic_team(self, temp_dir):
        """Loads a basic team config with host + one member agent."""
        team_yaml = _setup_team_structure(temp_dir)
        team = Team.from_yaml(team_yaml)

        assert team.name == "test-team"
        assert team.host_agent.name == "host-agent"
        assert "member1" in team.member_agents
        assert team.member_agents["member1"].name == "member1"

    def test_host_agent_is_loaded_correctly(self, temp_dir):
        """Host agent has correct properties from its YAML config."""
        host_config = {
            "name": "my-host",
            "model": {
                "name": "my-model",
                "base_url": "https://api.my.com",
                "model_id": "my-v1",
                "api_key": "sk-my",
            },
            "system_prompt": "I am the host.",
            "tools": ["bash"],
        }
        team_yaml = _setup_team_structure(temp_dir, host_config=host_config)
        team = Team.from_yaml(team_yaml)

        assert team.host_agent.name == "my-host"
        assert team.host_agent.system_prompt.startswith("I am the host.")
        assert team.host_agent.tool_names == ["bash"]
        assert team.host_agent.model.name == "my-model"

    def test_member_agents_are_loaded_correctly(self, temp_dir):
        """Member agents have correct properties from their YAML configs."""
        member_configs = [
            {
                "filename": "coder.yaml",
                "config": {
                    "name": "coder-agent",
                    "model": {
                        "name": "coder-model",
                        "base_url": "https://api.code.com",
                        "model_id": "code-v1",
                        "api_key": "sk-code",
                    },
                    "system_prompt": "You write code.",
                    "tools": ["bash", "read_file"],
                },
            },
        ]
        team_yaml = _setup_team_structure(
            temp_dir,
            member_configs=member_configs,
            team_config={
                "name": "dev-team",
                "host": {"agent": "configs/agents/host.yaml"},
                "agents": [
                    {
                        "name": "coder",
                        "agent": "configs/agents/coder.yaml",
                        "description": "Writes and reviews code.",
                    },
                ],
            },
        )
        team = Team.from_yaml(team_yaml)

        assert "coder" in team.member_agents
        coder = team.member_agents["coder"]
        assert coder.name == "coder-agent"
        assert coder.system_prompt == "You write code."
        assert coder.tool_names == ["bash", "read_file"]
        assert coder.model.name == "coder-model"

    def test_member_descriptions_injected_into_host_system_prompt(self, temp_dir):
        """Member descriptions appear in the host agent's system prompt."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "desc-team",
                "host": {"agent": "configs/agents/host.yaml"},
                "agents": [
                    {
                        "name": "coder",
                        "agent": "configs/agents/member1.yaml",
                        "description": "Expert coder who writes Python.",
                    },
                    {
                        "name": "reviewer",
                        "agent": "configs/agents/member1.yaml",
                        "description": "Reviews code for quality.",
                    },
                ],
            },
        )
        team = Team.from_yaml(team_yaml)

        prompt = team.host_agent.system_prompt
        assert "## Available team members" in prompt
        assert "### coder" in prompt
        assert "Expert coder who writes Python." in prompt
        assert "### reviewer" in prompt
        assert "Reviews code for quality." in prompt

    def test_works_with_no_member_agents_empty_list(self, temp_dir):
        """Team with agents: [] (empty list) works fine."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "solo-team",
                "host": {"agent": "configs/agents/host.yaml"},
                "agents": [],
            },
        )
        team = Team.from_yaml(team_yaml)

        assert team.name == "solo-team"
        assert team.host_agent is not None
        assert team.member_agents == {}

    def test_works_with_no_agents_key(self, temp_dir):
        """Team without 'agents' key at all works fine."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "host-only-team",
                "host": {"agent": "configs/agents/host.yaml"},
            },
        )
        team = Team.from_yaml(team_yaml)

        assert team.name == "host-only-team"
        assert team.member_agents == {}

    def test_missing_name_raises(self, temp_dir):
        """Raises ValueError when 'name' key is missing."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "host": {"agent": "configs/agents/host.yaml"},
            },
        )
        with pytest.raises(ValueError, match="name"):
            Team.from_yaml(team_yaml)

    def test_missing_host_key_raises(self, temp_dir):
        """Raises ValueError when 'host' key is missing."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "no-host-team",
            },
        )
        with pytest.raises(ValueError, match="host.agent"):
            Team.from_yaml(team_yaml)

    def test_missing_host_agent_key_raises(self, temp_dir):
        """Raises ValueError when 'host.agent' key is missing."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "bad-host-team",
                "host": {"not_agent": "oops"},
            },
        )
        with pytest.raises(ValueError, match="host.agent"):
            Team.from_yaml(team_yaml)

    def test_not_a_dict_raises(self, temp_dir):
        """Raises ValueError when YAML is not a dict."""
        configs_dir = os.path.join(temp_dir, "configs")
        os.makedirs(configs_dir, exist_ok=True)
        team_yaml = os.path.join(configs_dir, "team.yaml")
        _write_yaml(team_yaml, ["not", "a", "dict"])
        with pytest.raises(ValueError, match="dict"):
            Team.from_yaml(team_yaml)

    def test_missing_member_agent_config_file_raises(self, temp_dir):
        """Raises ValueError when a member agent config file doesn't exist."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "bad-ref-team",
                "host": {"agent": "configs/agents/host.yaml"},
                "agents": [
                    {
                        "name": "ghost",
                        "agent": "configs/agents/nonexistent.yaml",
                        "description": "Does not exist.",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="not found"):
            Team.from_yaml(team_yaml)

    def test_duplicate_member_names_raises(self, temp_dir):
        """Raises ValueError when two member agents share the same name."""
        team_yaml = _setup_team_structure(
            temp_dir,
            team_config={
                "name": "dup-team",
                "host": {"agent": "configs/agents/host.yaml"},
                "agents": [
                    {
                        "name": "coder",
                        "agent": "configs/agents/member1.yaml",
                        "description": "First coder.",
                    },
                    {
                        "name": "coder",
                        "agent": "configs/agents/member1.yaml",
                        "description": "Second coder.",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Duplicate agent name"):
            Team.from_yaml(team_yaml)

    def test_auto_loads_model_configs_from_models_dir(self, temp_dir):
        """Model configs in configs/models/ are auto-loaded into the registry."""
        models = {
            "deepseek": {
                "name": "deepseek-v4-pro",
                "base_url": "https://api.deepseek.com",
                "model_id": "deepseek-v4-pro",
                "api_key": "sk-ds",
            },
        }
        host_config = {
            "name": "host-agent",
            "model": "deepseek-v4-pro",  # reference by name from model registry
            "system_prompt": "Host uses registry model.",
        }
        team_yaml = _setup_team_structure(
            temp_dir,
            host_config=host_config,
            models=models,
        )
        team = Team.from_yaml(team_yaml)

        # The host agent should have loaded the model from the registry by name
        assert team.host_agent.model.name == "deepseek-v4-pro"
        assert team.host_agent.model.base_url == "https://api.deepseek.com"

    def test_broken_model_config_skipped_gracefully(self, temp_dir):
        """A broken model YAML file is silently skipped, others still loaded."""
        configs_dir = os.path.join(temp_dir, "configs")
        models_dir = os.path.join(configs_dir, "models")
        os.makedirs(models_dir, exist_ok=True)

        # Write a broken model config (missing required keys)
        _write_yaml(os.path.join(models_dir, "broken.yaml"), {
            "name": "broken-model",
            # missing base_url and model_id
        })
        # Write a valid model config
        _write_yaml(os.path.join(models_dir, "good.yaml"), {
            "name": "good-model",
            "base_url": "https://api.good.com",
            "model_id": "good-v1",
            "api_key": "sk-good",
        })

        host_config = {
            "name": "host-agent",
            "model": "good-model",  # reference by name
            "system_prompt": "Host.",
        }
        team_yaml = _setup_team_structure(
            temp_dir,
            host_config=host_config,
            models={},  # don't use the helper's model writing
        )
        # Overwrite with our custom models
        # (the helper already wrote host.yaml and member configs, we just need
        # to ensure our good model is there — but we already wrote it above)

        team = Team.from_yaml(team_yaml)
        # Should not crash; should load the good model
        assert team.host_agent.model.name == "good-model"

    def test_paths_resolve_relative_to_project_root(self, temp_dir):
        """Relative paths in team YAML are resolved relative to project_root,
        which is the parent of the configs/ directory containing team.yaml."""
        # Create a deeply nested structure to verify resolution
        project_root = temp_dir
        configs_dir = os.path.join(project_root, "configs")
        agents_dir = os.path.join(configs_dir, "agents")
        os.makedirs(agents_dir, exist_ok=True)

        # Host agent at configs/agents/host.yaml (relative to project_root)
        _write_yaml(os.path.join(agents_dir, "host.yaml"), {
            "name": "nested-host",
            "model": {
                "name": "m", "base_url": "https://x.com", "model_id": "x",
            },
            "system_prompt": "Host.",
        })

        # Member at a custom path relative to project_root
        custom_agent_dir = os.path.join(project_root, "custom", "agents")
        os.makedirs(custom_agent_dir, exist_ok=True)
        _write_yaml(os.path.join(custom_agent_dir, "special.yaml"), {
            "name": "special-agent",
            "model": {
                "name": "m2", "base_url": "https://y.com", "model_id": "y",
            },
            "system_prompt": "Special.",
        })

        team_yaml_path = os.path.join(configs_dir, "team.yaml")
        _write_yaml(team_yaml_path, {
            "name": "path-test-team",
            "host": {"agent": "configs/agents/host.yaml"},
            "agents": [
                {
                    "name": "special",
                    "agent": "custom/agents/special.yaml",
                    "description": "Custom path agent.",
                },
            ],
        })

        team = Team.from_yaml(team_yaml_path)
        assert team.host_agent.name == "nested-host"
        assert "special" in team.member_agents
        assert team.member_agents["special"].name == "special-agent"


# ============================================================================
#  Delegation tool schema
# ============================================================================

class TestDelegationToolSchema:
    @pytest.fixture
    def team(self):
        """A minimal Team for schema tests."""
        host = _make_test_agent(name="host")
        member = _make_test_agent(name="member")
        return Team(
            name="schema-team",
            host_agent=host,
            member_agents={"coder": member},
        )

    def test_schema_has_correct_name_format(self, team):
        """The schema function name should be delegate_to_{agent_name}."""
        schema = team._make_delegation_tool_schema("coder", "Writes code.")
        assert schema["function"]["name"] == "delegate_to_coder"

    def test_schema_requires_task_argument(self, team):
        """The schema must require the 'task' argument."""
        schema = team._make_delegation_tool_schema("coder", "Writes code.")
        params = schema["function"]["parameters"]
        assert "task" in params["properties"]
        assert "task" in params["required"]
        assert params["properties"]["task"]["type"] == "string"

    def test_schema_type_is_function(self, team):
        """The schema should have type 'function'."""
        schema = team._make_delegation_tool_schema("coder", "Writes code.")
        assert schema["type"] == "function"


# ============================================================================
#  _handle_delegation
# ============================================================================

class TestHandleDelegation:
    @pytest.fixture
    def team(self):
        """A minimal Team with a member that echoes its task."""
        host = _make_test_agent(name="host")
        member_model = _make_test_model(name="member-model")
        member = Agent(
            name="coder",
            model=member_model,
            system_prompt="You are a coder.",
        )
        return Team(
            name="delegation-team",
            host_agent=host,
            member_agents={"coder": member},
        )

    def test_delegates_and_returns_result(self, team):
        """Delegating to a member agent returns its text response."""
        with patch.object(team.member_agents["coder"].model, "chat",
                          return_value=("I have completed the task.", [])):
            result = team._handle_delegation("coder", "Write a function.")
            assert result == "I have completed the task."
            assert "coder" in result or result == "I have completed the task."

    def test_returns_error_for_nonexistent_agent(self, team):
        """Delegating to an unknown agent returns an error string."""
        result = team._handle_delegation("nonexistent", "Do something.")
        assert result.startswith("Error: no agent named")

    def test_member_agent_no_text_output(self, team):
        """When member produces no text, returns a fallback message."""
        with patch.object(team.member_agents["coder"].model, "chat",
                          return_value=("", [])):
            result = team._handle_delegation("coder", "Task.")
            assert "(agent produced no text output)" in result


# ============================================================================
#  _host_turn
# ============================================================================

class TestHostTurn:
    @pytest.fixture
    def team(self):
        """A Team with host + one member for host_turn tests."""
        host_model = _make_test_model(name="host-model")
        host = Agent(
            name="host",
            model=host_model,
            system_prompt="You are a host agent.",
            tool_names=["bash"],
        )
        member_model = _make_test_model(name="member-model")
        member = Agent(
            name="helper",
            model=member_model,
            system_prompt="You help the host.",
        )
        return Team(
            name="turn-team",
            host_agent=host,
            member_agents={"helper": member},
        )

    def test_host_processes_simple_message_no_delegation(self, team):
        """Host responds to a simple message without delegating."""
        with patch.object(team.host_agent.model, "chat",
                          return_value=("Hello, I can help!", [])):
            messages = []
            result = team._host_turn(messages, "Hi")
            assert result[0]["role"] == "user"
            assert result[0]["content"] == "Hi"

    def test_host_delegates_to_member(self, team):
        """Host delegates a subtask to a member agent."""
        delegation_call = {
            "id": "tc1",
            "function": {
                "name": "delegate_to_helper",
                "arguments": '{"task":"Write a test"}',
            },
        }
        with patch.object(team.host_agent.model, "chat") as mock_host_chat, \
             patch.object(team.member_agents["helper"].model, "chat") as mock_member_chat:
            # Turn 1: host makes a delegation call
            # Turn 2: host produces final response
            mock_host_chat.side_effect = [
                ("Let me delegate that.", [delegation_call]),
                ("The helper completed the task.", []),
            ]
            mock_member_chat.return_value = ("Task completed successfully!", [])

            messages = []
            result = team._host_turn(messages, "Do something complex")

            # Should have: user, assistant (with tool_call), tool (delegation result), assistant (final)
            roles = [m["role"] for m in result]
            assert "user" in roles
            assert "assistant" in roles
            assert "tool" in roles
            # The tool result should contain the member's response
            tool_msg = [m for m in result if m["role"] == "tool"][0]
            assert "Task completed successfully!" in tool_msg["content"]

    def test_host_uses_own_tools(self, team):
        """Host can use its own tools (bash, read_file) alongside delegation tools."""
        tool_call = {
            "id": "tc1",
            "function": {
                "name": "bash",
                "arguments": '{"command":"echo hello"}',
            },
        }
        with patch.object(team.host_agent.model, "chat") as mock_chat, \
             patch("tools._check_bash_permission", return_value=True):
            mock_chat.side_effect = [
                ("", [tool_call]),
                ("Done.", []),
            ]
            messages = []
            result = team._host_turn(messages, "Run a command")
            tool_msgs = [m for m in result if m["role"] == "tool"]
            assert len(tool_msgs) == 1
            assert "hello" in tool_msgs[0]["content"]

    def test_max_turns_respected(self, team):
        """Host turn stops after max_turns even if model keeps making tool calls."""
        team.host_agent.max_turns = 3
        tool_call = {
            "id": "tc1",
            "function": {
                "name": "bash",
                "arguments": '{"command":"echo x"}',
            },
        }
        with patch.object(team.host_agent.model, "chat",
                          return_value=("", [tool_call])), \
             patch("tools._check_bash_permission", return_value=True):
            messages = []
            result = team._host_turn(messages, "Go")
            # user + 3*(assistant+tool) = 7 messages
            assert len(result) == 7


# ============================================================================
#  chat_loop
# ============================================================================

class TestTeamChatLoop:
    @pytest.fixture
    def solo_team(self):
        """A team with only a host (no members)."""
        model = _make_test_model()
        host = Agent(
            name="solo-host",
            model=model,
            system_prompt="You are a solo host.",
        )
        return Team(
            name="solo-team",
            host_agent=host,
            member_agents={},
        )

    @pytest.fixture
    def multi_team(self):
        """A team with host + one member."""
        host_model = _make_test_model(name="h-model")
        host = Agent(
            name="multi-host",
            model=host_model,
            system_prompt="You are a host with helpers.",
        )
        member_model = _make_test_model(name="m-model")
        member = Agent(
            name="helper",
            model=member_model,
            system_prompt="You are a helper.",
        )
        return Team(
            name="multi-team",
            host_agent=host,
            member_agents={"helper": member},
        )

    def test_exit_on_quit(self, solo_team):
        """Typing 'quit' exits the chat loop."""
        with patch("builtins.input", side_effect=["quit"]), \
             patch.object(solo_team.host_agent.model, "chat") as mock_chat:
            solo_team.chat_loop()
            mock_chat.assert_not_called()

    def test_exit_on_exit(self, solo_team):
        """Typing 'exit' exits the chat loop."""
        with patch("builtins.input", side_effect=["exit"]), \
             patch.object(solo_team.host_agent.model, "chat") as mock_chat:
            solo_team.chat_loop()
            mock_chat.assert_not_called()

    def test_exit_on_eof(self, solo_team):
        """EOF triggers sys.exit(0)."""
        with patch("builtins.input", side_effect=EOFError), \
             patch.object(solo_team.host_agent.model, "chat") as mock_chat:
            with pytest.raises(SystemExit) as exc_info:
                solo_team.chat_loop()
            assert exc_info.value.code == 0
            mock_chat.assert_not_called()

    def test_exit_on_keyboard_interrupt(self, solo_team):
        """KeyboardInterrupt triggers sys.exit(0)."""
        with patch("builtins.input", side_effect=KeyboardInterrupt), \
             patch.object(solo_team.host_agent.model, "chat") as mock_chat:
            with pytest.raises(SystemExit) as exc_info:
                solo_team.chat_loop()
            assert exc_info.value.code == 0
            mock_chat.assert_not_called()

    def test_empty_input_is_skipped(self, solo_team):
        """Empty and whitespace-only inputs are ignored."""
        with patch("builtins.input", side_effect=["", "  ", "exit"]), \
             patch.object(solo_team.host_agent.model, "chat") as mock_chat:
            solo_team.chat_loop()
            mock_chat.assert_not_called()

    def test_processes_one_message(self, multi_team):
        """A single message is processed by the host."""
        with patch("builtins.input", side_effect=["Hello", "quit"]), \
             patch.object(multi_team.host_agent.model, "chat",
                          return_value=("Hi there!", [])):
            multi_team.chat_loop()

    def test_system_prompt_included(self, multi_team):
        """The host's system prompt is the first message."""
        with patch("builtins.input", side_effect=["Hello", "quit"]), \
             patch.object(multi_team.host_agent.model, "chat",
                          return_value=("Hi!", [])) as mock_chat:
            multi_team.chat_loop()
            # The first call should include the system prompt
            call_args = mock_chat.call_args[0][0]
            assert call_args[0]["role"] == "system"
            assert "You are a host with helpers." in call_args[0]["content"]

    def test_solo_team_prints_no_members_message(self, solo_team, capsys):
        """When there are no member agents, chat_loop prints an appropriate message."""
        with patch("builtins.input", side_effect=["quit"]):
            solo_team.chat_loop()
        captured = capsys.readouterr()
        assert "none" in captured.out.lower() or "no member" in captured.out.lower()

    def test_multi_team_prints_members(self, multi_team, capsys):
        """When there are member agents, chat_loop lists them."""
        with patch("builtins.input", side_effect=["quit"]):
            multi_team.chat_loop()
        captured = capsys.readouterr()
        assert "helper" in captured.out
