from ipod2playlist.matching import Candidate, best_match, normalize


def song(title, artist):
    from ipod2playlist.library import Song

    return Song(title=title, artist=artist, album="", path="")


def cand(title, artist, id="x"):
    return Candidate(id=id, title=title, artist=artist)


def test_exact_title_and_artist_match():
    assert best_match(song("Creep", "Radiohead"), [cand("Creep", "Radiohead")])


def test_remaster_suffixes_are_ignored_in_either_field():
    assert best_match(song("Song (Remastered 2009)", "Band"), [cand("Song", "Band")])
    assert best_match(song("Song", "Band"), [cand("Song - 2011 Remaster", "Band")])


def test_featuring_credit_is_ignored():
    assert best_match(song("Song (feat. X)", "Band"), [cand("Song", "Band")])
    assert best_match(song("Song", "Band"), [cand("Song ft. Y", "Band")])


def test_accents_are_ignored():
    assert best_match(song("Jóga", "Björk"), [cand("Joga", "Bjork")])


def test_same_title_different_artist_is_no_match():
    assert best_match(song("Hello", "Adele"), [cand("Hello", "Lionel Richie")]) is None


def test_different_title_same_artist_is_no_match():
    assert best_match(song("Creep", "Radiohead"), [cand("Karma Police", "Radiohead")]) is None


def test_youtube_video_title_and_vevo_channel_match():
    video = cand("Radiohead - Karma Police (Official Video)", "RadioheadVEVO")
    assert best_match(song("Karma Police", "Radiohead"), [video])


def test_youtube_topic_channel_matches():
    topic = cand("Karma Police", "Radiohead - Topic")
    assert best_match(song("Karma Police", "Radiohead"), [topic])


def test_best_match_picks_the_higher_scorer():
    wanted = song("Karma Police", "Radiohead")
    candidates = [
        cand("Karma Police (Live)", "Some Cover Band", id="cover"),
        cand("Karma Police", "Radiohead", id="right"),
    ]
    assert best_match(wanted, candidates).id == "right"


def test_best_match_of_no_candidates_is_none():
    assert best_match(song("Creep", "Radiohead"), []) is None


def test_normalize_strips_noise():
    assert normalize("Jóga (Live) (Official Video) - 2009 Remaster feat. X!") == "joga live"


def test_cover_of_same_title_by_another_artist_is_no_match():
    assert best_match(song("Hurt", "Nine Inch Nails"), [cand("Hurt", "Johnny Cash")]) is None


def test_artist_name_inside_a_longer_channel_name_is_no_match():
    channel = cand("One", "Beautiful Musicals 2U2")
    assert best_match(song("One", "U2"), [channel]) is None


def test_karaoke_version_is_no_match():
    karaoke = cand("Karma Police (Karaoke Version)", "Radiohead Karaoke")
    assert best_match(song("Karma Police", "Radiohead"), [karaoke]) is None


def test_live_version_is_no_match():
    live = cand("Karma Police (Live at Glastonbury)", "Radiohead")
    assert best_match(song("Karma Police", "Radiohead"), [live]) is None


def test_different_number_in_title_is_no_match():
    assert best_match(song("Song 2", "Blur"), [cand("Song 3", "Blur")]) is None


def test_label_channel_matches_when_artist_is_in_the_title():
    label = cand("Radiohead - Karma Police (Official Audio)", "XL Recordings")
    assert best_match(song("Karma Police", "Radiohead"), [label])


def test_live_tag_on_candidate_only_is_no_match():
    live = cand("Karma Police (Live)", "Radiohead")
    assert best_match(song("Karma Police", "Radiohead"), [live]) is None


def test_official_live_video_is_no_match_for_studio_song():
    live = cand("Radiohead - Karma Police (Official Live Video)", "Radiohead")
    assert best_match(song("Karma Police", "Radiohead"), [live]) is None


def test_live_song_matches_its_live_version():
    live = cand("Karma Police - Live", "Radiohead")
    assert best_match(song("Karma Police (Live)", "Radiohead"), [live])


def test_multi_artist_spotify_track_matches_any_listed_artist():
    assert best_match(song("Umbrella", "Rihanna"), [cand("Umbrella", "Rihanna, JAY-Z")])
    assert best_match(song("Under Pressure", "Queen"), [cand("Under Pressure", "Queen, David Bowie")])
    assert best_match(
        song("Empire State of Mind", "Jay-Z feat. Alicia Keys"),
        [cand("Empire State of Mind", "JAY-Z, Alicia Keys")],
    )


def test_multi_artist_track_without_the_artist_is_no_match():
    assert best_match(song("Hello", "Adele"), [cand("Hello", "Lionel Richie, Diana Ross")]) is None


def test_extra_live_word_in_candidate_title_is_no_match():
    mine = song("Live and Let Die", "Paul McCartney & Wings")
    assert best_match(mine, [cand("Live and Let Die (Live)", "Paul McCartney & Wings")]) is None


def test_band_named_live_matches_its_studio_video():
    mine = song("Lightning Crashes", "Live")
    assert best_match(mine, [cand("Live - Lightning Crashes (Official Video)", "LiveVEVO")])


def test_band_named_live_still_rejects_the_live_version():
    mine = song("Lightning Crashes", "Live")
    assert best_match(mine, [cand("Live - Lightning Crashes (Live at Woodstock)", "LiveVEVO")]) is None


def test_4k_tag_is_noise():
    assert best_match(
        song("Song 2", "Blur"), [cand("Blur - Song 2 (Official Music Video) [4K]", "Blur")]
    )


def test_bracketed_year_is_noise():
    assert best_match(
        song("Bohemian Rhapsody", "Queen"), [cand("Queen - Bohemian Rhapsody (1975)", "Queen Official")]
    )


def test_bare_year_number_still_gates():
    assert best_match(song("1999", "Prince"), [cand("1998", "Prince")]) is None


def test_leading_the_is_ignored_in_the_artist_gate_both_ways():
    assert best_match(song("Let It Be", "Beatles"), [cand("Let It Be", "The Beatles")])
    assert best_match(song("Let It Be", "The Beatles"), [cand("Let It Be", "Beatles")])


def test_dropping_the_does_not_open_the_artist_gate():
    assert best_match(song("Hello", "The Beatles"), [cand("Hello", "The Beat")]) is None


def test_partial_title_overlap_is_no_match():
    mine = song("Yesterday", "The Carpenters")
    assert best_match(mine, [cand("Yesterday Once More", "The Carpenters")]) is None
