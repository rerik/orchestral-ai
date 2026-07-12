"""
Config path resolution utilities.

Provides functions to search for config files in standard locations:
  1. ./.orchestral-ai/   (project-local, highest priority)
  2. ~/.orchestral-ai/   (user-global)
  3. Package directory    (built-in fallback)

Both main.py and team.py depend on these functions; they live in their
own module to avoid a circular import between those two modules.
"""

import os


def get_config_search_dirs(no_package: bool = False) -> list[str]:
    """Return config directory search paths in priority order.

    1. ./.orchestral-ai/   (project-local)
    2. ~/.orchestral-ai/   (user-global)
    3. Package directory    (built-in fallback)
    """
    if no_package:
        return [
            os.path.join(".", ".orchestral-ai"),
            os.path.join(os.path.expanduser("~"), ".orchestral-ai"),
        ]
    package_dir = os.path.dirname(os.path.abspath(__file__))
    return [
        os.path.join(".", ".orchestral-ai"),
        os.path.join(os.path.expanduser("~"), ".orchestral-ai"),
        package_dir,
    ]


def find_config_path(relative_path: str, no_package: bool = False) -> str | None:
    """Search for a config file in standard locations.

    If *relative_path* is absolute, return it unchanged.

    Search order:
    1. ./.orchestral-ai/   (project-local)
    2. ~/.orchestral-ai/   (user-global)
    3. Package directory    (built-in fallback)

    Returns the first existing path found, or the package-directory
    path (which may not exist) as a default.
    """
    if os.path.isabs(relative_path):
        return relative_path

    for root in get_config_search_dirs(no_package):
        candidate = os.path.normpath(os.path.join(root, relative_path))
        if os.path.isfile(candidate):
            return candidate
        
    if no_package:
        return None

    # Default: return the package path (caller handles file-not-found)
    package_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(package_dir, relative_path))
