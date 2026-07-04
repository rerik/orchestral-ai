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
import difflib
import tempfile




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
#  Tool: edit_file
# ---------------------------------------------------------------------------


def _count_diff_stats(diff_lines: list[str]) -> tuple[int, int]:
    """Count lines added (+) and removed (-) from a unified diff (ignoring header/metadata)."""
    added = 0
    removed = 0
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _show_occurrences(filepath: str, content: str, old_string: str, occurrences: list[int]) -> str:
    """Format an error message with line-numbered context for each occurrence of old_string."""
    context_lines = 2  # lines of context before and after
    file_lines = content.splitlines(keepends=True)
    # Build line start offsets for mapping positions to line numbers
    line_starts = [0]
    for line in file_lines:
        line_starts.append(line_starts[-1] + len(line))

    msg_lines = [
        f"Error: old_string appears {len(occurrences)} times in the file. "
        f"It must be unique. Provide a larger string with more surrounding context "
        f"to make it unique.\n",
        f"Occurrences in `{filepath}`:\n",
    ]

    for idx, pos in enumerate(occurrences, 1):
        # Find the 1-based line number of this occurrence
        line_no = 1
        for ls_idx in range(1, len(line_starts)):
            if line_starts[ls_idx] > pos:
                break
            line_no = ls_idx

        # Determine range of lines to show as context
        start_line_idx = max(0, line_no - 1 - context_lines)
        end_line_idx = min(len(file_lines), line_no - 1 + context_lines + 1)

        msg_lines.append(f"--- Occurrence #{idx} at line {line_no} ---\n")
        for li in range(start_line_idx, end_line_idx):
            lnum = li + 1
            prefix = ">" if lnum == line_no else " "
            line_text = file_lines[li]
            if not line_text.endswith("\n"):
                line_text += "\n"
            msg_lines.append(f"  {prefix} {lnum:4d}| {line_text}")
        msg_lines.append("\n")

    return "".join(msg_lines)


def edit_file(filepath: str, old_string: str, new_string: str) -> str:
    """Edit a file by finding and replacing an exact string.

    Finds `old_string` in the file (must appear exactly once), replaces it
    with `new_string`, shows a unified diff, asks for user confirmation,
    then writes atomically.

    Args:
        filepath: Path to the file (absolute, or relative to current working directory).
        old_string: The exact text to find and replace. Must appear exactly once
                    in the file.
        new_string: The replacement text.

    Returns a summary of changes or an error message.
    """
    # Resolve the path
    if not os.path.isabs(filepath):
        resolved = os.path.join(os.getcwd(), filepath)
    else:
        resolved = filepath
    resolved = os.path.normpath(resolved)

    # Check if file exists
    if not os.path.exists(resolved):
        return f"Error: file not found: {filepath}"
    if os.path.isdir(resolved):
        return f"Error: path is a directory, not a file: {filepath}"

    # Read current content
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()
    except PermissionError:
        return f"Error: permission denied reading: {filepath}"
    except Exception as e:
        return f"Error: could not read file '{filepath}': {e}"

    # Validate old_string is not empty
    if not old_string:
        return "Error: old_string must not be empty."

    # Find all occurrences of old_string
    occurrences = []
    start = 0
    while True:
        idx = old_content.find(old_string, start)
        if idx == -1:
            break
        occurrences.append(idx)
        start = idx + 1

    if len(occurrences) == 0:
        return "Error: old_string not found in file."
    if len(occurrences) > 1:
        return _show_occurrences(filepath, old_content, old_string, occurrences)

    # Check for no-op
    if old_string == new_string:
        return "No changes to apply — old_string and new_string are identical."

    # Compute new content (replace first/only occurrence)
    new_content = old_content.replace(old_string, new_string, 1)

    # Compute unified diff
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filepath}",
        tofile=f"b/{filepath}",
    ))

    # Count changes
    added, removed = _count_diff_stats(diff)
    diff_text = "".join(diff)

    # Display the diff nicely
    max_width = shutil.get_terminal_size().columns - 2
    header = f" Proposed edit for `{filepath}` "
    divider = '#' * max_width
    left_pad = (max_width - len(header)) // 2
    print()
    print(divider)
    print('#' + ' ' * (max_width - 2) + '#')
    print(f"#{' ' * (left_pad - 1)}{header}{' ' * (max_width - len(header) - left_pad - 1)}#")
    print('#' + ' ' * (max_width - 2) + '#')
    print(divider)
    print()
    if diff_text:
        for line in diff_text.splitlines(keepends=True):
            print(line, end='')
    else:
        print("(diff is empty — unusual state)")
    print()

    # Show stats
    summary_line = f"  {added} line(s) added, {removed} line(s) removed"
    print(summary_line)
    print(divider)

    # Ask for confirmation
    question = f" Apply this edit to `{filepath}`? y/n "
    answer = input('\n' + question)
    if answer.lower() not in ("y", "yes"):
        print("Edit rejected by user.")
        return "Edit rejected by user."

    # Write atomically: write to a temp file, then rename
    try:
        # Ensure parent directory exists
        parent = os.path.dirname(resolved)
        if parent:
            os.makedirs(parent, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=parent if parent else None, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(new_content)
            # Rename atomic on the same filesystem
            os.replace(tmp_path, resolved)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise
    except PermissionError:
        return f"Error: permission denied writing to: {filepath}"
    except OSError as e:
        return f"Error: could not write to '{filepath}': {e}"

    return f"Successfully edited `{filepath}` — {added} line(s) added, {removed} line(s) removed."


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
    "edit_file": {
        "schema": {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": (
                    "Edit a file by finding and replacing an exact string. "
                    "The tool reads the current file, finds `old_string` (which must appear "
                    "exactly once in the file), replaces it with `new_string`, computes a "
                    "unified diff of the changes, displays it to the user, and asks for "
                    "explicit confirmation before writing. If `old_string` appears multiple "
                    "times, the tool will reject the edit and show the occurrences with "
                    "context to help you disambiguate — provide a larger unique string "
                    "with more surrounding context instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {
                            "type": "string",
                            "description": "Path to the file (absolute, or relative to current working directory).",
                        },
                        "old_string": {
                            "type": "string",
                            "description": "The exact text to find and replace. Must appear exactly once in the file — if it appears multiple times, the tool will reject the edit and ask for more context.",
                        },
                        "new_string": {
                            "type": "string",
                            "description": "The replacement text.",
                        },
                    },
                    "required": ["filepath", "old_string", "new_string"],
                },
            },
        },
        "handler": edit_file,
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