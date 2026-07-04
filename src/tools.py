"""
Tool definitions: each tool has a name, an LLM function schema,
and a handler function.
"""

import json
import os
import re
import subprocess
import shutil
import fnmatch
import sys



# ---------------------------------------------------------------------------
#  Safe JSON parsing — handles malformed LLM output
# ---------------------------------------------------------------------------

def safe_json_loads(raw: str) -> dict:
    """Safely parse a JSON string that might be malformed (e.g. from an LLM).

    Attempts to fix common errors:
    - unterminated strings (appends closing quote)
    - unclosed braces / brackets (appends missing closing chars)
    - trailing commas (removes them before } or ] and at end of string)

    Returns an empty dict if all recovery attempts fail.
    """
    raw = raw.strip()
    if not raw:
        return {}

    # 1. Try direct parse
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
        # If it's a list, wrap it
        return {"result": result}
    except json.JSONDecodeError:
        pass

    # Helper: strip string contents to get structural skeleton
    def _skeleton(s: str) -> str:
        """Replace string contents with placeholders."""
        out = []
        i = 0
        while i < len(s):
            if s[i] == '"':
                out.append('"')
                i += 1
                while i < len(s):
                    if s[i] == '\\':
                        out.append(s[i:i+2])
                        i += 2
                    elif s[i] == '"':
                        out.append('"')
                        i += 1
                        break
                    else:
                        i += 1
            else:
                out.append(s[i])
                i += 1
        return ''.join(out)

    # Collect fix candidates
    candidates = []

    # Fix A: unterminated string (append closing quote)
    candidates.append(raw + '"')

    # Fix B: close unclosed braces/brackets (strip trailing comma first)
    skel = _skeleton(raw)
    open_braces = skel.count('{') - skel.count('}')
    open_brackets = skel.count('[') - skel.count(']')
    if open_braces > 0 or open_brackets > 0:
        closing = '}' * max(open_braces, 0) + ']' * max(open_brackets, 0)
        # Try without stripping trailing comma
        candidates.append(raw + closing)
        candidates.append(raw + '"' + closing)
        # Try stripping trailing comma before closing
        trimmed = raw.rstrip()
        if trimmed.endswith(','):
            trimmed = trimmed[:-1]
            candidates.append(trimmed + closing)
            candidates.append(trimmed + '"' + closing)

    # Fix C: trailing commas before } or ]
    trailing_fixed = re.sub(r',\s*([}\]])', r'\1', raw)
    if trailing_fixed != raw:
        candidates.append(trailing_fixed)
        # Also try: trailing commas + close braces
        skel2 = _skeleton(trailing_fixed)
        ob2 = skel2.count('{') - skel2.count('}')
        obr2 = skel2.count('[') - skel2.count(']')
        if ob2 > 0 or obr2 > 0:
            candidates.append(trailing_fixed + '}' * max(ob2, 0) + ']' * max(obr2, 0))

    # Fix D: trailing comma at end of string (not before } or ])
    if raw.rstrip().endswith(','):
        stripped = raw.rstrip()[:-1]
        candidates.append(stripped)
        # Also try: closing braces after stripping trailing comma
        skel_s = _skeleton(stripped)
        obs = skel_s.count('{') - skel_s.count('}')
        obrs = skel_s.count('[') - skel_s.count(']')
        if obs > 0 or obrs > 0:
            candidates.append(stripped + '}' * max(obs, 0) + ']' * max(obrs, 0))
        # And with closing quote
        candidates.append(stripped + '"')
        if obs > 0 or obrs > 0:
            candidates.append(stripped + '"' + '}' * max(obs, 0) + ']' * max(obrs, 0))

    # Fix E: combination of all fixes (trailing commas + close braces + close string)
    combined = re.sub(r',\s*([}\]])', r'\1', raw)
    if combined.rstrip().endswith(','):
        combined = combined.rstrip()[:-1]
    skel3 = _skeleton(combined)
    ob3 = skel3.count('{') - skel3.count('}')
    obr3 = skel3.count('[') - skel3.count(']')
    if ob3 > 0 or obr3 > 0:
        combined += '}' * max(ob3, 0) + ']' * max(obr3, 0)
    candidates.append(combined)
    candidates.append(combined + '"')

    # Try all candidates
    for candidate in candidates:
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
            return {"result": result}
        except json.JSONDecodeError:
            continue

    # All recovery attempts failed
    print(
        f"Warning: could not parse JSON arguments: {raw[:200]}...",
        file=sys.stderr,
    )
    return {}


# ---------------------------------------------------------------------------
#  Tool: bash
# ---------------------------------------------------------------------------

ALLOWED_CMD = [
    "ls", "cd", "pwd", "cat", "head", "tail", "wc", "stat", "file", "du", "df",
    "grep", "sort", "uniq", "diff", "comm", "cut", "tr", "fmt", "pr", "fold",
    "echo", "printf",
    "which", "type", "command", "hash",
    "basename", "dirname", "realpath", "readlink",
    "git status", "git log", "git diff", "git show",
    "python3 -m pytest", "python3 -m unittest", "python3 -m doctest",
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
#  Tool: web_search
# ---------------------------------------------------------------------------

def web_search(query: str, max_results: int = 10) -> str:
    """Search the web using DuckDuckGo and return formatted results.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return (default 10, max 20).

    Returns a formatted string with title, URL, and snippet for each result.
    """
    max_results = max(1, min(max_results, 20))

    try:
        from ddgs import DDGS
    except ImportError:
        return (
            "Error: the 'ddgs' package is required for web search. "
            "Install it with: pip install ddgs"
        )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        return f"Error performing web search: {type(e).__name__}: {e}"

    if not results:
        return f"No results found for query: '{query}'"

    lines = [f"Web search results for: '{query}'", ""]
    for i, r in enumerate(results, 1):
        title = r.get("title", "No title")
        url = r.get("href", "No URL")
        body = r.get("body", "No description")
        lines.append(f"{i}. {title}")
        lines.append(f"   URL: {url}")
        lines.append(f"   {body}")
        lines.append("")

    return "\n".join(lines).strip()


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
    "web_search": {
        "schema": {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web for information using DuckDuckGo. "
                    "Use this to find current information, documentation, "
                    "news, or any knowledge not already in your training data."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 10, max 20).",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        "handler": web_search,
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
