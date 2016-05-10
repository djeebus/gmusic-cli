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


@cli.command('years')
@click.pass_context
def years(ctx):
    tracks = ctx.obj['tracks']

    year_key = lambda t: t.get('year', 0)
    tracks = sorted(tracks, key=year_key)

    tracks_by_year = itertools.groupby(
        tracks, key=year_key,
    )

    for year, tracks in tracks_by_year:
        track_count = sum(1 for t in tracks)
        print("%s: %s" % (year, track_count))
