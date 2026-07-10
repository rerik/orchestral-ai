# Orchestral AI - Smart CLI Agent

A modular, configurable AI agent framework that integrates with Large Language Models (LLMs) and external tools such as bash and file reading. The agent is driven entirely by YAML configuration files, making it easy to swap models, adjust tool sets, and customize behavior without modifying code.

Supports both **single-agent** and **multi-agent team** modes — the team mode orchestrates a host agent with specialized member agents via automatic delegation tools.

## 📂 Structure

```
orchestral-ai/
├── src/
│   ├── __init__.py
│   ├── main.py                    # Entry point — CLI parsing, team vs single mode
│   ├── model.py                   # Model class — LLM configuration & chat completion
│   ├── agent.py                   # Agent class — conversation loop & tool orchestration
│   ├── team.py                    # Team class — multi-agent orchestration
│   ├── tools.py                   # Tool registry — bash, read_file, web_search, edit_file
│   ├── chat_manager.py            # Chat persistence — save, list, resume chats
│   ├── input_handler.py           # Terminal input helpers — readline & history
│   ├── configs/
│   │   ├── agents/
│   │   │   ├── coding_agent.yaml          # Agent config (model, tools, system prompt)
│   │   │   ├── coding_agent_low.yaml      # Cheaper, faster model for simple coding tasks
│   │   │   ├── coding_agent_high.yaml     # More capable model for complex coding tasks
│   │   │   ├── host_agent.yaml            # Host agent config (team orchestrator)
│   │   │   └── research_agent.yaml        # Research agent config (analysis & explanation)
│   │   ├── models/
│   │   │   ├── deepseek.yaml          # Model config (API endpoint, params)
│   │   │   └── deepseek-v4-flash.yaml # Cheaper, faster model config
│   │   └── team.yaml                  # Team config (host + member agents)
│   └── prompts/
│       ├── coding_system_prompt.txt   # System prompt for coding agents
│       ├── host_system_prompt.txt     # System prompt for the host agent
│       ├── research_system_prompt.txt # System prompt for the research agent
│       └── system_prompt.txt          # System prompt template (single agent)
├── examples/                       # Reference configs — copy into ./.orchestral-ai/ or ~/.orchestral-ai/ to customize
│   ├── configs/
│   │   ├── agents/                 # All agent YAML configs
│   │   ├── models/                 # All model YAML configs
│   │   └── team.yaml
│   └── prompts/                    # All system prompt templates
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Shared fixtures (temp_dir, temp_file)
│   ├── test_main.py               # Tests for entry point & path resolution
│   ├── test_model.py              # Tests for Model (YAML loading, chat API calls)
│   ├── test_agent.py              # Tests for Agent (YAML loading, agent_turn, chat_loop)
│   ├── test_team.py               # Tests for Team (config loading, delegation, chat loop)
│   └── test_tools.py              # Tests for tools (allowlist, sensitive detection, bash, read_file)
├── pyproject.toml                 # Package metadata & build config (setuptools)
├── install.sh                     # One-command installer (curl | sh)
├── requirements.txt
├── LICENSE
└── README.md
```

### Core Modules

| File | Purpose |
|------|---------|
| `src/main.py` | Entry point. Parses CLI arguments, supports two modes: **single-agent mode** (default) for single-agent chat, and **team mode** (`--team` flag) for multi-agent orchestration. Resolves config paths by searching `.orchestral-ai/` (local → user-global → package fallback). Loads configs and starts the appropriate loop. |
| `src/model.py` | `Model` dataclass — encapsulates LLM provider settings (base URL, model ID, API key, temperature, etc.) and handles `/chat/completions` requests. Can be instantiated from a YAML file. |
| `src/agent.py` | `Agent` dataclass — holds the system prompt, equipped tools, and max-turn limit. Runs the agent loop: sends user messages to the model, invokes tool calls, and returns results. Can be instantiated from a YAML file. |
| `src/team.py` | Team orchestration — loads team config, creates host + member agents, injects delegation tools into the host, and runs the multi-agent chat loop. The host analyzes tasks, delegates subtasks to members, and synthesizes results. |
| `src/tools.py` | Tool registry. Defines four tools — **`bash`** (safe shell execution with an allowlist and user confirmation), **`read_file`** (file reading with sensitive-file blocking), **`web_search`** (DuckDuckGo web search), and **`edit_file`** (exact-string find-and-replace with diff preview and confirmation). Each tool provides an LLM function schema and a handler. |
| `src/chat_manager.py` | Chat persistence manager. Stores chat sessions as JSON files in `.orchestral-ai/` in the working directory. Supports creating, listing, loading, and deleting chats with auto-titling from the first user message. |
| `src/input_handler.py` | Terminal input helpers for interactive mode. Provides **`setup_readline`** for persistent command history across sessions and **`get_input`** for safe input with EOF/KeyboardInterrupt handling. |

### Test Suite

| File | Coverage |
|------|----------|
| `tests/test_tools.py` | `_is_allowed`, `_is_sensitive`, `_check_bash_permission`, `read_file`, `run_bash`, `get_tool_schemas`, `call_tool`, `TOOL_REGISTRY` structure, `web_search`, `edit_file` |
| `tests/test_model.py` | `Model.from_yaml` (all parameters, env vars, headers, edge cases), `Model.chat` (payload construction, tool calls, auth headers, errors) |
| `tests/test_agent.py` | `Agent.from_yaml` (model resolution — registry/path/inline, system prompt — literal/file/template, tools, validation), `agent_turn` (simple response, tool calls, max turns), `chat_loop` (quit/exit/EOF/KeyboardInterrupt, system prompt, empty input) |
| `tests/test_team.py` | `Team.from_yaml` (team config loading, member descriptions, model registry, validation), delegation tools, host turn with delegation, chat loop |
| `tests/test_main.py` | `resolve_path`, `find_config_path`, `get_config_search_dirs`, `main` (missing configs, successful run, default paths, model registry wiring) |

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

### Config Search Paths

Config files (models, agents, team) are resolved by searching three locations in
priority order:

1. **`./.orchestral-ai/`** — Project-local overrides (highest priority)
2. **`~/.orchestral-ai/`** — User-global overrides
3. **Package directory** — Built-in defaults (fallback)

This means you can customize any config without modifying the installed package.
For example, to override the default model with your own settings:

```bash
mkdir -p ./.orchestral-ai/configs/models
cp examples/configs/models/deepseek.yaml ./.orchestral-ai/configs/models/
# Edit ./.orchestral-ai/configs/models/deepseek.yaml as needed
```

The `examples/` directory contains reference copies of all built-in configs and
prompts — use them as starting points for your custom overrides.

### Chat Management

All chat sessions are automatically persisted to a `.orchestral-ai/` directory
created in the working directory where the agent is launched:

```
.orchestral-ai/
├── index.json              # index of all chats with metadata (ID, title, timestamps, mode, message count)
└── chats/
    ├── 86b73364ec4b.json   # individual chat files with full message history
    └── ...
```

**Features:**
- **Automatic saving** — Messages are persisted after every agent turn and on exit.
- **Auto-titling** — Each chat is titled automatically from the first user message (truncated to 60 characters).
- **Resume** — Reload any previous chat and continue exactly where you left off.
- **List** — View all saved chats with IDs, titles, modes, and message counts.
- **Mode tracking** — Chats remember whether they were created in team or single-agent mode.

**CLI flags:**

```bash
# List all saved chats with IDs, titles, and metadata
orchestral-cli --chats

# Resume a specific chat by its ID
orchestral-cli --chat 86b73364ec4b
```

**In-chat commands:**

While in an interactive session, you can type `/chats` at the prompt to list all
saved chats without leaving the conversation.

Running with no flags starts a **new chat** in single-agent mode (the default).

## 📦 Installation

### Quick install (Linux & macOS)

```bash
curl -LsSf https://raw.githubusercontent.com/rerik/orchestral-ai/main/install.sh | sh
```

This single command installs `orchestral-cli` and makes it available on your PATH.  
If the app is already installed, it upgrades it to the latest version automatically.

### Install from local repo

```bash
# From a cloned copy of the repository
./install.sh

# Or with pip directly
pip install .
```

### Install from GitHub

```bash
pip install git+https://github.com/rerik/orchestral-ai.git
```

To upgrade an existing installation, add `--upgrade`:

```bash
pip install --upgrade git+https://github.com/rerik/orchestral-ai.git
```

### Editable / development install

```bash
pip install -e .
```

This links the local source directory so code changes take effect immediately  
without reinstalling.  Use this when hacking on the agent itself.

---

## 🚀 How to Run

### Prerequisites

- Python 3.10+
- A DeepSeek API key (or any OpenAI-compatible LLM endpoint)

### Environment Variables

Create a `.env` file in the project root:

```bash
echo 'DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' > .env
```

The model config (`configs/models/deepseek.yaml`) reads the key from the `DEEPSEEK_API_KEY` environment variable via the `api_key_env` field.

### Execution

**Starting a new chat:**

```bash
# Single-agent mode (default) — starts a new chat
orchestral-cli

# Single-agent mode with custom agent — starts a new chat
orchestral-cli --agent configs/agents/coding_agent.yaml

# Team mode — starts a new chat with multi-agent orchestration
orchestral-cli --team configs/team.yaml
```

**Managing saved chats:**

```bash
# List all saved chats (shows IDs, titles, modes, message counts, timestamps)
orchestral-cli --chats

# Resume a specific chat by ID
orchestral-cli --chat 86b73364ec4b
```

**Inside a chat session:**
- Type `/chats` to list all saved chats without leaving the conversation.
- Type `exit` or `quit` to end the session (messages are saved automatically).

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
cost_coefficient: 2.0          # Relative cost multiplier for delegation decisions
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
  - web_search
```

You can also specify `system_prompt` inline (as a string) instead of `system_prompt_file`. If both are given, `system_prompt` takes precedence.

### Team YAML (`configs/team.yaml`)

```yaml
name: smart-team                     # Team name

host:                                # Host agent (orchestrator)
  agent: configs/agents/host_agent.yaml

agents:                              # Member agents (specialists)
  - name: coder_low                  # Agent name (used in delegation tool)
    agent: configs/agents/coding_agent_low.yaml
    description: >                   # Description injected into host prompt
      Specialized in simple, straightforward programming tasks: basic
      scripts, simple debugging, formatting, minor refactoring. Powered
      by a fast, cost-effective model. Use this for routine coding work.

  - name: coder_high
    agent: configs/agents/coding_agent_high.yaml
    description: >
      Specialized in complex programming tasks: architecture design,
      hard debugging, complex refactoring, performance optimization,
      security reviews. Powered by a more capable model. Use this for
      challenging coding work.

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
| `web_search` | Search the web using DuckDuckGo for current information, documentation, and news |
| `edit_file` | Find-and-replace exact string in a file, with diff preview and user confirmation |

To add new tools, define them in `src/tools.py` (schema + handler) and register them in `TOOL_REGISTRY`.
