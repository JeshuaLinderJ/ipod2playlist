"""Errors the services raise and the command line turns into messages."""


class QuotaExceeded(Exception):
    """YouTube's daily API quota is used up; resume tomorrow."""


class PlaylistGone(Exception):
    """The playlist we were adding to no longer exists on the service."""

    def __init__(self, service: str):
        super().__init__(f"{service} playlist no longer exists")
        self.service = service
