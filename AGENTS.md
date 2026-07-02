# Project Agents Overview

This document outlines the structure and components of the Smart Agent framework.

## Directory Analysis

```
smart_agent/
├── configs/
│   ├── agents/
│   │   └── coding_agent.yaml      # Agent config (model, tools, system prompt)
│   └── models/
│       └── deepseek.yaml          # Model config (API endpoint, params)
├── prompts/
│   └── system_prompt.txt          # System prompt template
├── src/
│   ├── __init__.py                # Package marker
│   ├── main.py                    # Entry point — argument parsing & orchestration
│   ├── model.py                   # Model class — LLM config & chat completion
│   ├── agent.py                   # Agent class — conversation loop & tool orchestration
│   └── tools.py                   # Tool registry — bash & read_file implementations
├── tests/
│   ├── __init__.py                # Package marker
│   ├── conftest.py                # Shared fixtures (temp_dir, temp_file)
│   ├── test_main.py               # Tests for entry point & path resolution
│   ├── test_model.py              # Tests for Model (YAML loading, chat API calls)
│   ├── test_agent.py              # Tests for Agent (YAML loading, agent_turn, chat_loop)
│   └── test_tools.py              # Tests for tools (allowlist, sensitive detection, bash, read_file)
├── requirements.txt
├── README.md
└── AGENTS.md
```

## Components

### 1. Entry Point (`src/main.py`)
Parses CLI arguments (`--model`, `--agent`), loads the Model and Agent from YAML config files, registers the model in a lookup table, and starts the interactive chat loop. It also resolves relative paths against the project root.

### 2. Model (`src/model.py`)
A `Model` dataclass that encapsulates an LLM provider configuration:
- **YAML-loadable** via `Model.from_yaml(path)` — reads `name`, `base_url`, `model_id`, `api_key_env`, `temperature`, `max_tokens`, and optional `headers`.
- **Chat completion** via `model.chat(messages, tools)` — sends requests to the LLM's `/chat/completions` endpoint and returns `(content, tool_calls)`.

### 3. Agent (`src/agent.py`)
An `Agent` dataclass that orchestrates the conversation:
- **YAML-loadable** via `Agent.from_yaml(path, model_registry)` — reads `name`, `model`, `system_prompt` (or `system_prompt_file`), `max_turns`, and `tools`.
- **Agent loop** — `agent_turn(messages, user_message)` appends the user message, calls the model, executes any tool calls, and feeds results back until the model produces a final response or the turn limit is reached.
- **Interactive chat** — `chat_loop()` provides a stdin/stdout REPL.

### 4. Tools (`src/tools.py`)
Defines the tool registry (`TOOL_REGISTRY`) with two tools:
- **`bash`** — Executes shell commands with an allowlist of safe utilities (`ls`, `grep`, `cat`, etc.). Commands outside the list require explicit user confirmation. Has a 120-second timeout.
- **`read_file`** — Reads file contents. Blocks sensitive files (`.env`, keys, credentials, secrets, config YAMLs, etc.) and directories (`.git`, `.ssh`, `node_modules`, etc.).

Each tool entry provides both an LLM function schema and a Python handler function.

### 5. Tests (`tests/`)
Comprehensive test suite covering all modules with **98 tests** across 4 files:

| Test file | Coverage |
|-----------|----------|
| `test_tools.py` | `_is_allowed`, `_is_sensitive`, `_check_bash_permission`, `read_file`, `run_bash`, `get_tool_schemas`, `call_tool`, `TOOL_REGISTRY` structure |
| `test_model.py` | `Model.from_yaml` (all parameters, env vars, headers, edge cases), `Model.chat` (payload construction, tool calls, auth headers, errors) |
| `test_agent.py` | `Agent.from_yaml` (model resolution — registry/path/inline, system prompt — literal/file/template, tools, validation), `agent_turn` (simple response, tool calls, max turns), `chat_loop` (quit/exit/EOF/KeyboardInterrupt, system prompt, empty input) |
| `test_main.py` | `resolve_path`, `main` (missing configs, successful run, default paths, model registry wiring) |

Run tests with:
```bash
pytest tests/ -v
```

### 6. Configuration (`configs/`)
YAML files that drive the entire framework without code changes:
- **Model configs** (`configs/models/`) — Define LLM providers (base URL, model ID, API key env var, temperature, etc.).
- **Agent configs** (`configs/agents/`) — Tie together a model, system prompt, and tool set.

### 7. Prompts (`prompts/`)
Contains the system prompt template (`system_prompt.txt`) that defines the agent's behavior, workflow, and constraints. The `{cwd}` placeholder is substituted at load time with the agent's working directory.

## Data Flow

```
User input
  → main.py (CLI parsing, config loading)
    → Agent.chat_loop()
      → Agent.agent_turn(messages, user_input)
        → Model.chat(messages, tools)
        → (if tool_calls) tools.call_tool(name, args)
        → loop until final response
```

## Adding New Components

- **New tool** — Define the schema + handler in `src/tools.py` and add it to `TOOL_REGISTRY`. Then reference it in an agent YAML's `tools` list.
- **New model** — Add a YAML file in `configs/models/` and reference it from an agent config.
- **New agent** — Add a YAML file in `configs/agents/` with a model reference, system prompt, and tool list.
- **New tests** — Add test files under `tests/` following the existing patterns (one test file per source module, using pytest fixtures from `conftest.py`).

## Maintenance Rules

When making changes to the codebase, always update the following as needed:

1. **Tests (`tests/`)** — Any new feature, bug fix, or behavioral change must be covered by tests. Add new test cases in the corresponding test file (`test_tools.py`, `test_model.py`, `test_agent.py`, `test_main.py`) or create a new test file for new modules. Run `pytest tests/ -v` to verify all tests pass before committing.

2. **Documentation (`*.md`)** — Both `README.md` and `AGENTS.md` must stay in sync with the code:
   - Update the **directory tree** if files are added, removed, or renamed.
   - Update the **component descriptions** if behavior, parameters, or interfaces change.
   - Update the **test coverage table** if the test suite changes significantly.
   - Update the **configuration reference** if YAML keys are added, removed, or changed.

3. **Requirements (`requirements.txt`)** — If new dependencies are introduced, add them to `requirements.txt`.
