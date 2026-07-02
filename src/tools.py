"""
Tool definitions: each tool has a name, an LLM function schema,
and a handler function.
"""

import os
import re
import subprocess
import shutil
import fnmatch


# ---------------------------------------------------------------------------
#  Tool: bash
# ---------------------------------------------------------------------------

ALLOWED_CMD = [
    "ls", "cd", "pwd", "cat", "head", "tail", "wc", "stat", "file", "du", "df",
    "grep", "sort", "uniq", "diff", "comm", "cut", "tr", "fmt", "pr", "fold",
    "echo", "printf",
    "which", "type", "command", "hash",
    "basename", "dirname", "realpath", "readlink",
]


def _is_allowed(cmd: str) -> bool:
    for allowed in ALLOWED_CMD:
        if cmd.startswith(allowed):
            return True
    return False


def _check_bash_permission(cmd: str) -> bool:
    delimiters = r'&&|\|\||>>|<<|\||;|&|>|<'
    cmd_parts = [part.strip() for part in re.split(delimiters, cmd) if part.strip()]
    if all(map(_is_allowed, cmd_parts)):
        return True
    max_width = shutil.get_terminal_size().columns - 2
    question = f"Execute `{cmd}`? y/n\n"
    wrap = '# ' + '-' * min((len(question) - 2), max_width)
    explicit_permission: str = input('\n' + wrap + '\n' + question + wrap + '\n')
    return explicit_permission.lower() in ("y", "yes")


def run_bash(command: str) -> str:
    """Execute a shell command and return stdout/stderr."""
    try:
        if _check_bash_permission(command):
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
            out = result.stdout
            if result.stderr:
                out += f"\nSTDERR:\n{result.stderr}"
            return f"Exit code: {result.returncode}\n{out}"
        return "Error: not allowed by user"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 120s"


# ---------------------------------------------------------------------------
#  Tool: read_file
# ---------------------------------------------------------------------------

SENSITIVE_FILE_PATTERNS = [
    ".env", ".env.*", "*.env", "*secret*", "*password*", "*credential*",
    "*token*", "*apikey*", "*api_key*", "id_rsa", "id_rsa.*",
    "id_ed25519", "id_ed25519.*", "*.pem", "*.key", "*.cert",
    "*.p12", "*.pfx", ".netrc", ".git-credentials", ".aws/credentials",
    "*.kubeconfig", "*.kube/config", ".npmrc", ".dockercfg",
    ".docker/config.json", "*.htpasswd", "*.htaccess",
    "config.yml", "config.yaml", "database.yml", "database.yaml",
    "secrets.yml", "secrets.yaml", "private*", "*.keystore", "*.jks",
]

SENSITIVE_DIR_SEGMENTS = [
    ".git", ".ssh", ".gnupg", "__pycache__", ".venv", "venv", "node_modules",
]


def _is_sensitive(filepath: str) -> bool:
    try:
        real = os.path.realpath(filepath)
    except Exception:
        real = filepath
    basename = os.path.basename(real)
    parts = real.split(os.sep)
    for seg in SENSITIVE_DIR_SEGMENTS:
        if seg in parts:
            return True
    for pattern in SENSITIVE_FILE_PATTERNS:
        if fnmatch.fnmatch(basename, pattern):
            return True
        if fnmatch.fnmatch(real, f"*{pattern}"):
            return True
        if fnmatch.fnmatch(real, f"*/{pattern}"):
            return True
    return False


def read_file(filepath: str, max_length: int = 100000) -> str:
    """Read a file's contents. Blocks sensitive files."""
    if not os.path.isabs(filepath):
        resolved = os.path.join(os.getcwd(), filepath)
    else:
        resolved = filepath
    resolved = os.path.normpath(resolved)

    if not os.path.exists(resolved):
        return f"Error: file not found: {filepath}"
    if os.path.isdir(resolved):
        return f"Error: path is a directory, not a file: {filepath}"
    if _is_sensitive(resolved):
        return f"Error: reading '{filepath}' is blocked — this file may contain sensitive data."

    try:
        size = os.path.getsize(resolved)
    except OSError as e:
        return f"Error: cannot determine file size: {e}"
    if size == 0:
        return "(file is empty)"
    if size > max_length:
        return f"Error: file is {size} bytes (max allowed: {max_length}). Use a tool like `head -n 100 <file>` via bash instead."

    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content
    except PermissionError:
        return f"Error: permission denied reading: {filepath}"
    except Exception as e:
        return f"Error: could not read file '{filepath}': {e}"


# ---------------------------------------------------------------------------
#  Tool registry
# ---------------------------------------------------------------------------

# Each tool entry: { "schema": {...}, "handler": callable }
TOOL_REGISTRY: dict[str, dict] = {
    "bash": {
        "schema": {
            "type": "function",
            "function": {
                "name": "bash",
                "description": (
                    "Execute a shell command and return stdout/stderr. "
                    "For general shell operations like listing files, running commands, "
                    "writing files via heredoc, etc."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The bash command to execute.",
                        }
                    },
                    "required": ["command"],
                },
            },
        },
        "handler": run_bash,
    },
    "read_file": {
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": (
                    "Read the contents of a file. This is the PREFERRED tool for getting "
                    "file contents. Use this instead of 'cat', 'head', 'tail' etc. in bash. "
                    "NOTE: Sensitive files (e.g. .env, secrets, keys, credentials) are blocked "
                    "for security."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Path to the file (absolute, or relative to current working directory).",
                        },
                        "max_length": {
                            "type": "integer",
                            "description": "Maximum number of bytes to read (default 100000).",
                            "default": 100000,
                        },
                    },
                    "required": ["filepath"],
                },
            },
        },
        "handler": read_file,
    },
}


def get_tool_schemas(tool_names: list[str]) -> list[dict]:
    """Return the LLM function schemas for the named tools."""
    return [TOOL_REGISTRY[name]["schema"] for name in tool_names if name in TOOL_REGISTRY]


def call_tool(name: str, arguments: dict) -> str:
    """Invoke a registered tool by name with the given arguments."""
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return f"Error: unknown tool '{name}'"
    try:
        return entry["handler"](**arguments)
    except Exception as e:
        return f"Error calling {name}: {e}"
