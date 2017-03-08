import click
import gmusicapi
import itertools
import re
import requests
import requests.packages
import time

from gmusic_cli.youtube import YoutubeClient
from gmusic_cli.config import get_config
from gmusic_cli.library import TrackLibrary, is_downloaded
from googleapiclient.errors import HttpError

youtube_api_key = 'AIzaSyCl5XXa40qM6JmJ3YU6HGpttyrI1dnyCq4'


@click.group()
@click.option('--config', default='~/.gmusic/config.yaml')
@click.option('--cache/--no-cache', default=True, is_flag=True)
@click.pass_context
def cli(ctx, config, cache):
    config = get_config(config)

    api = gmusicapi.Mobileclient(validate=True, verify_ssl=True)
    requests.packages.urllib3.disable_warnings()

    if not api.login(
        config.username,
        config.password,
        config.device_id,
    ):
        print("Failed to login")
        exit(1)

    print("successfully logged in")

    library = TrackLibrary(api)

    tracks = library.get_tracks(cache)
    ctx.obj = {
        'api': api,
        'tracks': tracks,
        'config': config,
    }


@cli.command('downloaded')
@click.pass_context
def downloaded(ctx):
    tracks = ctx.obj['tracks']

    downloaded_tracks = []
    total_bytes = 0
    for t in filter(is_downloaded, tracks):
        downloaded_tracks.append(t)
        total_bytes += int(t['estimatedSize'])

    print("downloaded: %s / %s"
          % (len(downloaded_tracks), len(tracks)))
    print('total size: %s GB'
          % (total_bytes / 1024 / 1024 / 1024))


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
    downloaded_tracks = filter(is_downloaded, tracks)
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
            if t.get('rating') == '5'
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
