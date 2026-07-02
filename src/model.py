"""
Model class — encapsulates an LLM model configuration.

Can be built from a YAML config file or instantiated directly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

import requests
import yaml


@dataclass
class Model:
    """Represents a configured LLM model (provider, endpoint, parameters)."""

    name: str
    base_url: str
    model_id: str
    api_key: str = ""
    api_key_env: str = ""  # name of the env var that holds the API key
    temperature: float = 0.1
    max_tokens: int = 4096
    extra_headers: dict[str, str] = field(default_factory=dict)

    # ------------------------------------------------------------------
    #  Factory: build from a YAML file
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "Model":
        """Load model configuration from a YAML file.

        YAML keys
        ---------
        name            (required)  human-readable name for this model
        base_url        (required)  LLM API base URL, e.g. https://api.deepseek.com
        model_id        (required)  model identifier, e.g. deepseek-v4-pro
        api_key_env     (optional)  environment variable holding the API key
        api_key         (optional)  literal API key (avoid committing to VCS)
        temperature     (optional)  default 0.1
        max_tokens      (optional)  default 4096
        headers         (optional)  extra HTTP headers as key-value pairs
        """
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Model YAML must contain a dict, got {type(data)}")

        for required in ("name", "base_url", "model_id"):
            if required not in data:
                raise ValueError(f"Model YAML is missing required key: '{required}'")

        # Resolve API key
        api_key = data.get("api_key", "")
        api_key_env = data.get("api_key_env", "")
        if api_key_env and not api_key:
            api_key = os.environ.get(api_key_env, "")
            if not api_key:
                print(
                    f"WARNING: environment variable '{api_key_env}' "
                    f"(referenced by model '{data['name']}') is not set."
                )

        headers = data.get("headers", {})
        if not isinstance(headers, dict):
            raise ValueError("'headers' must be a dict in model YAML")

        # Ensure Content-Type is present
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        return cls(
            name=data["name"],
            base_url=data["base_url"].rstrip("/"),
            model_id=data["model_id"],
            api_key=api_key,
            api_key_env=api_key_env,
            temperature=float(data.get("temperature", 0.1)),
            max_tokens=int(data.get("max_tokens", 4096)),
            extra_headers=headers,
        )

    # ------------------------------------------------------------------
    #  Chat completion call
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ) -> tuple[str, list[dict]]:
        """Send messages to the LLM and return (content, tool_calls).

        Parameters
        ----------
        messages    List of message dicts (role/content).
        tools       Optional list of tool schemas for function calling.
        tool_choice One of "auto", "none", or "required".

        Returns
        -------
        (content, tool_calls) — content is stripped text (may be empty),
        tool_calls is a list of tool-call dicts (may be empty).
        """
        if not self.api_key:
            raise RuntimeError(
                f"No API key available for model '{self.name}'. "
                f"Set the '{self.api_key_env}' environment variable or "
                f"provide 'api_key' in the YAML config."
            )

        headers = {**self.extra_headers, "Authorization": f"Bearer {self.api_key}"}

        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        msg = response.json()["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []

        return content, tool_calls
