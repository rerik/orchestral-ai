"""Tests for src/main.py"""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from main import resolve_path, main


# ============================================================================
#  resolve_path
# ============================================================================

class TestResolvePath:
    def test_absolute_path_unchanged(self):
        abs_path = "/absolute/path/to/file.yaml"
        assert resolve_path(abs_path) == abs_path

    def test_relative_path_resolved(self):
        """Relative path should be resolved against the project root."""
        result = resolve_path("configs/models/deepseek.yaml")
        assert os.path.isabs(result)
        assert result.endswith("configs/models/deepseek.yaml")

    def test_current_directory_relative(self):
        result = resolve_path("./foo.yaml")
        assert os.path.isabs(result)
        assert result.endswith("foo.yaml")


# ============================================================================
#  main
# ============================================================================

class TestMain:
    def test_missing_model_config(self, temp_dir, monkeypatch, capsys):
        """When model config doesn't exist, print error and exit."""
        monkeypatch.setattr(sys, "argv", ["main", "--model", "/nonexistent/model.yaml", "--agent", "/nonexistent/agent.yaml"])
        with pytest.raises(SystemExit) as exc_info, \
             patch("builtins.print") as mock_print:
            main()
        assert exc_info.value.code == 1

    def test_missing_agent_config(self, temp_dir, monkeypatch, capsys):
        """When agent config doesn't exist, print error and exit."""
        monkeypatch.setattr(sys, "argv", [
            "main",
            "--model", os.path.join(temp_dir, "model.yaml"),
            "--agent", "/nonexistent/agent.yaml",
        ])

        # Write a valid model yaml so we get past that check
        import yaml
        with open(os.path.join(temp_dir, "model.yaml"), "w") as f:
            yaml.dump({"name": "m", "base_url": "https://x.com", "model_id": "v1"}, f)

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_successful_run(self, temp_dir, monkeypatch):
        """Full happy-path: load configs and start chat loop."""
        import yaml
        model_yaml = os.path.join(temp_dir, "model.yaml")
        agent_yaml = os.path.join(temp_dir, "agent.yaml")

        with open(model_yaml, "w") as f:
            yaml.dump({"name": "test-model", "base_url": "https://x.com", "model_id": "v1"}, f)

        with open(agent_yaml, "w") as f:
            yaml.dump({
                "name": "test-agent",
                "model": {
                    "name": "inline",
                    "base_url": "https://x.com",
                    "model_id": "v1",
                },
                "system_prompt": "Hi",
            }, f)

        monkeypatch.setattr(sys, "argv", [
            "main",
            "--model", model_yaml,
            "--agent", agent_yaml,
        ])

        with patch("sys.exit") as mock_exit, \
             patch("builtins.input", side_effect=["quit"]):
            main()

    def test_default_config_paths(self, monkeypatch):
        """When no args given, default config paths are used."""
        monkeypatch.setattr(sys, "argv", ["main", "--agent", "configs/agents/coding_agent.yaml"])

        # The default paths should exist in the project
        with patch("sys.exit") as mock_exit, \
             patch("builtins.input", side_effect=["quit"]), \
             patch("main.load_dotenv"):
            # This should work because the actual config files exist
            main()

    def test_model_registry_passed_to_agent(self, temp_dir, monkeypatch):
        """The model loaded from --model is registered and matched by name
        in the agent YAML's `model` field."""
        import yaml
        model_yaml = os.path.join(temp_dir, "model.yaml")
        agent_yaml = os.path.join(temp_dir, "agent.yaml")

        with open(model_yaml, "w") as f:
            yaml.dump({"name": "deepseek-v4-pro", "base_url": "https://x.com", "model_id": "v1"}, f)

        with open(agent_yaml, "w") as f:
            yaml.dump({
                "name": "agent",
                "model": "deepseek-v4-pro",  # looked up by name in registry
                "system_prompt": "Hi",
            }, f)

        monkeypatch.setattr(sys, "argv", [
            "main",
            "--model", model_yaml,
            "--agent", agent_yaml,
        ])

        with patch("builtins.input", side_effect=["quit"]):
            main()
