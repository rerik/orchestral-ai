"""
Team class — orchestrates a multi-agent team.

Loads a team YAML config, creates the host agent and member agents,
and exposes member agents as delegation tools to the host.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

from .model import Model
from .agent import Agent
from .tools import get_tool_schemas, call_tool, safe_json_loads, configure_risk_model
from .input_handler import setup_readline, get_input
from .chat_manager import ChatManager
from .main import find_config_path, get_config_search_dirs


@dataclass
class Team:
    """A team of agents orchestrated by a host agent.

    The host analyzes tasks, decomposes them into subtasks, and delegates
    to member agents via dynamically-generated delegation tools.
    """

    name: str
    host_agent: Agent
    member_agents: dict[str, Agent]  # name -> Agent
    chat_manager: ChatManager | None = None

    # ------------------------------------------------------------------
    #  Factory: build from a YAML file
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "Team":
        """Load a team configuration from a YAML file.

        YAML keys
        ---------
        name          (required)  team name
        host.agent    (required)  path to host agent YAML config
        agents        (optional)  list of member agents, each with:
                      - name        agent name (used in delegation tool)
                      - agent       path to agent YAML config
                      - description what this agent does (injected into host prompt)

        Model configs are auto-loaded from configs/models/ and passed to each
        agent so they can reference models by name.
        """
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Team YAML must contain a dict, got {type(data)}")

        if "name" not in data:
            raise ValueError("Team YAML missing required key: 'name'")
        if "host" not in data or "agent" not in data.get("host", {}):
            raise ValueError("Team YAML missing required key: 'host.agent'")

        # --- Auto-load all model configs so agents can reference them by name ---
        # Searches all config directories; higher-priority dirs win (first found sticks).
        model_registry: dict[str, Model] = {}
        for search_dir in get_config_search_dirs():
            models_dir = os.path.join(search_dir, "configs", "models")
            if os.path.isdir(models_dir):
                for fname in sorted(os.listdir(models_dir)):
                    if fname.endswith((".yaml", ".yml")):
                        model_path = os.path.join(models_dir, fname)
                        try:
                            model = Model.from_yaml(model_path)
                            if model.name not in model_registry:
                                model_registry[model.name] = model
                        except Exception:
                            pass  # skip broken model configs

        # --- Configure AI risk assessment for bash commands ---
        # Use the cheapest available model; fall back to host model; 
        # if no models at all, stays rule-based.
        risk_model: Model | None = None
        if model_registry:
            # Prefer cheapest model (lowest cost_coefficient)
            cheapest = min(model_registry.values(), key=lambda m: m.cost_coefficient)
            risk_model = cheapest
        configure_risk_model(risk_model)

        # --- Load host agent ---
        host_agent_path = find_config_path(data["host"]["agent"])
        if not os.path.isfile(host_agent_path):
            raise ValueError(f"Host agent config not found: {host_agent_path}")
        host_agent = Agent.from_yaml(host_agent_path, model_registry=model_registry)

        # --- Load member agents ---
        member_agents: dict[str, Agent] = {}
        member_descriptions: dict[str, str] = {}

        for entry in data.get("agents", []) or []:
            name = entry.get("name", "").strip()
            agent_path = find_config_path(entry.get("agent", ""))
            description = entry.get("description", "").strip()

            if not name:
                raise ValueError("Each member agent must have a 'name'")
            if not agent_path or not os.path.isfile(agent_path):
                raise ValueError(f"Agent config for '{name}' not found: {agent_path}")
            if name in member_agents:
                raise ValueError(f"Duplicate agent name: '{name}'")

            agent = Agent.from_yaml(agent_path, model_registry=model_registry)
            member_agents[name] = agent
            cost = agent.model.cost_coefficient
            if cost != 1.0:
                cost_note = f" [Model cost coefficient: {cost}]"
                member_descriptions[name] = description + cost_note
            else:
                member_descriptions[name] = description

        # --- Inject member agent descriptions into host system prompt ---
        team = cls(
            name=data["name"],
            host_agent=host_agent,
            member_agents=member_agents,
        )
        team._inject_member_descriptions(member_descriptions)

        return team

    # ------------------------------------------------------------------
    #  Member description injection
    # ------------------------------------------------------------------

    # Note: descriptions now include cost coefficient info where applicable.
    def _inject_member_descriptions(self, descriptions: dict[str, str]) -> None:
        """Append member agent descriptions to the host's system prompt."""
        if not descriptions:
            return

        lines = ["\n## Available team members\n"]
        for name, desc in descriptions.items():
            lines.append(f"### {name}")
            lines.append(f"{desc}\n")

        self.host_agent.system_prompt += "\n".join(lines)

    # ------------------------------------------------------------------
    #  Delegation tool factory
    # ------------------------------------------------------------------

    def _make_delegation_tool_schema(self, agent_name: str, description: str) -> dict:
        """Build an LLM tool schema for delegating to a member agent."""
        tool_name = f"delegate_to_{agent_name}"

        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": (
                    f"Delegate a subtask to the '{agent_name}' agent. "
                    f"This agent is {description}\n\n"
                    f"Use this when a subtask matches this agent's expertise. "
                    f"Provide a clear, self-contained task description that "
                    f"the agent can work on independently. The agent will "
                    f"return its result as a string."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": (
                                "A clear, self-contained description of the "
                                "subtask for this agent to perform. Include "
                                "all necessary context so the agent can work "
                                "independently."
                            ),
                        }
                    },
                    "required": ["task"],
                },
            },
        }

    def _handle_delegation(self, agent_name: str, task: str) -> str:
        """Execute a delegated task on a member agent and return its result."""
        agent = self.member_agents.get(agent_name)
        if not agent:
            return f"Error: no agent named '{agent_name}' in the team."

        print(f"\n   ┌─ Delegating to '{agent_name}' ─────────────────────")
        print(f"   │ Task: {task[:200]}{'...' if len(task) > 200 else ''}")

        # Run the agent on this task (fresh conversation)
        messages: list[dict] = []
        if agent.system_prompt:
            messages.append({"role": "system", "content": agent.system_prompt})

        result_messages = agent.agent_turn(messages, task)

        # Extract the final response — the last assistant message without tool_calls
        final_output = ""
        for msg in reversed(result_messages):
            if msg["role"] == "assistant" and "tool_calls" not in msg:
                final_output = msg.get("content", "")
                break

        if not final_output:
            final_output = "(agent produced no text output)"

        print(f"   └─ '{agent_name}' finished ─────────────────────────────")
        return final_output

    # ------------------------------------------------------------------
    #  Host turn — with delegation tools
    # ------------------------------------------------------------------

    def _host_turn(self, messages: list[dict], user_message: str) -> list[dict]:
        """Run one host turn. The host can use its own tools AND delegation tools.

        This extends Agent.agent_turn by dynamically adding delegation tool
        schemas and handling delegation calls.
        """
        messages.append({"role": "user", "content": user_message})

        # Build combined tool list: host's own tools + delegation tools
        host_tool_schemas = get_tool_schemas(self.host_agent.tool_names)
        delegation_schemas = []
        for name, agent in self.member_agents.items():
            # Find the description from the host's system prompt
            # We stored it when injecting — but let's derive it from the tool
            desc = f"specialized in handling tasks delegated by the host."
            delegation_schemas.append(
                self._make_delegation_tool_schema(name, desc)
            )

        all_tools = host_tool_schemas + delegation_schemas
        delegation_names = set(self.member_agents.keys())

        try:
            for turn in range(1, self.host_agent.max_turns + 1):
                content, tool_calls = self.host_agent.model.chat(
                    messages, tools=all_tools if all_tools else None
                )

                if content:
                    print(f"\n🤖 {content}")

                if not tool_calls:
                    if not content:
                        print("(no text output)")
                    else:
                        messages.append({"role": "assistant", "content": content})
                    print()
                    return messages

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content or "",
                }
                assistant_msg["tool_calls"] = tool_calls
                messages.append(assistant_msg)

                prefix = "\n" if content else ""
                for tc in tool_calls:
                    func = tc["function"]["name"]
                    arguments = safe_json_loads(tc["function"]["arguments"])
                    tool_call_id = tc["id"]

                    # Check if this is a delegation call
                    if func.startswith("delegate_to_"):
                        agent_name = func[len("delegate_to_"):]
                        task = arguments.get("task", "")
                        print(f"{prefix}🔧 Delegating to: {agent_name}")
                        result = self._handle_delegation(agent_name, task)
                    else:
                        print(f"{prefix}{Agent._format_tool_call(func, arguments)}")
                        result = call_tool(func, arguments)
                        print(f"   → {result[:500]}{'...' if len(result) > 500 else ''}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    })

            print(f"\n⚠️ Max turns ({self.host_agent.max_turns}) reached. Stopping.")
            return messages

        except RuntimeError as e:
            print(f"\n{e}")
            print("Sorry, the request failed. Please try again.")
            # Remove the user message that was just appended so it doesn't
            # corrupt the message history for the next turn.
            messages.pop()
            return messages

    # ------------------------------------------------------------------
    #  Interactive chat loop
    # ------------------------------------------------------------------

    def chat_loop(self, chat_manager: ChatManager | None = None) -> None:
        """Run an interactive chat loop with the host orchestrating the team.

        If a ChatManager is provided (via argument or self.chat_manager),
        messages are persisted to the chat database and /chats is supported.
        Otherwise, runs the original non-persistent loop.
        """
        cm = chat_manager or self.chat_manager
        if cm is None:
            # No chat manager — run without persistence (backward compat)
            setup_readline()
            print(f"🤖 Team '{self.name}' — Multi-Agent Chat")
            print(f"   Host: {self.host_agent.name}")
            if self.member_agents:
                print(f"   Members: {', '.join(self.member_agents.keys())}")
            else:
                print("   Members: (none — host handles everything)")
            print()
            print("Type your task below. Type 'exit' or 'quit' to end the session.")
            print()

            messages: list[dict] = []
            if self.host_agent.system_prompt:
                messages.append({
                    "role": "system",
                    "content": self.host_agent.system_prompt,
                })

            while True:
                user_input = get_input()

                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit"):
                    print("👋 Goodbye!")
                    break

                try:
                    messages = self._host_turn(messages, user_input)
                except RuntimeError:
                    # Error already printed by _host_turn
                    continue
            return

        setup_readline()

        # Determine if we're resuming a chat
        if cm.current_chat_id:
            chat_data = cm.load_chat(cm.current_chat_id)
            messages = chat_data.get("messages", []) if chat_data else []
            if messages:
                print(f"📂 Resuming chat: {cm.current_chat_id}")
                print(f"   Title: {chat_data.get('title', 'N/A')}")
        else:
            chat_id = cm.create_chat(mode="team")
            print(f"💬 New chat: {chat_id}")
            messages = []
            if self.host_agent.system_prompt:
                messages.append({
                    "role": "system",
                    "content": self.host_agent.system_prompt,
                })

        print(f"🤖 Team '{self.name}' — Multi-Agent Chat")
        print(f"   Host: {self.host_agent.name}")
        if self.member_agents:
            print(f"   Members: {', '.join(self.member_agents.keys())}")
        else:
            print("   Members: (none — host handles everything)")
        print()
        print("Type your task below. Type 'exit' or 'quit' to end the session.")
        print()

        while True:
            user_input = get_input()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                cm.save_messages(messages)
                print("👋 Goodbye!")
                break
            if user_input == "/chats":
                print()
                print(cm.format_chat_list())
                print()
                continue

            try:
                messages = self._host_turn(messages, user_input)
                cm.save_messages(messages)
            except RuntimeError:
                # Error already printed by _host_turn
                continue
