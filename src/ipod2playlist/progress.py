"""Resumable per-service progress, so an interrupted run can continue into the same playlist."""

import json
import os
from pathlib import Path

VALID_STATUSES = {"added", "missing"}


class Progress:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = {"version": 1, "services": {}}
        if self.path.exists():
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
                raise ValueError(f"{path} is not a progress file")
            self._data = data

    def _service(self, service: str) -> dict:
        return self._data["services"].setdefault(service, {"playlist_id": None, "songs": {}})

    def playlist_id(self, service: str) -> str | None:
        return self._data["services"].get(service, {}).get("playlist_id")

    def set_playlist_id(self, service: str, playlist_id: str) -> None:
        self._service(service)["playlist_id"] = playlist_id

    def status(self, service: str, song_key: str) -> str | None:
        return self._data["services"].get(service, {}).get("songs", {}).get(song_key)

    def record(self, service: str, song_key: str, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; expected one of {sorted(VALID_STATUSES)}")
        self._service(service)["songs"][song_key] = status

    def keys_with_status(self, service: str, status: str) -> list[str]:
        songs = self._data["services"].get(service, {}).get("songs", {})
        return [key for key, value in songs.items() if value == status]

    def save(self) -> None:
        """Write to a sibling temp file, then atomically replace the real file."""
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, self.path)
