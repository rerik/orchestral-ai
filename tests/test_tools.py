"""Tests for src/tools.py"""
import os
import sys
import subprocess
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import smart_agent.tools as tools
from smart_agent.tools import (
    _is_allowed,
    _check_bash_permission,
    _is_sensitive,
    read_file,
    run_bash,
    edit_file,
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
        with patch("smart_agent.tools._check_bash_permission", return_value=True):
            result = run_bash("echo hello")
            assert "hello" in result
            assert "Exit code: 0" in result

    def test_denied_by_user(self):
        with patch("smart_agent.tools._check_bash_permission", return_value=False):
            result = run_bash("rm -rf /")
            assert "not allowed by user" in result

    def test_command_timeout(self):
        with patch("smart_agent.tools._check_bash_permission", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 120)):
            result = run_bash("sleep 200")
            assert "timed out" in result.lower()

    def test_stderr_captured(self):
        with patch("smart_agent.tools._check_bash_permission", return_value=True):
            result = run_bash("echo error >&2")
            assert "STDERR:" in result
            assert "error" in result

    def test_nonzero_exit_code(self):
        with patch("smart_agent.tools._check_bash_permission", return_value=True):
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
        with patch("smart_agent.tools._is_allowed", return_value=True):
            assert _check_bash_permission("ls | grep test") is True

    def test_user_approves(self):
        """When command is not auto-allowed, user must say yes."""
        with patch("smart_agent.tools._is_allowed", return_value=False), \
             patch("builtins.input", return_value="y"), \
             patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            assert _check_bash_permission("curl example.com") is True

    def test_user_rejects(self):
        with patch("smart_agent.tools._is_allowed", return_value=False), \
             patch("builtins.input", return_value="n"), \
             patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            assert _check_bash_permission("curl example.com") is False

    def test_user_says_yes_full_word(self):
        with patch("smart_agent.tools._is_allowed", return_value=False), \
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




# ============================================================================
#  edit_file
# ============================================================================

class TestEditFile:
    def test_file_not_found(self):
        """Calling edit_file on a nonexistent path returns 'Error: file not found'."""
        result = edit_file("/nonexistent/path/file.txt", old_string="foo", new_string="bar")
        assert result.startswith("Error: file not found")

    def test_directory_not_file(self, temp_dir):
        """Calling edit_file on a directory returns 'is a directory' error."""
        result = edit_file(temp_dir, old_string="foo", new_string="bar")
        assert "is a directory" in result

    def test_no_changes_needed(self, temp_file):
        """When old_string and new_string are identical, returns appropriate message."""
        path = temp_file("nochange.txt", "hello world")
        result = edit_file(path, old_string="hello", new_string="hello")
        assert "No changes to apply" in result
        assert "old_string and new_string are identical" in result

    def test_user_rejects(self, temp_file):
        """Mock input to return 'n', verify the file is NOT modified and 'Edit rejected by user' is returned."""
        path = temp_file("reject.txt", "hello world")
        with patch("builtins.input", return_value="n"):
            result = edit_file(path, old_string="world", new_string="everyone")
        assert result == "Edit rejected by user."
        # Verify file was NOT modified
        with open(path, "r") as f:
            assert f.read() == "hello world"

    def test_user_accepts(self, temp_file):
        """Mock input to return 'y', verify the file IS written with new content and success message."""
        path = temp_file("accept.txt", "hello world")
        with patch("builtins.input", return_value="y"):
            result = edit_file(path, old_string="world", new_string="everyone")
        assert "Successfully edited" in result
        # Verify file was modified
        with open(path, "r") as f:
            assert f.read() == "hello everyone"

    def test_old_string_not_found(self, temp_file):
        """When old_string does not exist in the file, return appropriate error."""
        path = temp_file("notfound.txt", "hello world")
        result = edit_file(path, old_string="xyz", new_string="abc")
        assert result == "Error: old_string not found in file."

    def test_file_to_empty(self, temp_file):
        """Replacing the entire file content with empty string works."""
        path = temp_file("to_empty.txt", "remove me please")
        with patch("builtins.input", return_value="y"):
            result = edit_file(path, old_string="remove me please", new_string="")
        assert "Successfully edited" in result
        with open(path, "r") as f:
            assert f.read() == ""

    def test_old_string_empty_error(self, temp_file):
        """Calling edit_file with empty old_string returns an error."""
        path = temp_file("empty_old.txt", "anything")
        result = edit_file(path, old_string="", new_string="anything")
        assert result == "Error: old_string must not be empty."

    def test_multiple_occurrences_error(self, temp_file):
        """When old_string appears multiple times, return an error mentioning appearances."""
        path = temp_file("multiple.txt", "the cat and the cat played")
        result = edit_file(path, old_string="cat", new_string="dog")
        assert "appears" in result
        assert "times" in result

    def test_edit_file_in_registry(self):
        """Assert edit_file in TOOL_REGISTRY with proper schema and callable handler."""
        assert "edit_file" in TOOL_REGISTRY
        entry = TOOL_REGISTRY["edit_file"]
        assert "schema" in entry
        assert "handler" in entry
        assert entry["schema"]["function"]["name"] == "edit_file"
        assert callable(entry["handler"])

    def test_edit_file_schema_requires_filepath_old_string_new_string(self):
        """Assert filepath, old_string, and new_string are all in the required params."""
        required = TOOL_REGISTRY["edit_file"]["schema"]["function"]["parameters"]["required"]
        assert "filepath" in required
        assert "old_string" in required
        assert "new_string" in required

    def test_call_edit_file_via_call_tool(self, temp_file):
        """Use call_tool('edit_file', ...) path, mock input to 'y', verify it works."""
        path = temp_file("call_tool_edit.txt", "hello world")
        with patch("builtins.input", return_value="y"):
            result = call_tool("edit_file", {"filepath": path, "old_string": "world", "new_string": "everyone"})
        assert "Successfully edited" in result
        with open(path, "r") as f:
            assert f.read() == "hello everyone"

    def test_old_string_unique_match(self, temp_file):
        """Replace a unique substring and verify file content changes correctly."""
        path = temp_file("unique.txt", "hello beautiful world")
        with patch("builtins.input", return_value="y"):
            result = edit_file(path, old_string="beautiful ", new_string="")
        assert "Successfully edited" in result
        with open(path, "r") as f:
            assert f.read() == "hello world"


# ============================================================================
#  web_search
# ============================================================================

class TestWebSearch:
    def test_returns_results_for_valid_query(self):
        """A valid query should return formatted results."""
        result = call_tool("web_search", {"query": "Python programming", "max_results": 2})
        assert "Web search results for: 'Python programming'" in result
        assert "URL:" in result
        # Should have at least one numbered result
        assert "1." in result

    def test_respects_max_results(self):
        """max_results should limit the number of results."""
        result = call_tool("web_search", {"query": "weather", "max_results": 1})
        # Only result #1 should be present, #2 should not
        assert "1." in result
        assert "\n2." not in result

    def test_clamps_max_results_to_20(self):
        """max_results above 20 should be clamped."""
        # Just test that it doesn't crash and still works
        result = call_tool("web_search", {"query": "test", "max_results": 100})
        assert "Web search results for: 'test'" in result

    def test_empty_query_handled(self):
        """An empty query should not crash."""
        result = call_tool("web_search", {"query": ""})
        # Should return either results or a "no results" message
        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_results_query(self):
        """An extremely specific nonsense query may return no results."""
        result = call_tool("web_search", {"query": "xyzkkwwqqppzz1234567890abcdeffoo"})
        # Should not crash, should return something
        assert isinstance(result, str)

    def test_web_search_in_registry(self):
        """web_search should be in TOOL_REGISTRY with schema and handler."""
        assert "web_search" in TOOL_REGISTRY
        entry = TOOL_REGISTRY["web_search"]
        assert "schema" in entry
        assert "handler" in entry
        assert entry["schema"]["function"]["name"] == "web_search"
        assert callable(entry["handler"])

    def test_web_search_schema_requires_query(self):
        """The web_search schema should require 'query'."""
        required = TOOL_REGISTRY["web_search"]["schema"]["function"]["parameters"]["required"]
        assert "query" in required


# ============================================================================
#  Updated: TOOL_REGISTRY now has 4 tools
# ============================================================================

class TestToolRegistryUpdated:
    def test_has_four_tools(self):
        """TOOL_REGISTRY should now contain bash, read_file, web_search, and edit_file."""
        assert "bash" in TOOL_REGISTRY
        assert "read_file" in TOOL_REGISTRY
        assert "web_search" in TOOL_REGISTRY
        assert "edit_file" in TOOL_REGISTRY
        assert len(TOOL_REGISTRY) == 4


# ============================================================================
