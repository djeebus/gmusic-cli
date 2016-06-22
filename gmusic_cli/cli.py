import click
import gmusicapi
import itertools
import re
import requests
import requests.packages

from gmusic_cli.config import get_config
from gmusic_cli.library import TrackLibrary, is_downloaded


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
    for track in filter(is_downloaded, tracks):
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


def draw_chart(data, max_width=50):
    max_data = max(data, key=lambda d: d[1])[1]
    data_per_pixel = int(max_data / max_width)

    for label, value in data:
        pixels = '▇' * int(value / data_per_pixel)
        print('{k:4} | {v}'.format(k=label, v=pixels))
