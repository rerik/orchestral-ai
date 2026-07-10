# Project Agents Overview

This document outlines the structure and components of the Smart Agent framework.

## Directory Analysis

```
smart_agent/
├── configs/
│   ├── agents/
│   │   ├── coding_agent.yaml          # Agent config (model, tools, system prompt)
│   │   ├── coding_agent_low.yaml      # Cheaper, faster model for simple coding tasks
│   │   ├── coding_agent_high.yaml     # More capable model for complex coding tasks
│   │   ├── host_agent.yaml            # Host agent config (team orchestrator)
│   │   └── research_agent.yaml        # Research agent config (analysis & explanation)
│   ├── models/
│   │   ├── deepseek.yaml          # Model config (API endpoint, params)
│   │   └── deepseek-v4-flash.yaml # Cheaper, faster model config
│   └── team.yaml                  # Team config (host + member agents)
├── prompts/
│   ├── coding_system_prompt.txt   # System prompt for coding agents
│   ├── host_system_prompt.txt     # System prompt for the host agent
│   ├── research_system_prompt.txt # System prompt for the research agent
│   └── system_prompt.txt          # System prompt template (single agent)
├── examples/                      # Reference configs — copy into ./.orchestral-ai/ or ~/.orchestral-ai/ to customize
│   ├── configs/
│   │   ├── agents/                # All agent YAML configs
│   │   ├── models/                # All model YAML configs
│   │   └── team.yaml
│   └── prompts/                   # All system prompt templates
├── src/
│   ├── __init__.py                # Package marker
│   ├── main.py                    # Entry point — CLI parsing, team vs single mode
│   ├── model.py                   # Model class — LLM config & chat completion
│   ├── agent.py                   # Agent class — conversation loop & tool orchestration
│   ├── team.py                    # Team class — multi-agent orchestration
│   ├── tools.py                   # Tool registry — bash & read_file implementations
│   └── input_handler.py           # Terminal input helpers — readline & history
├── tests/
│   ├── __init__.py                # Package marker
│   ├── conftest.py                # Shared fixtures (temp_dir, temp_file)
│   ├── test_main.py               # Tests for entry point & path resolution
│   ├── test_model.py              # Tests for Model (YAML loading, chat API calls)
│   ├── test_agent.py              # Tests for Agent (YAML loading, agent_turn, chat_loop)
│   ├── test_team.py               # Tests for Team (config loading, delegation, chat loop)
│   └── test_tools.py              # Tests for tools (allowlist, sensitive detection, bash, read_file)
├── requirements.txt
├── LICENSE
├── README.md
└── AGENTS.md
```

## Components

### 1. Entry Point (`src/main.py`)
Parses CLI arguments (`--team`, `--model`, `--agent`), supports two modes:
- **Single-agent mode** (default): Loads a single Model and Agent from YAML config files, registers the model in a lookup table, and starts the interactive chat loop.
- **Team mode** (`--team` flag): Loads a team config and runs multi-agent orchestration via the `Team` class.

Config files are resolved by searching three locations in priority order: `./.orchestral-ai/` (project-local), `~/.orchestral-ai/` (user-global), then the package directory (built-in fallback). This lets you customize configs without modifying the installed package.

### 2. Model (`src/model.py`)
A `Model` dataclass that encapsulates an LLM provider configuration:
- **YAML-loadable** via `Model.from_yaml(path)` — reads `name`, `base_url`, `model_id`, `api_key_env`, `temperature`, `max_tokens`, and optional `headers`.
- **Chat completion** via `model.chat(messages, tools)` — sends requests to the LLM's `/chat/completions` endpoint and returns `(content, tool_calls)`.

### 3. Agent (`src/agent.py`)
An `Agent` dataclass that orchestrates the conversation:
- **YAML-loadable** via `Agent.from_yaml(path, model_registry)` — reads `name`, `model`, `system_prompt` (or `system_prompt_file`), `max_turns`, and `tools`.
- **Agent loop** — `agent_turn(messages, user_message)` appends the user message, calls the model, executes any tool calls, and feeds results back until the model produces a final response or the turn limit is reached.
- **Interactive chat** — `chat_loop()` provides a stdin/stdout REPL.

### 4. Team (`src/team.py`)
A `Team` dataclass that orchestrates multi-agent collaboration:
- **Team config** — Loaded from a YAML file defining a host agent and a list of member agents, each with a name, agent config path, and description.
- **`from_yaml` factory** — Searches all config directories (local → user-global → package fallback) for model configs, auto-loads found models into a registry, resolves agent paths via the same search order, creates the host and all member agents, and injects member descriptions into the host's system prompt.
- **Delegation tools** — Each member agent is exposed to the host as a dynamically-generated tool (`delegate_to_<name>`). The tool schema includes the member's description so the LLM knows when to use it.
- **Host turn** — `_host_turn(messages, user_message)` extends the single-agent turn by combining the host's own tools with delegation tools. When a delegation tool is called, `_handle_delegation` runs the member agent on the subtask and returns its result.
- **Interactive chat** — `chat_loop()` provides a REPL where the host orchestrates the team. If no member agents exist, the host handles everything itself.

### 5. Config Resolution (`src/main.py` — `find_config_path`, `get_config_search_dirs`)
Config files (models, agents, team) are resolved by searching three locations in priority order:
1. **`./.orchestral-ai/`** — Project-local overrides (highest priority)
2. **`~/.orchestral-ai/`** — User-global overrides  
3. **Package directory** — Built-in defaults (fallback)

The `find_config_path(relative_path)` function walks these directories in order and returns the first existing match. Both `main.py` (for single-agent mode) and `team.py` (for team mode) use this to resolve configs. The `examples/` directory contains reference copies of all built-in configs — copy them into your `.orchestral-ai/` to customize.

### 6. Tools (`src/tools.py`)
Defines the tool registry (`TOOL_REGISTRY`) with four tools:
- **`bash`** — Executes shell commands with an allowlist of safe utilities (`ls`, `grep`, `cat`, etc.). Commands outside the list require explicit user confirmation. Has a 120-second timeout.
- **`read_file`** — Reads file contents. Blocks sensitive files (`.env`, keys, credentials, secrets, config YAMLs, etc.) and directories (`.git`, `.ssh`, `node_modules`, etc.).
- **`web_search`** — Searches the web using DuckDuckGo. Returns formatted results with titles, URLs, and snippets.
- **`edit_file`** — Edits files by exact-string find-and-replace. Shows a unified diff and asks for user confirmation. Rejects edits when `old_string` appears multiple times.

Each tool entry provides both an LLM function schema and a Python handler function.

Additional utilities in `tools.py`:
- **`safe_json_loads(raw)`** — Parses potentially malformed JSON from LLM outputs. Attempts multiple recovery strategies (unterminated strings, unclosed braces, trailing commas).
- **`configure_risk_model(model)`** — Sets up an optional AI model for intelligent bash command risk assessment. Falls back to rule-based assessment when `None` or on API errors.
- **`configure_summary_model(model)`** — Sets up an optional AI model for bash command summarization. Falls back to rule-based summarization when `None` or on API errors.

### 7. Input Handler (`src/input_handler.py`)
Provides enhanced terminal input functionality used by both the Agent and Team interactive loops:
- **`setup_readline(history_file)`** — Configures GNU readline with persistent history (~/.smart_agent_history), saving up to 1000 entries across sessions. Gracefully degrades if readline is unavailable.
- **`get_input(prompt)`** — Thin wrapper around `input()` that strips input and handles EOF/KeyboardInterrupt by cleanly exiting.

### 8. Tests (`tests/`)
Comprehensive test suite covering all modules across 5 files:

| Test file | Coverage |
|-----------|----------|
| `test_tools.py` | `_is_allowed`, `_is_sensitive`, `_check_bash_permission`, `read_file`, `run_bash`, `get_tool_schemas`, `call_tool`, `TOOL_REGISTRY` structure, `web_search`, `edit_file` |
| `test_model.py` | `Model.from_yaml` (all parameters, env vars, headers, edge cases), `Model.chat` (payload construction, tool calls, auth headers, errors) |
| `test_agent.py` | `Agent.from_yaml` (model resolution — registry/path/inline, system prompt — literal/file/template, tools, validation), `agent_turn` (simple response, tool calls, max turns), `chat_loop` (quit/exit/EOF/KeyboardInterrupt, system prompt, empty input) |
| `test_team.py` | `Team.from_yaml` (team config loading, member descriptions, model registry, validation), delegation tools, host turn with delegation, chat loop |
| `test_main.py` | `resolve_path`, `find_config_path`, `get_config_search_dirs`, `main` (missing configs, successful run, default paths, model registry wiring) |

Run tests with:
```bash
pytest tests/ -v
```

### 9. Configuration (`configs/`)
YAML files that drive the entire framework without code changes. Config files are searched in three locations: `./.orchestral-ai/` (project-local), `~/.orchestral-ai/` (user-global), then the package directory (built-in fallback). See **Section 5** for details.
- **Model configs** (`configs/models/`) — Define LLM providers (base URL, model ID, API key env var, temperature, cost coefficient, etc.).
- **Agent configs** (`configs/agents/`) — Tie together a model, system prompt, and tool set.
- **Team config** (`configs/team.yaml`) — Defines a team with a host agent and member agents, each with a name, agent path, and description.

### 10. Prompts (`prompts/`)
Contains system prompt templates that define agent behavior, workflow, and constraints:
- `system_prompt.txt` — General-purpose single-agent prompt.
- `coding_system_prompt.txt` — Coding agent prompt covering tool usage, workflow, and file writing best practices.
- `host_system_prompt.txt` — Host agent prompt covering task analysis, decomposition, delegation, and synthesis.
- `research_system_prompt.txt` — Research agent prompt for handling analysis and explanation subtasks.

The `{cwd}` placeholder is substituted at load time with the agent's working directory.

## Data Flow

### Single-Agent Mode
```
User input
  → main.py (CLI parsing, detects mode, resolves config paths)
    → Agent.chat_loop()
      → Agent.agent_turn(messages, user_input)
        → Model.chat(messages, tools)
        → (if tool_calls) tools.call_tool(name, args)
        → loop until final response
```

### Team Mode
```
User input
  → main.py (CLI parsing, detects team vs single mode)
    → Team.chat_loop()
      → Team._host_turn(messages, user_input)
        → Host Model.chat(messages, tools + delegation tools)
        → (if delegation) Team._handle_delegation(agent_name, task)
          → Member Agent.agent_turn(...)
        → loop until host produces final response
```

## Adding New Components

- **New tool** — Define the schema + handler in `src/tools.py` and add it to `TOOL_REGISTRY`. Then reference it in an agent YAML's `tools` list.
- **New model** — Add a YAML file in `configs/models/` (or in `./.orchestral-ai/configs/models/` or `~/.orchestral-ai/configs/models/` for overrides) and reference it from an agent config.
- **New agent** — Add a YAML file in `configs/agents/` with a model reference, system prompt, and tool list.
- **New team member agent** — Add the agent YAML in `configs/agents/`, add a system prompt in `prompts/`, then add an entry in `configs/team.yaml` under `agents` with the agent's name, config path, and description.
- **New tests** — Add test files under `tests/` following the existing patterns (one test file per source module, using pytest fixtures from `conftest.py`).

## Maintenance Rules

When making changes to the codebase, always update the following as needed:

1. **Tests (`tests/`)** — Any new feature, bug fix, or behavioral change must be covered by tests. Add new test cases in the corresponding test file (`test_tools.py`, `test_model.py`, `test_agent.py`, `test_team.py`, `test_main.py`) or create a new test file for new modules. Run `pytest tests/ -v` to verify all tests pass before committing.

2. **Documentation (`*.md`)** — Both `README.md` and `AGENTS.md` must stay in sync with the code:
   - Update the **directory tree** if files are added, removed, or renamed.
   - Update the **component descriptions** if behavior, parameters, or interfaces change.
   - Update the **test coverage table** if the test suite changes significantly.
   - Update the **configuration reference** if YAML keys are added, removed, or changed.
   - Update **`examples/`** if config files or prompts are added, removed, or renamed.

3. **Requirements (`requirements.txt`)** — If new dependencies are introduced, add them to `requirements.txt`.
