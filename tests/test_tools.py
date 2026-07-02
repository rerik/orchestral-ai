"""Tests for src/tools.py"""
import os
import sys
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import tools
from tools import (
    _is_allowed,
    _check_bash_permission,
    _is_sensitive,
    read_file,
    run_bash,
    get_tool_schemas,
    call_tool,
    TOOL_REGISTRY,
    ALLOWED_CMD,
    SENSITIVE_FILE_PATTERNS,
    SENSITIVE_DIR_SEGMENTS,
)


# ============================================================================
#  _is_allowed
# ============================================================================

class TestIsAllowed:
    def test_allowed_commands(self):
        """All commands in ALLOWED_CMD should be allowed."""
        for cmd in ALLOWED_CMD:
            assert _is_allowed(cmd) is True

    def test_allowed_with_args(self):
        """Allowed commands with arguments should pass."""
        assert _is_allowed("ls -la") is True
        assert _is_allowed("grep -r pattern .") is True

    def test_disallowed_commands(self):
        """Commands not in the allowlist should be rejected."""
        assert _is_allowed("rm -rf /") is False
        assert _is_allowed("curl evil.com") is False
        assert _is_allowed("sudo reboot") is False

    def test_partial_match_not_allowed(self):
        """A command that merely starts with an allowed prefix substring
        should NOT be allowed — we match command names exactly."""
        # 'ca' partial-matches 'cat' but should not pass since 'ca' != 'cat'
        assert _is_allowed("ca file.txt") is False


# ============================================================================
#  _is_sensitive
# ============================================================================

class TestIsSensitive:
    def test_env_file_sensitive(self):
        assert _is_sensitive(".env") is True
        assert _is_sensitive("/home/user/project/.env") is True

    def test_secret_patterns(self):
        assert _is_sensitive("my_secret_file.txt") is True
        assert _is_sensitive("password.txt") is True
        assert _is_sensitive("credentials.json") is True
        assert _is_sensitive("api_key.py") is True
        assert _is_sensitive("token.dat") is True

    def test_pem_key_files(self):
        assert _is_sensitive("cert.pem") is True
        assert _is_sensitive("private.key") is True
        assert _is_sensitive("id_rsa") is True
        assert _is_sensitive("id_ed25519") is True
        assert _is_sensitive("server.p12") is True

    def test_sensitive_directories(self):
        assert _is_sensitive("/home/user/.git/config") is True
        assert _is_sensitive("/home/user/.ssh/id_rsa") is True
        assert _is_sensitive("/project/__pycache__/module.pyc") is True
        assert _is_sensitive("/project/.venv/bin/python") is True
        assert _is_sensitive("/project/venv/lib/module.py") is True
        assert _is_sensitive("/project/node_modules/package/index.js") is True

    def test_normal_files_not_sensitive(self):
        assert _is_sensitive("main.py") is False
        assert _is_sensitive("/home/user/src/tools.py") is False
        assert _is_sensitive("README.md") is False
        assert _is_sensitive("requirements.txt") is False


# ============================================================================
#  read_file
# ============================================================================

class TestReadFile:
    def test_reads_file_content(self, temp_dir, temp_file):
        path = temp_file("hello.txt", "Hello, world!")
        result = read_file(path)
        assert result == "Hello, world!"

    def test_relative_path(self, temp_dir, temp_file):
        path = temp_file("data.txt", "some data")
        result = read_file("data.txt")
        assert result == "some data"

    def test_file_not_found(self):
        result = read_file("/nonexistent/path/file.txt")
        assert result.startswith("Error: file not found")

    def test_directory_not_file(self, temp_dir):
        result = read_file(temp_dir)
        assert "is a directory" in result

    def test_empty_file(self, temp_file):
        path = temp_file("empty.txt", "")
        result = read_file(path)
        assert "(file is empty)" in result

    def test_sensitive_file_blocked(self, temp_file):
        path = temp_file(".env", "SECRET=12345")
        result = read_file(path)
        assert "blocked" in result

    def test_file_too_large(self, temp_file):
        path = temp_file("big.txt", "x" * 5000)
        result = read_file(path, max_length=1000)
        assert "file is" in result and "bytes" in result

    def test_max_length_default(self, temp_file):
        """Content within default max_length should be read fine."""
        path = temp_file("normal.txt", "Hello")
        result = read_file(path)
        assert result == "Hello"


# ============================================================================
#  run_bash
# ============================================================================

class TestRunBash:
    def test_runs_allowed_command(self):
        with patch("tools._check_bash_permission", return_value=True):
            result = run_bash("echo hello")
            assert "hello" in result
            assert "Exit code: 0" in result

    def test_denied_by_user(self):
        with patch("tools._check_bash_permission", return_value=False):
            result = run_bash("rm -rf /")
            assert "not allowed by user" in result

    def test_command_timeout(self):
        with patch("tools._check_bash_permission", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 120)):
            result = run_bash("sleep 200")
            assert "timed out" in result.lower()

    def test_stderr_captured(self):
        with patch("tools._check_bash_permission", return_value=True):
            result = run_bash("echo error >&2")
            assert "STDERR:" in result
            assert "error" in result

    def test_nonzero_exit_code(self):
        with patch("tools._check_bash_permission", return_value=True):
            result = run_bash("exit 1")
            assert "Exit code: 1" in result


# ============================================================================
#  _check_bash_permission (interactive prompt)
# ============================================================================

class TestCheckBashPermission:
    def test_allowlist_allows(self):
        """Commands composed only of allowed commands should auto-pass."""
        assert _check_bash_permission("ls -la") is True
        assert _check_bash_permission("cat file.txt") is True
        assert _check_bash_permission("grep pattern file") is True

    def test_complex_allowed_pipeline(self):
        """Pipelines of allowed commands should auto-pass."""
        with patch("tools._is_allowed", return_value=True):
            assert _check_bash_permission("ls | grep test") is True

    def test_user_approves(self):
        """When command is not auto-allowed, user must say yes."""
        with patch("tools._is_allowed", return_value=False), \
             patch("builtins.input", return_value="y"), \
             patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            assert _check_bash_permission("curl example.com") is True

    def test_user_rejects(self):
        with patch("tools._is_allowed", return_value=False), \
             patch("builtins.input", return_value="n"), \
             patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            assert _check_bash_permission("curl example.com") is False

    def test_user_says_yes_full_word(self):
        with patch("tools._is_allowed", return_value=False), \
             patch("builtins.input", return_value="yes"), \
             patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            assert _check_bash_permission("curl example.com") is True


# ============================================================================
#  TOOL_REGISTRY structure
# ============================================================================

class TestToolRegistry:
    def test_has_both_tools(self):
        assert "bash" in TOOL_REGISTRY
        assert "read_file" in TOOL_REGISTRY

    def test_bash_has_schema_and_handler(self):
        entry = TOOL_REGISTRY["bash"]
        assert "schema" in entry
        assert "handler" in entry
        assert entry["schema"]["function"]["name"] == "bash"
        assert callable(entry["handler"])

    def test_read_file_has_schema_and_handler(self):
        entry = TOOL_REGISTRY["read_file"]
        assert "schema" in entry
        assert "handler" in entry
        assert entry["schema"]["function"]["name"] == "read_file"
        assert callable(entry["handler"])

    def test_bash_schema_requires_command(self):
        required = TOOL_REGISTRY["bash"]["schema"]["function"]["parameters"]["required"]
        assert "command" in required

    def test_read_file_schema_requires_filepath(self):
        required = TOOL_REGISTRY["read_file"]["schema"]["function"]["parameters"]["required"]
        assert "filepath" in required


# ============================================================================
#  get_tool_schemas
# ============================================================================

class TestGetToolSchemas:
    def test_returns_schemas_for_known_tools(self):
        schemas = get_tool_schemas(["bash", "read_file"])
        assert len(schemas) == 2

    def test_ignores_unknown_tools(self):
        schemas = get_tool_schemas(["bash", "nonexistent_tool"])
        assert len(schemas) == 1

    def test_empty_list(self):
        assert get_tool_schemas([]) == []

    def test_all_unknown(self):
        assert get_tool_schemas(["foo", "bar"]) == []


# ============================================================================
#  call_tool
# ============================================================================

class TestCallTool:
    def test_calls_bash_tool(self):
        with patch.object(tools, "_check_bash_permission", return_value=True):
            result = call_tool("bash", {"command": "echo test"})
            assert "test" in result

    def test_calls_read_file_tool(self, temp_file):
        path = temp_file("test.txt", "hello world")
        result = call_tool("read_file", {"filepath": path})
        assert "hello world" in result

    def test_unknown_tool(self):
        result = call_tool("nonexistent", {})
        assert "unknown tool" in result

    def test_missing_arguments(self):
        """Passing a bad keyword to the handler should raise TypeError,
        which call_tool catches and returns as an error string."""
        with patch.object(tools, "_check_bash_permission", return_value=True):
            result = call_tool("bash", {})
            assert "Error calling bash" in result
