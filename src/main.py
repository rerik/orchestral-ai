"""
Entry point for the smart-agent framework.

Loads a Model and an Agent from YAML config files, then starts the
interactive chat loop.

Usage:
    python src/main.py

Or specify custom configs:
    python src/main.py --model configs/models/deepseek.yaml \\
                       --agent configs/agents/coding_agent.yaml
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from model import Model
from agent import Agent

# ---------------------------------------------------------------------------
#  Default config paths (relative to the project root)
# ---------------------------------------------------------------------------

DEFAULT_MODEL_YAML = "configs/models/deepseek.yaml"
DEFAULT_AGENT_YAML = "configs/agents/coding_agent.yaml"


def resolve_path(path: str) -> str:
    """If *path* is relative, resolve it against the project root."""
    if os.path.isabs(path):
        return path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.normpath(os.path.join(root, path))


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Smart Agent — configurable AI agent")
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL_YAML,
        help=f"Path to model YAML config (default: {DEFAULT_MODEL_YAML})",
    )
    parser.add_argument(
        "--agent", "-a",
        default=DEFAULT_AGENT_YAML,
        help=f"Path to agent YAML config (default: {DEFAULT_AGENT_YAML})",
    )
    args = parser.parse_args()

    model_path = resolve_path(args.model)
    agent_path = resolve_path(args.agent)

    # --- Load model ---
    if not os.path.isfile(model_path):
        print(f"ERROR: model config not found: {model_path}")
        sys.exit(1)

    print(f"📦 Loading model from: {model_path}")
    model = Model.from_yaml(model_path)
    print(f"   ✓ Model '{model.name}' ({model.model_id}) loaded")

    # --- Register model so the agent can reference it by name ---
    model_registry = {model.name: model}

    # --- Load agent ---
    if not os.path.isfile(agent_path):
        print(f"ERROR: agent config not found: {agent_path}")
        sys.exit(1)

    print(f"🤖 Loading agent from: {agent_path}")
    agent = Agent.from_yaml(agent_path, model_registry=model_registry)
    print(f"   ✓ Agent '{agent.name}' loaded with tools: {agent.tool_names}")
    print()

    # --- Start chat ---
    agent.chat_loop()


if __name__ == "__main__":
    main()
