"""Fuzzy matching: decide whether a search result is really the iPod song."""
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from ipod2playlist.library import Song

# Bracketed text is dropped only when it is noise; "(Live ...)" or "(Karaoke ...)" stays.
_NOISE_WORDS = r"remaster(ed)?|feat|ft|featuring|official|video|audio|lyrics?|hd|explicit"
_BRACKETED_NOISE = re.compile(rf"\([^)]*\b({_NOISE_WORDS})\b[^)]*\)|\[[^\]]*\b({_NOISE_WORDS})\b[^\]]*\]")
_REMASTER_SUFFIX = re.compile(r"\s-\s[^-]*remaster.*$")
_FEATURING = re.compile(r"\b(feat|ft|featuring)\b.*$")
_PUNCTUATION = re.compile(r"[^\w\s]|_")
_CHANNEL_SUFFIX = re.compile(r"(\s*(vevo|topic|official))+$")
_DIGITS = re.compile(r"\d+")
_VERSION_WORDS = re.compile(r"\b(live|karaoke|cover|acoustic|instrumental|remix|demo)\b")


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    artist: str


def normalize(text: str) -> str:
    """Lowercase, accent-free text without bracketed/remaster/feat. noise or punctuation."""
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = _BRACKETED_NOISE.sub(" ", text)
    text = _REMASTER_SUFFIX.sub("", text)
    text = _FEATURING.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    return " ".join(text.split())


def score(song: Song, candidate: Candidate) -> float:
    """0..100. The artist is a gate, the title is the score.

    A wrong song by the right artist or a cover by someone else must not pass, so
    the artist has to match first: the channel name (minus "VEVO"/"Topic"/"Official")
    is close to it, or it appears as whole words in the title ("Artist - Song" on a
    label channel). Then the score is the title similarity, with a leading "Artist -"
    removed from YouTube titles. Titles with different numbers ("Song 2" vs "Song 3")
    score 0, and so do titles with different version words (live, karaoke, remix...).
    """
    title, artist = normalize(song.title), normalize(song.artist)
    cand_title = normalize(candidate.title)
    channel = _CHANNEL_SUFFIX.sub("", normalize(candidate.artist))
    in_title = bool(artist) and re.search(rf"\b{re.escape(artist)}\b", cand_title)
    if fuzz.ratio(artist, channel) < 85 and not in_title:
        return 0
    cand_title = cand_title.removeprefix(artist + " ")
    if set(_DIGITS.findall(title)) != set(_DIGITS.findall(cand_title)):
        return 0
    # Version tags are read from the raw titles: normalize drops "(Official Live Video)".
    if set(_VERSION_WORDS.findall(song.title.casefold())) != set(
        _VERSION_WORDS.findall(candidate.title.casefold())
    ):
        return 0
    return fuzz.ratio(title, cand_title)


def best_match(
    song: Song, candidates: list[Candidate], threshold: float = 80
) -> Candidate | None:
    """The highest-scoring candidate at or above the threshold, else None."""
    best = max(candidates, key=lambda c: score(song, c), default=None)
    if best is not None and score(song, best) >= threshold:
        return best
    return None
