# Smart Agent

A modular, configurable AI agent framework that integrates with Large Language Models (LLMs) and external tools such as bash and file reading. The agent is driven entirely by YAML configuration files, making it easy to swap models, adjust tool sets, and customize behavior without modifying code.

## 📂 Structure

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
│   ├── __init__.py
│   ├── main.py                    # Entry point — argument parsing & orchestration
│   ├── model.py                   # Model class — LLM configuration & chat completion
│   ├── agent.py                   # Agent class — conversation loop & tool orchestration
│   └── tools.py                   # Tool registry — bash & read_file implementations
├── requirements.txt
└── README.md
```

### Core Modules

| File | Purpose |
|------|---------|
| `src/main.py` | Entry point. Parses CLI arguments, loads model and agent from YAML, starts the interactive chat loop. |
| `src/model.py` | `Model` dataclass — encapsulates LLM provider settings (base URL, model ID, API key, temperature, etc.) and handles `/chat/completions` requests. Can be instantiated from a YAML file. |
| `src/agent.py` | `Agent` dataclass — holds the system prompt, equipped tools, and max-turn limit. Runs the agent loop: sends user messages to the model, invokes tool calls, and returns results. Can be instantiated from a YAML file. |
| `src/tools.py` | Tool registry. Defines two tools — **`bash`** (safe shell execution with an allowlist and user confirmation) and **`read_file`** (file reading with sensitive-file blocking). Each tool provides an LLM function schema and a handler. |

## 💡 How It Works

1. **Configuration** — Model and agent settings live in YAML files under `configs/`. The model config specifies the LLM provider, API key (via env var), and parameters. The agent config ties together a model, a system prompt, and a list of tools.

2. **Agent Loop** — The user types a task. The agent sends it (with conversation history and system prompt) to the LLM. If the LLM responds with tool calls, the agent executes them (e.g., running `bash` or `read_file`) and feeds the results back into the conversation. This repeats until the LLM produces a final text response or the turn limit is reached.

3. **Safety** — The `bash` tool restricts commands to an allowlist of safe utilities (e.g., `ls`, `grep`, `cat`). Any command outside the list prompts the user for explicit confirmation. The `read_file` tool blocks access to sensitive files (`.env`, keys, credentials, etc.).

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

Run with default configs:

```bash
python src/main.py
```

Or specify custom configs:

```bash
python src/main.py --model configs/models/deepseek.yaml --agent configs/agents/coding_agent.yaml
```

Once started, the agent enters an interactive chat loop. Type your task and press Enter. Type `exit` or `quit` to end the session.

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

## 🔧 Available Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (allowlist-based, with user confirmation for untrusted commands) |
| `read_file` | Read file contents (blocked for sensitive files like `.env`, keys, secrets) |

To add new tools, define them in `src/tools.py` (schema + handler) and register them in `TOOL_REGISTRY`.
