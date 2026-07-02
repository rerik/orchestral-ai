import os
import subprocess
import re
import json
import sys
import shutil
import fnmatch

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------
#  Load environment variables from .env
# ---------------------------------------------------------

load_dotenv()


# ---------------------------------------------------------
#  BASH
# ---------------------------------------------------------


ALLOWED_CMD = [
    # --- File system navigation & inspection (read-only) ---
    "ls",
    "cd",
    "pwd",
    "cat",
    "head",
    "tail",
    "wc",
    "stat",
    "file",
    "du",
    "df",

    # --- Text search & processing (read-only) ---
    "grep",
    "sort",
    "uniq",
    "diff",
    "comm",
    "cut",
    "tr",
    "fmt",
    "pr",
    "fold",

    # --- Output / printing (safe: redirections are caught by delimiter splitting) ---
    "echo",
    "printf",

    # --- Command location ---
    "which",
    "type",
    "command",
    "hash",

    # --- Path manipulation (read-only) ---
    "basename",
    "dirname",
    "realpath",
    "readlink",

    # --- Low-risk file/directory creation ---
    # "mkdir",
    # "touch",
    # "ln",
]


def is_allowed(cmd: str) -> bool:
    for allowed in ALLOWED_CMD:
        if cmd.startswith(allowed):
            return True
    return False


def check_bash_permission(cmd: str) -> bool:
    delimiters = r'&&|\|\||>>|<<|\||;|&|>|<'
    cmd_parts = [part.strip() for part in re.split(delimiters, cmd) if part.strip()]
    if all(map(is_allowed, cmd_parts)):
        return True
    max_width = shutil.get_terminal_size().columns - 2
    question = f"Execute `{cmd}`? y/n\n"
    wrap = '# ' + '-' * min((len(question) - 2), max_width)
    expliscit_permission: str = input('\n' + wrap + '\n' + question + wrap + '\n')
    if expliscit_permission.lower() in ["y", "yes"]:
        return True
    return False


def run_bash(command: str) -> str:
    try:
        if check_bash_permission(command):
            command_result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
            out = command_result.stdout + (f"\nSTDERR:\n{command_result.stderr}" if command_result.stderr else "")
            return f"Exit code: {command_result.returncode}\n{out}"
        return "Error: not allowed by user"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"


# ---------------------------------------------------------
#  READ_FILE (secure file reader — blocks sensitive files)
# ---------------------------------------------------------


# Glob patterns for files that MUST NOT be read via this tool
SENSITIVE_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.env",
    "*secret*",
    "*password*",
    "*credential*",
    "*token*",
    "*apikey*",
    "*api_key*",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "*.pem",
    "*.key",
    "*.cert",
    "*.p12",
    "*.pfx",
    ".netrc",
    ".git-credentials",
    ".aws/credentials",
    "*.kubeconfig",
    "*.kube/config",
    ".npmrc",
    ".dockercfg",
    ".docker/config.json",
    "*.htpasswd",
    "*.htaccess",  # often contains DB credentials
    "config.yml",
    "config.yaml",
    "database.yml",
    "database.yaml",
    "secrets.yml",
    "secrets.yaml",
    "private*",
    "*.keystore",
    "*.jks",
]

# Also block by path segments containing well-known sensitive dirs
SENSITIVE_DIR_SEGMENTS = [
    ".git",
    ".ssh",
    ".gnupg",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
]


def _is_sensitive(filepath: str) -> bool:
    """Check if a file path matches any sensitive pattern."""
    # Normalise: resolve symlinks, get real absolute path
    try:
        real = os.path.realpath(filepath)
    except Exception:
        real = filepath

    # Get the filename (base name) and the full path
    basename = os.path.basename(real)
    full = real

    # Check against sensitive directory segments
    parts = full.split(os.sep)
    for seg in SENSITIVE_DIR_SEGMENTS:
        if seg in parts:
            return True

    # Check filename against glob patterns
    for pattern in SENSITIVE_FILE_PATTERNS:
        # Match against basename
        if fnmatch.fnmatch(basename, pattern):
            return True
        # Also match against the full path (for patterns like ".aws/credentials")
        if fnmatch.fnmatch(full, f"*{pattern}"):
            return True
        # Match with wildcard prefix
        if fnmatch.fnmatch(full, f"*/{pattern}"):
            return True

    return False


def read_file(filepath: str, max_length: int = 100000) -> str:
    """Read a file's contents. Blocks sensitive files (e.g. .env, secrets, keys)."""
    # Resolve the path relative to CWD if it's not absolute
    if not os.path.isabs(filepath):
        resolved = os.path.join(os.getcwd(), filepath)
    else:
        resolved = filepath

    # Normalise
    resolved = os.path.normpath(resolved)

    # Check if file exists
    if not os.path.exists(resolved):
        return f"Error: file not found: {filepath}"

    # Check if it's a directory
    if os.path.isdir(resolved):
        return f"Error: path is a directory, not a file: {filepath}"

    # Security check: block sensitive files
    if _is_sensitive(resolved):
        return f"Error: reading '{filepath}' is blocked — this file may contain sensitive data."

    # Security check: block files that are too large (protect against DoS / accidental huge files)
    try:
        size = os.path.getsize(resolved)
    except OSError as e:
        return f"Error: cannot determine file size: {e}"
    if size == 0:
        return "(file is empty)"
    if size > max_length:
        return f"Error: file is {size} bytes (max allowed: {max_length}). Use a tool like `head -n 100 <file>` via bash instead."

    # Read the file
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content
    except PermissionError:
        return f"Error: permission denied reading: {filepath}"
    except Exception as e:
        return f"Error: could not read file '{filepath}': {e}"


# ---------------------------------------------------------
#  TOOLS
# ---------------------------------------------------------


TOOLS = {
    "bash": run_bash,
    "read_file": read_file,
}


def call_tool(name: str, arguments: dict) -> str:
    func = TOOLS.get(name)
    if not func:
        return f"Error: unknown tool '{name}'"
    try:
        return func(**arguments)
    except Exception as e:
        return f"Error calling {name}: {e}"


# ---------------------------------------------------------
#  LLM
# ---------------------------------------------------------


# Load API key from environment (populated via .env by dotnet)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    print("ERROR: DEEPSEEK_API_KEY not found. Create a .env file in the project root with:")
    print('  DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')
    sys.exit(1)

LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-v4-flash"
LLM_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
}


LLM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a shell command and return stdout/stderr. For general shell operations like listing files, running commands, writing files via heredoc, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute."}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. This is the PREFERRED tool for getting file contents. Use this instead of 'cat', 'head', 'tail' etc. in bash. NOTE: Sensitive files (e.g. .env, secrets, keys, credentials) are blocked for security.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the file (absolute, or relative to current working directory)."
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Maximum number of bytes to read (default 100000).",
                        "default": 100000
                    }
                },
                "required": ["filepath"]
            }
        }
    }
]


# ---------------------------------------------------------
#  SYSTEM PROMPT (template with {cwd} placeholder)
# ---------------------------------------------------------


SYSTEM_PROMPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prompts", "system_prompt.txt")
with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
    SYSTEM_PROMPT_TEMPLATE = f.read().strip()

# Substitute the current working directory into the template
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(cwd=os.getcwd())


def call_llm(messages):
    payload = {
        "model": LLM_MODEL, 
        "messages": messages, 
        "tools": LLM_TOOLS, 
        "tool_choice": "auto",
        "temperature": 0.1, 
        "max_tokens": 4096
    }
    llm_http_response = requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=LLM_HEADERS)
    llm_http_response.raise_for_status()
    msg = llm_http_response.json()["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    tool_calls = msg.get("tool_calls") or []
    return content, tool_calls


# ---------------------------------------------------------
#  CHAT LOOP
# ---------------------------------------------------------


MAX_TURNS = 1000


def agent_turn(messages: list, user_message: str) -> list:
    """Append a user message and run the agent loop until no more tool calls.
    
    Returns the updated messages list.
    """
    messages.append({"role": "user", "content": user_message})
    
    for _ in range(1, MAX_TURNS + 1):
        content, tool_calls = call_llm(messages)
        
        if content:
            print(f"\n🤖 {content}")
        
        if not tool_calls:
            if not content:
                print("(no text output)")
            print()
            return messages
        
        assistant_msg = {"role": "assistant", "content": content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)
        
        prefix = "\n" if content else ""
        for tool_call in tool_calls:
            function = tool_call["function"]["name"]
            arguments = json.loads(tool_call["function"]["arguments"])
            tool_call_id = tool_call["id"]
            
            print(f"{prefix}🔧 Tool: {function}({json.dumps(arguments, ensure_ascii=False)})")
            result = call_tool(function, arguments)
            print(f"   → {result[:500]}{'...' if len(result)>500 else ''}")
            
            messages.append({
                "role": "tool", 
                "tool_call_id": tool_call_id, 
                "content": result
            })
    
    print(f"\n⚠️ Max turns ({MAX_TURNS}) reached. Stopping.")
    return messages


if __name__ == "__main__":
    print("🤖 Coding Agent — Chat mode")
    print("Type your task below. Type 'exit' or 'quit' to end the session.")
    print()
    
    # Initialise conversation history with the system prompt
    messages: list = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    
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
        
        messages = agent_turn(messages, user_input)
