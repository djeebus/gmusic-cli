import os
import os.path
import pytest
import tempfile
import unittest.mock
import uuid


@pytest.fixture(name='api')
def _api():
    return unittest.mock.Mock()


@pytest.fixture(name='library_factory')
def _library(request, api):
    def library_factory(tracks):
        from gmusic_cli.library import TrackLibrary

        library_json_fname = tempfile.mktemp()

        def cleanup():
            if os.path.exists(library_json_fname):
                os.unlink(library_json_fname)

        request.addfinalizer(cleanup)

        class FakeLibrary(TrackLibrary):
            fname = library_json_fname

        library = FakeLibrary(api)
        library._cache.set(tracks)
        return library
    return library_factory


def test_can_filter_properly(library_factory):
    from gmusic_cli import THUMBS_DOWN_RATING, THUMBS_UP_RATING
    from gmusic_cli.cli.download import filter_tracks

    album_1_name = str(uuid.uuid4())
    album_1_id = str(uuid.uuid4())
    album_1 = {
        'album': album_1_name,
        'albumId': album_1_id,
    }
    album_2_name = str(uuid.uuid4())
    album_2_id = str(uuid.uuid4())
    album_2 = {
        'album': album_2_name,
        'albumId': album_2_id,
    }

    album_1_yes = {
        'id': str(uuid.uuid4()),
        'rating': THUMBS_UP_RATING,
        **album_1,
    }

    album_1_no = {
        'id': str(uuid.uuid4()),
        'rating': THUMBS_DOWN_RATING,
        **album_1,
    }

    from gmusic_cli import NO_RATING
    album_1_meh = {
        'id': str(uuid.uuid4()),
        'rating': NO_RATING,
        **album_1,
    }

    no_album = {
        'id': str(uuid.uuid4()),
    }

    album_2_yes = {
        'id': str(uuid.uuid4()),
        'rating': THUMBS_UP_RATING,
        **album_2,
    }

    album_2_meh = {
        'id': str(uuid.uuid4()),
        'rating': NO_RATING,
        **album_2,
    }

    library = library_factory([
        album_1_yes,
        album_1_no,
        album_1_meh,
        album_2_yes,
        album_2_meh,
        no_album,
    ])

    # filter by thumbs up
    tracks = filter_tracks(
        library, only_thumbs_up=True,
    )
    track_1, track_2 = tracks
    assert track_1 == album_1_yes
    assert track_2 == album_2_yes

    # filter by album name
    tracks = filter_tracks(
        library, album=album_1_name,
    )
    track_1, track_2 = tracks

    assert track_1 == album_1_yes
    assert track_2 == album_1_meh

    # filter by album, allow thumbs down
    tracks = filter_tracks(
        library, album=album_1_name, allow_thumbs_down=True,
    )
    track_1, track_2, track_3 = tracks

    assert track_1 == album_1_yes
    assert track_2 == album_1_no
    assert track_3 == album_1_meh

    # filter by album and thumbs up
    tracks = filter_tracks(
        library, album=album_1_name, only_thumbs_up=True,
    )
    track_1, = tracks

    assert track_1 == album_1_yes

    # filter by album score
    tracks = filter_tracks(
        library, min_album_rating=1,
    )
    track_1, track_2 = tracks
    assert track_1 == album_2_yes
    assert track_2 == album_2_meh
