"""
Entry point for the orchestral-ai framework.

Supports two modes:
  1. Team mode (--team):    Multi-agent orchestration with a host + member agents
  2. Single mode (--agent): Single agent chat (original behavior)

Usage:
    python src/main.py --team configs/team.yaml
    python src/main.py --model configs/models/deepseek.yaml \\
                       --agent configs/agents/coding_agent.yaml
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from .model import Model
from .agent import Agent
from .team import Team
from .chat_manager import ChatManager

# ---------------------------------------------------------------------------
#  Default config paths (relative to the project root)
# ---------------------------------------------------------------------------

DEFAULT_MODEL_YAML = "configs/models/deepseek.yaml"
DEFAULT_AGENT_YAML = "configs/agents/coding_agent.yaml"
DEFAULT_TEAM_YAML = "configs/team.yaml"


def resolve_path(path: str) -> str:
    """If *path* is relative, resolve it against the package directory.

    In development: src/ (where main.py lives alongside configs/, prompts/).
    When installed: site-packages/smart_agent/.
    """
    if os.path.isabs(path):
        return path
    root = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(root, path))


def run_single_agent(model_path: str, agent_path: str, chat_manager: ChatManager | None = None) -> None:
    """Run a single agent in interactive chat mode."""
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
    agent.chat_manager = chat_manager
    print(f"   ✓ Agent '{agent.name}' loaded with tools: {agent.tool_names}")
    print()

    # --- Start chat ---
    agent.chat_loop()


def run_team(team_path: str, chat_manager: ChatManager | None = None) -> None:
    """Run a multi-agent team in interactive chat mode."""
    if not os.path.isfile(team_path):
        print(f"ERROR: team config not found: {team_path}")
        sys.exit(1)

    print(f"👥 Loading team from: {team_path}")
    team = Team.from_yaml(team_path)
    team.chat_manager = chat_manager
    print(f"   ✓ Team '{team.name}' loaded")
    print(f"   ✓ Host: '{team.host_agent.name}' "
          f"({team.host_agent.model.model_id})")
    if team.member_agents:
        for name, agent in team.member_agents.items():
            print(f"   ✓ Member: '{name}' ({agent.model.model_id}) "
                  f"tools: {agent.tool_names}")
    else:
        print("   ✓ Members: (none — host handles everything)")
    print()

    team.chat_loop()


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Smart Agent — configurable AI agent (single or multi-agent team)"
    )
    parser.add_argument(
        "--team", "-t",
        default=None,
        help=f"Path to team YAML config (multi-agent mode). Default: {DEFAULT_TEAM_YAML}",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help=f"Path to model YAML config (single-agent mode; default: {DEFAULT_MODEL_YAML})",
    )
    parser.add_argument(
        "--agent", "-a",
        default=None,
        help=f"Path to agent YAML config (single-agent mode; default: {DEFAULT_AGENT_YAML})",
    )
    parser.add_argument(
        "--chats",
        action="store_true",
        default=False,
        help="List all saved chats and exit.",
    )
    parser.add_argument(
        "--chat",
        default=None,
        help="Resume a specific chat by ID.",
    )
    args = parser.parse_args()

    # --- ChatManager instance for all modes ---
    chat_mgr = ChatManager()

    # Handle --chats flag: list chats and exit
    if args.chats:
        print(chat_mgr.format_chat_list())
        return

    # Handle --chat <id> flag: set the chat to resume
    if args.chat:
        if not chat_mgr.load_chat(args.chat):
            print(f"ERROR: Chat '{args.chat}' not found.")
            return

    # Determine mode: if --team is explicitly given, or if --agent is NOT given
    # and the default team config exists, use team mode.
    team_given = args.team is not None
    agent_given = args.agent is not None

    if team_given or not agent_given:
        # Team mode
        team_path = resolve_path(args.team or DEFAULT_TEAM_YAML)
        run_team(team_path, chat_mgr)
    else:
        # Single-agent mode (--agent was explicitly given without --team)
        model_path = resolve_path(args.model or DEFAULT_MODEL_YAML)
        agent_path = resolve_path(args.agent)
        run_single_agent(model_path, agent_path, chat_mgr)


if __name__ == "__main__":
    main()
