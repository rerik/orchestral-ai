"""
Chat Manager — persistence for chat sessions stored in .orchestral-ai/

Directory structure:
    .orchestral-ai/
      index.json          # list of all chats with metadata
      chats/
        <chat_id>.json    # individual chat files

Each chat file contains:
    {
        "id": "...",
        "title": "...",
        "created_at": "ISO 8601",
        "updated_at": "ISO 8601",
        "mode": "team" | "single",
        "messages": [...]
    }

Index file:
    {
        "chats": [
            {"id": "...", "title": "...", "created_at": "...", "updated_at": "...", "mode": "...", "message_count": N}
        ]
    }
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

ORCHESTRAL_DIR = ".orchestral-ai"
CHATS_DIR = "chats"
INDEX_FILE = "index.json"


class ChatManager:
    """Manages chat session persistence in the .orchestral-ai directory."""

    def __init__(self, workdir: str | None = None):
        """Initialize the chat manager.

        Args:
            workdir: Working directory where .orchestral-ai will be created.
                     Defaults to os.getcwd().
        """
        self.workdir = workdir or os.getcwd()
        self.orchestral_dir = os.path.join(self.workdir, ORCHESTRAL_DIR)
        self.chats_dir = os.path.join(self.orchestral_dir, CHATS_DIR)
        self.index_path = os.path.join(self.orchestral_dir, INDEX_FILE)
        self.current_chat_id: str | None = None
        self._ensure_dirs()

    # ------------------------------------------------------------------
    #  Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dirs(self) -> None:
        """Create the .orchestral-ai directory structure if it doesn't exist."""
        os.makedirs(self.chats_dir, exist_ok=True)

    def _load_index(self) -> dict[str, Any]:
        """Load the chat index file. Returns a dict with a 'chats' key."""
        if not os.path.isfile(self.index_path):
            return {"chats": []}
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"chats": []}

    def _save_index(self, index: dict[str, Any]) -> None:
        """Save the chat index file atomically."""
        tmp_path = self.index_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.index_path)
        except OSError:
            pass

    def _chat_path(self, chat_id: str) -> str:
        """Return the file path for a given chat ID."""
        return os.path.join(self.chats_dir, f"{chat_id}.json")

    def _save_chat(self, chat_id: str, data: dict[str, Any]) -> None:
        """Write a single chat file."""
        with open(self._chat_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_chat_file(self, chat_id: str) -> dict[str, Any] | None:
        """Read a single chat file. Returns None if not found."""
        chat_path = self._chat_path(chat_id)
        if not os.path.isfile(chat_path):
            return None
        try:
            with open(chat_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    #  Public API
    # ------------------------------------------------------------------

    def create_chat(self, mode: str = "team") -> str:
        """Create a new chat session and return its ID.

        Args:
            mode: "team" or "single" — the agent mode.

        Returns:
            The new chat ID (12-character hex string).
        """
        chat_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()

        chat_data: dict[str, Any] = {
            "id": chat_id,
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "mode": mode,
            "messages": [],
        }

        self._save_chat(chat_id, chat_data)

        # Update index
        index = self._load_index()
        index["chats"].insert(0, {  # newest first
            "id": chat_id,
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "mode": mode,
            "message_count": 0,
        })
        self._save_index(index)

        self.current_chat_id = chat_id
        return chat_id

    def save_messages(self, messages: list[dict[str, Any]]) -> None:
        """Persist the current chat's messages and update metadata.

        Automatically sets the chat title from the first user message
        (truncated to 60 characters).

        Args:
            messages: The full message list (including system messages).
        """
        if not self.current_chat_id:
            return

        chat_data = self._load_chat_file(self.current_chat_id)
        if chat_data is None:
            return

        chat_data["messages"] = messages
        chat_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Auto-generate title from the first user message
        if chat_data["title"] == "New Chat":
            for msg in messages:
                if msg.get("role") == "user":
                    content = msg.get("content", "").strip()
                    if content:
                        title = content[:60]
                        if len(content) > 60:
                            title += "..."
                        chat_data["title"] = title
                    break

        self._save_chat(self.current_chat_id, chat_data)

        # Update index entry
        index = self._load_index()
        for entry in index["chats"]:
            if entry["id"] == self.current_chat_id:
                entry["title"] = chat_data["title"]
                entry["updated_at"] = chat_data["updated_at"]
                entry["message_count"] = sum(
                    1 for m in messages if m.get("role") != "system"
                )
                break
        self._save_index(index)

    def list_chats(self) -> list[dict[str, Any]]:
        """Return all chats sorted by creation time (newest first).

        Returns:
            A list of chat metadata dicts (id, title, created_at, updated_at,
            mode, message_count).
        """
        index = self._load_index()
        return sorted(
            index["chats"],
            key=lambda c: c.get("created_at", ""),
            reverse=True,
        )

    def load_chat(self, chat_id: str) -> dict[str, Any] | None:
        """Load a chat by ID and set it as the current chat.

        Args:
            chat_id: The chat ID to load.

        Returns:
            The chat data dict, or None if the chat doesn't exist.
        """
        chat_data = self._load_chat_file(chat_id)
        if chat_data is None:
            return None
        self.current_chat_id = chat_id
        return chat_data

    def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat by ID.

        Args:
            chat_id: The chat ID to delete.

        Returns:
            True if the chat was deleted, False if it didn't exist.
        """
        chat_path = self._chat_path(chat_id)
        existed = os.path.isfile(chat_path)
        if existed:
            try:
                os.remove(chat_path)
            except OSError:
                pass

        index = self._load_index()
        index["chats"] = [c for c in index["chats"] if c["id"] != chat_id]
        self._save_index(index)

        if self.current_chat_id == chat_id:
            self.current_chat_id = None
        return existed

    def format_chat_list(self) -> str:
        """Return a human-readable formatted string of all chats.

        Returns:
            A string listing all chats with their IDs, titles, modes,
            message counts, and timestamps.
        """
        chats = self.list_chats()
        if not chats:
            return "No saved chats."

        lines = ["Chats:", "-" * 72]
        for chat in chats:
            marker = "→" if chat["id"] == self.current_chat_id else " "
            created = chat.get("created_at", "")[:19].replace("T", " ")
            lines.append(
                f"{marker} [{chat['id']}] {chat['title']}  "
                f"({chat.get('mode', '?')}, "
                f"{chat.get('message_count', 0)} msgs)  "
                f"{created}"
            )
        lines.append("-" * 72)
        return "\n".join(lines)
