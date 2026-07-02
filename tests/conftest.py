"""Shared fixtures for all tests."""
import os
import sys
import tempfile
import pytest

# Ensure the src directory is in the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def temp_dir():
    """Create a temporary directory and cd into it. Clean up after."""
    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        yield tmpdir
        os.chdir(old_cwd)


@pytest.fixture
def temp_file(temp_dir):
    """Create a temporary file with given content and return its path."""
    def _create(filename: str, content: str) -> str:
        path = os.path.join(temp_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        return path
    return _create
