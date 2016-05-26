import click
import gmusicapi
import itertools
import requests
import requests.packages

from gmusic_cli.config import get_config
from gmusic_cli.library import TrackLibrary


@click.group()
@click.option('--config', default='~/.gmusic/config.yaml')
@click.pass_context
def cli(ctx, config):
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

    tracks = library.get_tracks()
    ctx.obj = {
        'api': api,
        'tracks': tracks,
    }


@cli.command('downloaded')
@click.pass_context
def downloaded(ctx):
    tracks = ctx.obj['tracks']

    downloaded = []
    bytes = 0
    for t in tracks:
        client_id = t.get('clientId')
        if client_id and '-' not in client_id:
            downloaded.append(t)
            bytes += int(t['estimatedSize'])

    print("downloaded: %s / %s"
          % (len(downloaded), len(tracks)))
    print('total size: %s GB'
          % (bytes / 1024 / 1024 / 1024))

    # key_func = lambda t: t['kind']
    # tracks = sorted(tracks, key=key_func)
    # grouped_tracks = itertools.groupby(tracks, key=key_func)
    # for kind, tracks in grouped_tracks:
    #     count = len(list(tracks))
    #     print("%s: %s" % (kind, count))


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
    data_per_pixel = int(max_data/max_width)

    for label, value in data:
        # import pdb; pdb.set_trace()
        format = "{k:4} | {v}"
        pixels = '▇' * int(value / data_per_pixel)
        print(format.format(k=label, v=pixels))
