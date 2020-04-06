import click
import functools
import gmusicapi
import itertools
import os
import pprint
import re
import requests
import requests.packages
import time

from gmusic_cli.cli.download import (
    cli as download_cli,
    THUMBS_UP_RATING,
)
from gmusic_cli.youtube import YoutubeClient
from gmusic_cli.config import get_config, set_config
from gmusic_cli.library import TrackLibrary, is_uploaded
from googleapiclient.errors import HttpError

youtube_api_key = 'AIzaSyCl5XXa40qM6JmJ3YU6HGpttyrI1dnyCq4'


class AuthError(Exception):
    pass


class LazyApiLoginWrapper:
    def __init__(
        self, client: gmusicapi.Mobileclient, cred_path,
    ):
        self._client = client
        self._cred_path = cred_path
        self._authenticated = False

    def validate(self):
        try:
            result = self._client.oauth_login(
                device_id='AA:BB:CC:11:22:33',
                oauth_credentials=self._cred_path,
            )
        except gmusicapi.exceptions.InvalidDeviceId as e:
            result = self._client.oauth_login(
                device_id=e.valid_device_ids[0],
                oauth_credentials=self._cred_path,
            )

        if not result:
            raise AuthError()

    def __getattr__(self, item):
        if not self._authenticated:
            try:
                self.validate()
                self._authenticated = True
            except AuthError:
                print("Failed to login to mobile client")
                exit(1)

        return self._client.__getattribute__(item)


class LazyManagerLoginWrapper:
    def __init__(self, client: gmusicapi.Musicmanager, cred_path):
        self._authenticated = False
        self._client = client
        self.cred_path = cred_path

    def validate(self):
        if not self._client.login(
            oauth_credentials=self.cred_path,
        ):
            raise AuthError()

    def __getattr__(self, item):
        if not self._authenticated:
            try:
                self.validate()
                self._authenticated = True
            except:
                print("Failed to login to manager")
                exit(1)

        return self._client.__getattribute__(item)


@click.group()
@click.option('--config', default='~/.config/gmusic/')
@click.pass_context
def cli(ctx, config):
    config_dir = os.path.expanduser(config)
    config_dir = os.path.abspath(config_dir)

    os.makedirs(config_dir, exist_ok=True)

    manager_oauth_cred_path = os.path.join(config_dir, 'oauth.manager.json')
    mobile_oauth_cred_path = os.path.join(config_dir, 'oauth.mobile.json')
    config_path = os.path.join(config_dir, CONFIG_FNAME)

    config = get_config(config_path)

    api = gmusicapi.Mobileclient()
    mgr = gmusicapi.Musicmanager()

    api = LazyApiLoginWrapper(api, mobile_oauth_cred_path)
    mgr = LazyManagerLoginWrapper(mgr, manager_oauth_cred_path)
    requests.packages.urllib3.disable_warnings()

    library = TrackLibrary(api)

    ctx.obj = {
        'api': api,
        'tracks': library,
        'config': config,
        'config_path': config_path,
        'mobile_oauth_path': mobile_oauth_cred_path,
        'manager_oauth_path': manager_oauth_cred_path,
        'mgr': mgr
    }


cli.command('download')(download_cli)


@cli.command('refresh')
@click.pass_context
def refresh(ctx):
    library: TrackLibrary = ctx.obj['tracks']
    library.refresh()


CONFIG_FNAME = 'config.yaml'


@cli.command('validate')
@click.option('--open-browser/--no-open-browser', default=True)
@click.pass_context
def validate(ctx, open_browser):
    config = ctx.obj['config']
    config_path = ctx.obj['config_path']
    mobile_oauth_cred_path = ctx.obj['mobile_oauth_path']
    manager_oauth_cred_path = ctx.obj['manager_oauth_path']

    click.echo("Testing mobile client credentials ... ")

    creds_changed = False
    while True:
        try:
            ctx.obj['api'].validate()
            break
        except AuthError:
            _fix_api_creds(mobile_oauth_cred_path, open_browser)
            creds_changed = True

    if creds_changed:
        click.echo("Saving credentials ...")
        set_config(config_path, config)

    click.echo("Testing music manager credentials ...")
    while True:
        try:
            ctx.obj['mgr'].validate()
            break
        except AuthError:
            _fix_mgr_creds(manager_oauth_cred_path, open_browser)

    click.echo("Credentials are valid!")


def _fix_api_creds(oauth_cred_path, open_browser):
    click.echo("Using oauth to login to music manager ... ")
    mgr = gmusicapi.Mobileclient()
    mgr.perform_oauth(
        open_browser=open_browser,
        storage_filepath=oauth_cred_path,
    )


def _fix_mgr_creds(oauth_cred_path, open_browser):
    click.echo("Using oauth to login to music manager ... ")
    mgr = gmusicapi.Musicmanager()
    mgr.perform_oauth(
        open_browser=open_browser,
        storage_filepath=oauth_cred_path,
    )


@cli.command('uploaded')
@click.pass_context
def uploaded(ctx):
    tracks = ctx.obj['tracks']

    uploaded_tracks = []
    total_bytes = 0
    for t in filter(is_uploaded, tracks):
        uploaded_tracks.append(t)
        total_bytes += int(t['estimatedSize'])

    print("uploaded: %s / %s" % (len(uploaded_tracks), len(tracks)))
    print('total size: %s GB' % (total_bytes / 1024 / 1024 / 1024))


def _format_query(track):
    parts = [
        track['artist'],
        track['title'],
    ]

    return ' '.join(
        p for p in parts if p
    )


def _get_best_result(expected, results):
    if not results['song_hits']:
        return

    non_chars = re.compile(r'^[a-z0-9]', re.IGNORECASE)

    def clean(t):
        return non_chars.sub(t, '')

    for song_hit in results['song_hits']:
        track = song_hit['track']

        match_keys = ['artist', 'album', 'title']

        def is_match(k):
            return clean(track[k]) == clean(expected[k])

        if all(map(is_match, match_keys)):
            return track


@cli.command('match-tracks')
@click.pass_context
def match_tracks(ctx):
    tracks = ctx.obj['tracks']
    api = ctx.obj['api']
    downloaded_tracks = filter(is_uploaded, tracks)
    sorted_tracks = sorted(downloaded_tracks, key=lambda t: t['artist'])
    for track in sorted_tracks:
        track_description = '%s - %s' % (
            track['artist'], track['title'],
        )

        query = _format_query(track)
        results = api.search(query)

        best_result = _get_best_result(track, results)
        if not best_result:
            print("no result for '%s'" % track_description)
            continue

        try:
            api.delete_songs(track['id'])
        except gmusicapi.exceptions.CallFailure:
            print("failed to delete '%s'" % track_description)
            continue

        print("adding '%s - %s'"
              % (best_result['artist'], best_result['title']))
        api.add_store_track(best_result['storeId'])


@cli.command('videos')
@click.pass_context
def videos(ctx):
    tracks = ctx.obj['tracks']

    videos = []
    video_types = set()
    for t in tracks:
        if 'primaryVideo' in t:
            video = t['primaryVideo']
            videos.append(video)
            video_types.add(video['kind'])

    import pprint
    pprint.pprint(videos)
    pprint.pprint(video_types)


@cli.command('years')
@click.pass_context
def years(ctx):
    tracks = ctx.obj['tracks']

    year_key = lambda t: t.get('year', 0)
    tracks = sorted(tracks, key=year_key)

    tracks_by_year = itertools.groupby(
        tracks, key=year_key,
    )
    tracks_by_year = [
        (year, sum(1 for t in tracks))
        for year, tracks in tracks_by_year
        if year
    ]

    draw_chart(tracks_by_year)


@cli.command('genres')
@click.pass_context
def genres(ctx):
    tracks = ctx.obj['tracks']

    # sort, group and count by genre
    genre_key = lambda t: t.get('genre', '')
    tracks = sorted(tracks, key=genre_key)
    tracks_by_genre = itertools.groupby(tracks, key=genre_key)
    tracks_by_genre = [
        (genre, sum(1 for t in tracks))
        for genre, tracks in tracks_by_genre
        if genre
    ]

    # justify first columns
    max_width = max(len(genre) for genre, count in tracks_by_genre)
    tracks_by_genre = [
        (genre.ljust(max_width), count)
        for genre, count in tracks_by_genre
    ]

    tracks_by_genre = sorted(tracks_by_genre, key=lambda gc: gc[1])

    draw_chart(tracks_by_genre)


@cli.group('export')
@click.pass_context
@click.option('--thumbs-up', help='export thumbs up playlist', is_flag=True)
def export(ctx, thumbs_up):
    tracks = ctx.obj['tracks']
    if thumbs_up:
        tracks = [
            t for t in tracks
            if t.get('rating') == THUMBS_UP_RATING
        ]
    ctx.obj['filtered'] = tracks


@export.command('to-youtube')
@click.argument('playlist_name')
@click.pass_context
def to_youtube(ctx, playlist_name):
    tracks = ctx.obj['filtered']
    print("%s tracks" % len(tracks))

    config = ctx.obj['config']

    client = YoutubeClient(config.username,
                           config.password)

    playlists = client.get_playlists()

    export_playlist = None
    for p in playlists:
        title = p['snippet']['localized']['title']
        if title == playlist_name:
            export_playlist = p

    if not export_playlist:
        export_playlist = client.create_playlist(playlist_name)

    playlist_items = client.get_playlist_items(export_playlist)
    playlist_items = list(playlist_items)

    existing_youtube_ids = {
        playlist_item['snippet']['resourceId']['videoId']
        for playlist_item in playlist_items
    }
    print('playlist has %s tracks' % len(playlist_items))

    def is_yt_track(track):
        if 'primaryVideo' not in track:
            return False

        return track['primaryVideo']['kind'] == 'sj#video'

    song_youtube_ids = [
        track['primaryVideo']['id']
        for track in tracks
        if is_yt_track(track)
    ]
    print('music library has %s tracks with videos'
          % len(song_youtube_ids))

    for song_youtube_id in song_youtube_ids:
        if song_youtube_id in existing_youtube_ids:
            continue

        add_video_to_playlist(client, export_playlist, song_youtube_id)
        existing_youtube_ids.add(song_youtube_id)


def add_video_to_playlist(client, mtv_playlist, song_youtube_id):
    print("adding %s" % song_youtube_id)
    try:
        client.insert_playlist_item(
            mtv_playlist, song_youtube_id,
        )
    except HttpError as e:
        print("error %s" % e)
        time.sleep(1)


def draw_chart(data, max_width=50):
    max_data = max(data, key=lambda d: d[1])[1]
    data_per_pixel = int(max_data / max_width)

    for label, value in data:
        if data_per_pixel == 0:
            continue
        pixels = '▇' * int(value / data_per_pixel)
        print('{k:4} | {v}'.format(k=label, v=pixels))


def get_device_id(api: gmusicapi.Mobileclient):
    devices = api.get_registered_devices()
    # TODO: sort devices by the last accessed time, grab the most recent
    for device in devices:
        if device['type'] != 'ANDROID':
            continue

        return device['id'].lstrip('0x')

    raise Exception('could not find an android device id')


@cli.command()
@click.option('--artist')
@click.pass_context
@click.option('--download', type=click.Path(file_okay=False))
def search(ctx, artist, download):
    query = filter(None, (artist,))
    query = ' '.join(query)

    api: gmusicapi.Mobileclient = ctx.obj['api']
    results = api.search(query)

    if artist:
        print('Artists:')
        for artist_result in results['artist_hits']:
            artist_info = artist_result['artist']
            print(f'\t{artist_info["name"]} [{artist_info["artistId"]}]')

    pprint.pprint(results.keys())
    exit(1)


if __name__ == '__main__':
    cli()
