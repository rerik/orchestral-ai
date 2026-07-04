"""
Agent class — encapsulates an agent loop (system prompt, model, tools).

Can be built from a YAML config file or instantiated directly.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import yaml

from model import Model
from tools import get_tool_schemas, call_tool, safe_json_loads


@dataclass
class Agent:
    """An AI agent that holds a conversation loop with tools and an LLM model."""

    name: str
    model: Model
    system_prompt: str = ""
    max_turns: int = 1000
    tool_names: list[str] = field(default_factory=list)
    _cwd: str = field(default_factory=os.getcwd)

    # ------------------------------------------------------------------
    #  Factory: build from a YAML file
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, yaml_path: str, model_registry: dict[str, Model] | None = None) -> "Agent":
        """Load agent configuration from a YAML file.

        YAML keys
        ---------
        name                (required)  human-readable name for this agent
        model               (required)  either a model name (looked up in model_registry)
                                        or a path to a model YAML file
        system_prompt       (optional)  literal system prompt string
        system_prompt_file  (optional)  path to a text file with the system prompt
        max_turns           (optional)  max LLM calls per user turn (default 1000)
        tools               (optional)  list of tool names to equip the agent with
        cwd                 (optional)  working directory for template substitution

        At least one of `system_prompt` or `system_prompt_file` must be provided.
        If both are given, `system_prompt` takes precedence.
        """
        if model_registry is None:
            model_registry = {}

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Agent YAML must contain a dict, got {type(data)}")

        for required in ("name", "model"):
            if required not in data:
                raise ValueError(f"Agent YAML is missing required key: '{required}'")

        # --- resolve model ---
        model_ref = data["model"]
        if isinstance(model_ref, str):
            # Try registry first, then treat as a YAML path
            if model_ref in model_registry:
                model = model_registry[model_ref]
            elif os.path.isfile(model_ref):
                model = Model.from_yaml(model_ref)
            else:
                raise ValueError(
                    f"Model '{model_ref}' not found in registry and "
                    f"'{model_ref}' is not a valid file path."
                )
        elif isinstance(model_ref, dict):
            # Inline model definition
            model = Model(
                name=model_ref.get("name", "inline"),
                base_url=model_ref["base_url"],
                model_id=model_ref["model_id"],
                api_key=model_ref.get("api_key", ""),
                api_key_env=model_ref.get("api_key_env", ""),
                temperature=float(model_ref.get("temperature", 0.1)),
                max_tokens=int(model_ref.get("max_tokens", 4096)),
                extra_headers=model_ref.get("headers", {}),
            )
        else:
            raise ValueError(f"Invalid 'model' value in agent YAML: {model_ref}")

        # --- system prompt ---
        system_prompt = data.get("system_prompt", "")
        system_prompt_file = data.get("system_prompt_file", "")
        if not system_prompt and system_prompt_file:
            # Resolve relative to the agent YAML file's directory
            yaml_dir = os.path.dirname(os.path.abspath(yaml_path))
            sp_path = system_prompt_file
            if not os.path.isabs(sp_path):
                sp_path = os.path.join(yaml_dir, sp_path)
            if not os.path.isfile(sp_path):
                raise ValueError(f"System prompt file not found: {sp_path}")
            with open(sp_path, "r", encoding="utf-8") as f:
                system_prompt = f.read().strip()

        # --- cwd for template substitution ---
        cwd = data.get("cwd", os.getcwd())

        # Substitute {cwd} placeholder
        system_prompt = system_prompt.format(cwd=cwd)

        # --- tools ---
        tool_names = data.get("tools", [])

        return cls(
            name=data["name"],
            model=model,
            system_prompt=system_prompt,
            max_turns=int(data.get("max_turns", 1000)),
            tool_names=tool_names,
            _cwd=cwd,
        )

    # ------------------------------------------------------------------
    #  Conversation
    # ------------------------------------------------------------------

    @staticmethod
    def _format_tool_call(func: str, arguments: dict) -> str:
        """Return a human-readable tool call string based on the tool type."""
        if func == "read_file":
            return f"🔧 read_file: {arguments.get('filepath', arguments)}"
        elif func == "bash":
            return f"🔧 bash: {arguments.get('command', arguments)}"
        elif func == "web_search":
            return f"🔧 web_search: \"{arguments.get('query', arguments)}\""
        else:
            return f"🔧 Tool: {func}({json.dumps(arguments, ensure_ascii=False)})"

    def _get_tool_schemas(self) -> list[dict]:
        """Return the LLM tool schemas for this agent's tool set."""
        return get_tool_schemas(self.tool_names)

    def agent_turn(self, messages: list[dict], user_message: str) -> list[dict]:
        """Append a user message and run the agent loop until no more tool calls.

        Returns the updated messages list.
        """
        messages.append({"role": "user", "content": user_message})
        tools = self._get_tool_schemas()

        try:
            for _ in range(1, self.max_turns + 1):
                content, tool_calls = self.model.chat(messages, tools=tools)

                if content:
                    print(f"\n🤖 {content}")

                if not tool_calls:
                    if not content:
                        print("(no text output)")
                    else:
                        # Append final assistant response so callers can capture it
                        messages.append({"role": "assistant", "content": content})
                    print()
                    return messages

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
                assistant_msg["tool_calls"] = tool_calls
                messages.append(assistant_msg)

                prefix = "\n" if content else ""
                for tc in tool_calls:
                    func = tc["function"]["name"]
                    arguments = safe_json_loads(tc["function"]["arguments"])
                    tool_call_id = tc["id"]

                    print(f"{prefix}{Agent._format_tool_call(func, arguments)}")
                    result = call_tool(func, arguments)
                    print(f"   → {result[:500]}{'...' if len(result) > 500 else ''}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result,
                    })

            print(f"\n⚠️ Max turns ({self.max_turns}) reached. Stopping.")
            return messages

        except RuntimeError as e:
            print(f"\n{e}")
            print("Sorry, the request failed. Please try again.")
            # Remove the user message that was just appended so it doesn't
            # corrupt the message history for the next turn.
            messages.pop()
            return messages

    def chat_loop(self) -> None:
        """Run an interactive chat loop (stdin/stdout)."""
        print(f"🤖 {self.name} — Chat mode")
        print("Type your task below. Type 'exit' or 'quit' to end the session.")
        print()

        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        while True:
            try:
                user_input = input(">>> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n👋 Goodbye!")
                sys.exit(0)

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("👋 Goodbye!")
                break

            try:
                messages = self.agent_turn(messages, user_input)
            except RuntimeError:
                # Error already printed by agent_turn
                continue
