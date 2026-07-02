# Smart Agent

A modular, configurable AI agent framework that integrates with Large Language Models (LLMs) and external tools such as bash and file reading. The agent is driven entirely by YAML configuration files, making it easy to swap models, adjust tool sets, and customize behavior without modifying code.

Supports both **single-agent** and **multi-agent team** modes — the team mode orchestrates a host agent with specialized member agents via automatic delegation tools.

## 📂 Structure

```
smart_agent/
├── configs/
│   ├── agents/
│   │   ├── coding_agent.yaml      # Agent config (model, tools, system prompt)
│   │   ├── host_agent.yaml        # Host agent config (team orchestrator)
│   │   └── research_agent.yaml    # Research agent config (analysis & explanation)
│   ├── models/
│   │   └── deepseek.yaml          # Model config (API endpoint, params)
│   └── team.yaml                  # Team config (host + member agents)
├── prompts/
│   ├── host_system_prompt.txt     # System prompt for the host agent
│   ├── research_system_prompt.txt # System prompt for the research agent
│   └── system_prompt.txt          # System prompt template (single agent)
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entry point — CLI parsing, team vs single mode
│   ├── model.py                   # Model class — LLM configuration & chat completion
│   ├── agent.py                   # Agent class — conversation loop & tool orchestration
│   ├── team.py                    # Team class — multi-agent orchestration
│   └── tools.py                   # Tool registry — bash & read_file implementations
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures (temp_dir, temp_file)
│   ├── test_main.py               # Tests for entry point & path resolution
│   ├── test_model.py              # Tests for Model (YAML loading, chat API calls)
│   ├── test_agent.py              # Tests for Agent (YAML loading, agent_turn, chat_loop)
│   ├── test_team.py               # Tests for Team (config loading, delegation, chat loop)
│   └── test_tools.py              # Tests for tools (allowlist, sensitive detection, bash, read_file)
├── requirements.txt
└── README.md
```

### Core Modules

| File | Purpose |
|------|---------|
| `src/main.py` | Entry point. Parses CLI arguments, supports two modes: **team mode** (`--team` flag or default) for multi-agent orchestration, and **single mode** (`--agent` flag) for single-agent chat. Loads configs and starts the appropriate loop. |
| `src/model.py` | `Model` dataclass — encapsulates LLM provider settings (base URL, model ID, API key, temperature, etc.) and handles `/chat/completions` requests. Can be instantiated from a YAML file. |
| `src/agent.py` | `Agent` dataclass — holds the system prompt, equipped tools, and max-turn limit. Runs the agent loop: sends user messages to the model, invokes tool calls, and returns results. Can be instantiated from a YAML file. |
| `src/team.py` | Team orchestration — loads team config, creates host + member agents, injects delegation tools into the host, and runs the multi-agent chat loop. The host analyzes tasks, delegates subtasks to members, and synthesizes results. |
| `src/tools.py` | Tool registry. Defines two tools — **`bash`** (safe shell execution with an allowlist and user confirmation) and **`read_file`** (file reading with sensitive-file blocking). Each tool provides an LLM function schema and a handler. |

### Test Suite

| File | Coverage |
|------|----------|
| `tests/test_tools.py` | `_is_allowed`, `_is_sensitive`, `_check_bash_permission`, `read_file`, `run_bash`, `get_tool_schemas`, `call_tool`, `TOOL_REGISTRY` structure |
| `tests/test_model.py` | `Model.from_yaml` (all parameters, env vars, headers, edge cases), `Model.chat` (payload construction, tool calls, auth headers, errors) |
| `tests/test_agent.py` | `Agent.from_yaml` (model resolution — registry/path/inline, system prompt — literal/file/template, tools, validation), `agent_turn` (simple response, tool calls, max turns), `chat_loop` (quit/exit/EOF/KeyboardInterrupt, system prompt, empty input) |
| `tests/test_team.py` | `Team.from_yaml` (team config loading, member descriptions, model registry, validation), delegation tools, host turn with delegation, chat loop |
| `tests/test_main.py` | `resolve_path`, `main` (missing configs, successful run, default paths, model registry wiring) |

## 💡 How It Works

### Single-Agent Mode

1. **Configuration** — Model and agent settings live in YAML files under `configs/`. The model config specifies the LLM provider, API key (via env var), and parameters. The agent config ties together a model, a system prompt, and a list of tools.

2. **Agent Loop** — The user types a task. The agent sends it (with conversation history and system prompt) to the LLM. If the LLM responds with tool calls, the agent executes them (e.g., running `bash` or `read_file`) and feeds the results back into the conversation. This repeats until the LLM produces a final text response or the turn limit is reached.

3. **Safety** — The `bash` tool restricts commands to an allowlist of safe utilities (e.g., `ls`, `grep`, `cat`). Any command outside the list prompts the user for explicit confirmation. The `read_file` tool blocks access to sensitive files (`.env`, keys, credentials, etc.).

### Team Mode

1. **Team Configuration** — A team YAML file (`configs/team.yaml`) defines a host agent and a list of member agents, each with a name, agent config path, and description of its expertise.

2. **Host Orchestration** — The host agent receives the user's task and analyzes it. It decides whether to handle the task directly or decompose it into subtasks for delegation.

3. **Delegation** — Each member agent is exposed to the host as a delegation tool (`delegate_to_coder`, `delegate_to_researcher`, etc.). The host calls these tools with clear, self-contained subtask descriptions. Member agents work independently and return their results.

4. **Synthesis** — The host collects all delegated results, synthesizes them into a coherent final answer, and presents it to the user. If the team has no member agents, the host handles everything itself.

## 🚀 How to Run

### Prerequisites

- Python 3.9+
- A DeepSeek API key (or any OpenAI-compatible LLM endpoint)

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```bash
echo 'DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' > .env
```

The model config (`configs/models/deepseek.yaml`) reads the key from the `DEEPSEEK_API_KEY` environment variable via the `api_key_env` field.

### Execution

**Team mode (default):**

```bash
# Team mode (default)
python src/main.py

# Team mode with custom config
python src/main.py --team configs/team.yaml
```

**Single-agent mode:**

```bash
# Single-agent mode
python src/main.py --agent configs/agents/coding_agent.yaml

# Single-agent mode with custom model
python src/main.py --model configs/models/deepseek.yaml --agent configs/agents/coding_agent.yaml
```

Once started, the agent enters an interactive chat loop. Type your task and press Enter. Type `exit` or `quit` to end the session.

### Running Tests

```bash
pytest tests/ -v
```

All tests should pass. The test suite uses `pytest` with fixtures defined in `tests/conftest.py` (temporary directories, file helpers). External dependencies (API calls, user input, shell commands) are mocked via `unittest.mock`.

## ⚙️ Configuration Reference

### Model YAML (`configs/models/deepseek.yaml`)

```yaml
name: deepseek-v4-pro          # Human-readable name (used as registry key)
base_url: https://api.deepseek.com   # LLM API base URL
model_id: deepseek-v4-pro      # Model identifier sent to the API
api_key_env: DEEPSEEK_API_KEY  # Env var holding the API key
temperature: 0.1               # Response randomness (0.0 – 1.0)
max_tokens: 4096               # Max output tokens
headers:                       # Extra HTTP headers
  Content-Type: application/json
```

### Agent YAML (`configs/agents/coding_agent.yaml`)

```yaml
name: coding-agent                     # Agent name
model: deepseek-v4-pro                 # Model name (looked up in registry) or path to model YAML
system_prompt_file: ../../prompts/system_prompt.txt  # Path to system prompt (relative to this YAML file)
max_turns: 1000                        # Max LLM calls per user turn
tools:                                 # Tool names to equip
  - bash
  - read_file
```

You can also specify `system_prompt` inline (as a string) instead of `system_prompt_file`. If both are given, `system_prompt` takes precedence.

### Team YAML (`configs/team.yaml`)

```yaml
name: smart-team                     # Team name

host:                                # Host agent (orchestrator)
  agent: configs/agents/host_agent.yaml

agents:                              # Member agents (specialists)
  - name: coder                      # Agent name (used in delegation tool)
    agent: configs/agents/coding_agent.yaml
    description: >                   # Description injected into host prompt
      Specialized in programming tasks: writing code, debugging,
      refactoring, running shell commands, reading and writing files.

  - name: researcher
    agent: configs/agents/research_agent.yaml
    description: >
      Specialized in research, analysis, and explanation: summarizing
      information, answering knowledge questions, analyzing data,
      and explaining complex topics.
```

The host agent is always present. Member agents are optional — if none are defined, the host handles all tasks itself. Each member agent's description is injected into the host's system prompt so the host knows when to delegate.

## 🔧 Available Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (allowlist-based, with user confirmation for untrusted commands) |
| `read_file` | Read file contents (blocked for sensitive files like `.env`, keys, secrets) |

To add new tools, define them in `src/tools.py` (schema + handler) and register them in `TOOL_REGISTRY`.
