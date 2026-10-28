"""Fuzzy matching: decide whether a search result is really the iPod song."""
import re
from collections import Counter
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from ipod2playlist.library import Song

ARTIST_GATE = 85  # minimum artist/channel similarity (0..100)
MATCH_THRESHOLD = 80  # minimum title similarity to accept a candidate
REVIEW_FLOOR = 60  # minimum score to remember a rejected candidate for human review

# Bracketed text is dropped only when it is noise; "(Live ...)" or "(Karaoke ...)" stays.
_NOISE_WORDS = r"remaster(ed)?|feat|ft|featuring|official|video|audio|lyrics?|hd|explicit|4k"
_BRACKETED_NOISE = re.compile(rf"\([^)]*\b({_NOISE_WORDS})\b[^)]*\)|\[[^\]]*\b({_NOISE_WORDS})\b[^\]]*\]")
# A year alone in brackets, "(1975)" or "[2009]", is release noise; a bare "1999" is a title.
_BRACKETED_YEAR = re.compile(r"\((19|20)\d{2}\)|\[(19|20)\d{2}\]")
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
    text = _BRACKETED_YEAR.sub(" ", text)
    text = _REMASTER_SUFFIX.sub("", text)
    text = _FEATURING.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    return " ".join(text.split())


def _without_the(name: str) -> str:
    """Drop one leading "the " so "The Beatles" and "Beatles" compare equal."""
    return name.removeprefix("the ")


def score(song: Song, candidate: Candidate) -> float:
    """0..100. The artist is a gate, the title is the score.

    A wrong song by the right artist or a cover by someone else must not pass, so
    the artist has to match first: the channel name or any one of its comma-separated
    names (minus "VEVO"/"Topic"/"Official") is close to it, or it appears as whole words in the title ("Artist - Song" on a
    label channel). Then the score is the title similarity, with a leading "Artist -"
    removed from YouTube titles. Titles with different numbers ("Song 2" vs "Song 3")
    score 0, and so do titles with different version words (live, karaoke, remix...).
    """
    title, artist = normalize(song.title), normalize(song.artist)
    cand_title = normalize(candidate.title)
    if not title or not cand_title:  # two empty titles would score 100 (fuzz.ratio("", "") == 100)
        return 0
    # Spotify joins several artists with commas ("Rihanna, JAY-Z"); any one of them may match.
    names = [candidate.artist, *candidate.artist.split(",")]
    channels = [_CHANNEL_SUFFIX.sub("", normalize(name)) for name in names]
    in_title = bool(artist) and re.search(rf"\b{re.escape(artist)}\b", cand_title)
    gate_artist = _without_the(artist)
    best_channel = max(fuzz.ratio(gate_artist, _without_the(channel)) for channel in channels)
    if best_channel < ARTIST_GATE and not in_title:
        return 0
    cand_title = cand_title.removeprefix(artist + " ")
    if set(_DIGITS.findall(title)) != set(_DIGITS.findall(cand_title)):
        return 0
    # Version tags are read from the raw titles: normalize drops "(Official Live Video)".
    # Counted, not set-compared: "Live and Let Die" must not match "... (Live)". A leading
    # "<artist> - " is removed first so a band named Live does not tag every upload as live.
    raw_cand_title = candidate.title.casefold().removeprefix(song.artist.casefold() + " - ")
    if Counter(_VERSION_WORDS.findall(song.title.casefold())) != Counter(
        _VERSION_WORDS.findall(raw_cand_title)
    ):
        return 0
    return fuzz.ratio(title, cand_title)


def best_match(
    song: Song, candidates: list[Candidate], threshold: float = MATCH_THRESHOLD
) -> Candidate | None:
    """The highest-scoring candidate at or above the threshold, else None."""
    best = max(candidates, key=lambda c: score(song, c), default=None)
    if best is not None and score(song, best) >= threshold:
        return best
    return None


def near_miss(song: Song, candidates: list[Candidate]) -> tuple[Candidate, float] | None:
    """The best candidate scoring in [REVIEW_FLOOR, MATCH_THRESHOLD), else None.

    score() is 0 whenever the artist, number or version gate fails, so every near miss
    already has the right artist and no live/karaoke/remix difference. Only the title is
    a little too different. This is only for remembering; it never adds anything.
    """
    best = max(candidates, key=lambda c: score(song, c), default=None)
    if best is None:
        return None
    best_score = score(song, best)
    if REVIEW_FLOOR <= best_score < MATCH_THRESHOLD:
        return best, best_score
    return None
