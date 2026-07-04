"""
Model class — encapsulates an LLM model configuration.

Can be built from a YAML config file or instantiated directly.
"""

from __future__ import annotations

import os
import sys
import time
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
    cost_coefficient: float = 1.0

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
            cost_coefficient=float(data.get("cost_coefficient", 1.0)),
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

        max_retries = 3

        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=120,
                )
            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    print(
                        f"Request timed out. Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})..."
                    )
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"Request timed out after {max_retries + 1} attempts. "
                    f"The server at {self.base_url} did not respond in time."
                )

            except requests.exceptions.ConnectionError as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    print(
                        f"Connection error: {e}. Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})..."
                    )
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"Connection failed after {max_retries + 1} attempts: {e}"
                )

            except requests.exceptions.RequestException as e:
                # Other request-level errors (not retryable)
                raise RuntimeError(f"Request failed: {e}")

            # ------------------------------------------------------------------
            #  Handle HTTP error responses
            # ------------------------------------------------------------------
            if response.status_code >= 400:
                # Try to extract a meaningful error message from the API
                try:
                    error_body = response.json()
                except (ValueError, requests.exceptions.JSONDecodeError):
                    error_body = response.text

                if isinstance(error_body, dict):
                    api_error = error_body.get("error", {})
                    if isinstance(api_error, dict):
                        api_error = api_error.get("message", str(error_body))
                    else:
                        api_error = str(api_error) or str(error_body)
                else:
                    api_error = str(error_body).strip() or response.reason

                # Retryable: 429 (rate limit) and 5xx (server errors)
                is_retryable = (
                    response.status_code == 429 or response.status_code >= 500
                )

                if is_retryable and attempt < max_retries:
                    wait = 2 ** attempt
                    print(
                        f"API error ({response.status_code}): {api_error}. "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})..."
                    )
                    time.sleep(wait)
                    continue

                # Non-retryable 4xx error → print and raise
                if response.status_code < 500:
                    print(f"API error ({response.status_code}): {api_error}")
                    raise RuntimeError(
                        f"API request failed ({response.status_code}): {api_error}"
                    )

                # Retryable error but out of retries
                print(
                    f"API error ({response.status_code}): {api_error}. "
                    f"All {max_retries + 1} attempts exhausted."
                )
                raise RuntimeError(
                    f"API request failed after {max_retries + 1} attempts "
                    f"({response.status_code}): {api_error}"
                )

            # ------------------------------------------------------------------
            #  Success — parse the response
            # ------------------------------------------------------------------
            msg = response.json()["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            tool_calls = msg.get("tool_calls") or []

            return content, tool_calls
