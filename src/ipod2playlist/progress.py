"""Resumable per-service progress, so an interrupted run can continue into the same playlist."""

import json
import os
from pathlib import Path

from ipod2playlist.matching import Candidate

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

    def services(self) -> list[str]:
        return list(self._data["services"])

    def playlist_id(self, service: str) -> str | None:
        return self._data["services"].get(service, {}).get("playlist_id")

    def set_playlist_id(self, service: str, playlist_id: str) -> None:
        self._service(service)["playlist_id"] = playlist_id

    def status(self, service: str, song_key: str) -> str | None:
        return self._data["services"].get(service, {}).get("songs", {}).get(song_key)

    def record(self, service: str, song_key: str, status: str) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; expected one of {sorted(VALID_STATUSES)}")
        block = self._service(service)
        block["songs"][song_key] = status
        if status == "added":
            block.get("maybe", {}).pop(song_key, None)

    def record_maybe(self, service: str, song_key: str, candidate: Candidate, score: float) -> None:
        """Remember a close match for review. The "maybe" key only appears here, so files
        without near misses keep the exact v1.5 shape; v1.5 code ignores it."""
        block = self._service(service)
        block.setdefault("maybe", {})[song_key] = {
            "id": candidate.id, "title": candidate.title,
            "artist": candidate.artist, "score": round(score, 1),
        }

    def maybe(self, service: str, song_key: str) -> dict | None:
        return self._data["services"].get(service, {}).get("maybe", {}).get(song_key)

    def clear_maybe(self, service: str, song_key: str) -> None:
        self._data["services"].get(service, {}).get("maybe", {}).pop(song_key, None)

    def keys_with_status(self, service: str, status: str) -> list[str]:
        songs = self._data["services"].get(service, {}).get("songs", {})
        return [key for key, value in songs.items() if value == status]

    def reset_service(self, service: str) -> None:
        """Forget one service's playlist and results; other services are untouched."""
        self._data["services"].pop(service, None)

    def save(self) -> None:
        """Write to a sibling temp file, then atomically replace the real file."""
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, self.path)
