"""Fuzzy matching: decide whether a search result is really the iPod song."""
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from ipod2playlist.library import Song

_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_REMASTER_SUFFIX = re.compile(r"\s-\s[^-]*remaster.*$")
_FEATURING = re.compile(r"\b(feat|ft|featuring)\b.*$")
_PUNCTUATION = re.compile(r"[^\w\s]|_")


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    artist: str


def normalize(text: str) -> str:
    """Lowercase, accent-free text without bracketed/remaster/feat. noise or punctuation."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _BRACKETED.sub(" ", text)
    text = _REMASTER_SUFFIX.sub("", text)
    text = _FEATURING.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    return " ".join(text.split())


def score(song: Song, candidate: Candidate) -> float:
    """0..100: 60% title similarity + 40% artist similarity.

    Spotify gives clean fields; YouTube gives "Artist - Song (Official Video)" and a
    channel like "ArtistVEVO" / "Artist - Topic". So the title may also match as
    "<artist> <title>", and the artist matches if it appears inside the channel name.
    """
    title, artist = normalize(song.title), normalize(song.artist)
    cand_title, cand_artist = normalize(candidate.title), normalize(candidate.artist)
    title_sim = max(
        fuzz.ratio(title, cand_title),
        fuzz.ratio(f"{artist} {title}", cand_title),
    )
    artist_sim = fuzz.partial_ratio(artist, cand_artist)
    return 0.6 * title_sim + 0.4 * artist_sim


def best_match(
    song: Song, candidates: list[Candidate], threshold: float = 80
) -> Candidate | None:
    """The highest-scoring candidate at or above the threshold, else None."""
    best = max(candidates, key=lambda c: score(song, c), default=None)
    if best is not None and score(song, best) >= threshold:
        return best
    return None
