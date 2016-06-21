import json
import os.path


def is_downloaded(track):
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

    def _load_cached_tracks(self):
        return self._cache.get()

    def get_tracks(self, use_cache=True):
        if use_cache:
            tracks = self._load_cached_tracks()
            if tracks:
                return tracks

        new_tracks = self._download_tracks()
        new_tracks = list(new_tracks)
        self._cache.set(new_tracks)

        return new_tracks


class TrackCache:
    def __init__(self, fname):
        self.fname = self._path(fname)

    @staticmethod
    def _path(fname):
        fname = os.path.expanduser(fname)
        fname = os.path.abspath(fname)
        return fname

    def get(self):
        if not os.path.isfile(self.fname):
            return

        with open(self.fname, 'r') as f:
            return json.load(f)

    def set(self, value):

        with open(self.fname, 'w') as f:
            json.dump(value, f)
