import json
import os.path


def is_uploaded(track):
    client_id = track.get('clientId')
    if not client_id:
        return False

    if '-' in client_id:
        return False

    return True


class TrackLibrary:
    fname = '~/.gmusic/tracks.json'

    def __init__(self, api):
        self._api = api
        self._cache = TrackCache(self.fname)

    def _download_tracks(self):
        results = self._api.get_all_songs(
            incremental=True,
            include_deleted=False,
        )

        for index, page in enumerate(results):
            for track_info in page:
                yield track_info

            print("Done with page %s" % (index + 1))

    @property
    def _cached_tracks(self):
        return self._cache.get()

    def refresh(self):
        new_tracks = []
        new_tracks += self._download_tracks()
        self._cache.set(new_tracks)

    def get_tracks(self):
        yield from self._cached_tracks

    def __iter__(self):
        yield from self.get_tracks()

    def __len__(self):
        tracks = self._cache.get()
        return len(tracks)


class TrackCache:
    def __init__(self, fname):
        self.fname = self._path(fname)
        self._local = None

    @staticmethod
    def _path(fname):
        fname = os.path.expanduser(fname)
        fname = os.path.abspath(fname)
        return fname

    def get(self):
        if self._local is not None:
            return self._local

        if not os.path.isfile(self.fname):
            return

        with open(self.fname, 'r') as f:
            self._local = json.load(f)

        return self._local

    def set(self, value):
        with open(self.fname, 'w') as f:
            json.dump(value, f)

        self._local = value
