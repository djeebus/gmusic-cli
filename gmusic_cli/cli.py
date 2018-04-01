import click
import collections
import gmusicapi
import itertools
import mutagen.id3
import os
import re
import requests
import requests.packages
import time
import unicodedata
import urllib.request

from gmusic_cli.youtube import YoutubeClient
from gmusic_cli.config import get_config
from gmusic_cli.library import TrackLibrary, is_uploaded
from googleapiclient.errors import HttpError

device_id = '0011221122334455'
youtube_api_key = 'AIzaSyCl5XXa40qM6JmJ3YU6HGpttyrI1dnyCq4'

THUMBS_UP_RATING = '5'
THUMBS_DOWN_RATING = '1'


class LazyApiLoginWrapper:

    def __init__(self, client, config):
        self._client = client
        self._config = config
        self._authenticated = False

    def __getattr__(self, item):
        if not self._authenticated:
            self._authenticated = self._client.login(
                self._config.username,
                self._config.password,
                self._config.device_id,
            )

            if not self._authenticated:
                print("Failed to login")
                exit(1)

            print("successfully logged in")

        return self._client.__getattribute__(item)


class LazyManagerLoginWrapper:
    def __init__(self, client):
        self._authenticated = False
        self._client = client

    def __getattr__(self, item):
        if not self._authenticated:
            success = self._client.login()

            if not success:
                self._client.perform_oauth()
                exit(1)

            self._authenticated = True

        return self._client.__getattribute__(item)


@click.group()
@click.option('--config', default='~/.gmusic/config.yaml')
@click.option('--cache/--no-cache', default=True, is_flag=True)
@click.pass_context
def cli(ctx, config, cache):
    config = get_config(config)

    api = gmusicapi.Mobileclient()
    mgr = gmusicapi.Musicmanager()

    api = LazyApiLoginWrapper(api, config)
    mgr = LazyManagerLoginWrapper(mgr)
    requests.packages.urllib3.disable_warnings()

    library = TrackLibrary(api)

    tracks = library.get_tracks(cache)
    ctx.obj = {
        'api': api,
        'tracks': tracks,
        'config': config,
        'mgr': mgr
    }


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


@cli.command()
@click.option('--artist')
@click.option('--album')
@click.option('--thumbs-up', is_flag=True)
@click.option('--good-albums', is_flag=True)
@click.option('--min-album-rating', default=5)
@click.argument('destination')
@click.pass_context
def download(
    ctx,  artist, album, destination, thumbs_up, good_albums, min_album_rating,
):
    tracks = ctx.obj['tracks']

    if good_albums:
        album_ratings = collections.defaultdict(int)
        tracks_by_album_id = collections.defaultdict(list)
        for track in tracks:
            aid = track.get('albumId')
            if not aid:
                continue

            if track.get('rating') == THUMBS_UP_RATING:
                album_ratings[aid] += 1
            tracks_by_album_id[aid].append(track)

    def is_match(track):
        if track.get('rating') == THUMBS_DOWN_RATING:
            return False

        if thumbs_up and track.get('rating') != THUMBS_UP_RATING:
            return False

        if artist and track.get('albumArtist', '').lower() != artist.lower():
            return False

        if album and track.get('album', '').lower() != album.lower():
            return False

        album_id = track.get('albumId')
        if good_albums:
            if not album_id:
                return False

            rating = album_ratings[album_id]
            if rating < min_album_rating:
                return False

        return True

    tracks = filter(is_match, tracks)
    tracks = list(tracks)

    print("Downloading %s tracks ... " % len(tracks))

    track_fnames = (
        (track, get_file_name(track))
        for track in tracks
    )

    missing_tracks = [
        (t, fname, os.path.join(destination, fname))
        for t, fname in track_fnames
        if not os.path.exists(fname)
    ]

    for index, (track, fname, full_path) in enumerate(missing_tracks, start=1):
        """Couldn't find a consistent way to differentiate between uploaded 
        tracks and store tracks, just try one, then the other"""

        dirname = os.path.dirname(full_path)
        os.makedirs(dirname, exist_ok=True)

        print(f'downloading {index}/{len(missing_tracks)}: {fname}')

        try:
            if 'nid' in track:
                download_store_track(ctx.obj['api'], full_path, track)
                success = True
            else:
                success = False
        except Exception as e:
            print('\terror getting store track, trying for user track: %s' % e)
            success = False

        if not success:
            try:
                download_user_track(ctx.obj['mgr'], full_path, track)
            except Exception as e:
                print('\terror getting user track: %s' % e)
                continue

        set_metadata(full_path, track)


invalid_chars = \
    ['"', '<', '>', '|', ':', '*', '?', '\\', '/'] + \
    list(map(chr, range(0, 0x1F)))


def _clean_file_name(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens.
    """
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore')
    value = value.decode('ascii')
    value = value.strip()
    value = ''.join(c for c in value if c not in invalid_chars)
    return value


def get_file_name(track):
    artist = track.get('albumArtist')
    is_compilation_album = artist == 'Various Artists'
    if not artist or is_compilation_album:
        artist = track.get('artist')
    if not artist:
        artist = 'Unknown artist'
    if artist == 'Christoper Titus':
        artist = 'Christopher Titus'
    artist = _clean_file_name(artist)

    title = track.get('title')
    if not title:
        title = 'Unnamed track'
    title = _clean_file_name(title)

    track_number = track.get('trackNumber', 0)
    year = track.get('year', 0)
    album = _clean_file_name(track.get('album'))

    if is_compilation_album:
        if year:
            format_string = u'{album} [{year}]{sep}{track:02d} - {artist} - {title}.mp3'
        else:
            format_string = u'{album}{sep}{track:02d} - {artist} - {title}.mp3'
    else:
        if year and album:
            format_string = u'{artist}{sep}[{year}] {album}{sep}{track:02d} - {title}.mp3'
        elif album:
            format_string = u'{artist}{sep}{album}{sep}{track:02d} - {title}.mp3'
        else:
            format_string = u'{artist}{sep}{title}.mp3'

    magic_sep = '!@#@!'
    file_name = format_string.format(
        artist=artist.rstrip('.'),
        year=year,
        title=title,
        track=track_number,
        album=album.rstrip('.'),
        sep=magic_sep,
    )
    parts = file_name.split(magic_sep)
    file_name = os.path.join(*parts)

    return file_name


def set_metadata(fname, track):
    try:
        tags = mutagen.id3.ID3(fname)
    except mutagen.id3.ID3NoHeaderError:
        tags = mutagen.id3.ID3()

    def _set_text(clazz, text):
        def _coerce_text(ugly_text):
            if not isinstance(ugly_text, str):
                ugly_text = str(ugly_text)

            return ugly_text

        def _create_text_clazz(data):
            return clazz(encoding=3, text=data)

        return _set_or_add_tag(clazz, text, _create_text_clazz, _coerce_text)

    def _set_image(name, image_refs):
        image_ref_url = image_refs[0]['url'] if image_refs else None

        def _create_image_clazz(url):
            fd = urllib.request.urlopen(url)
            data = fd.read()

            return mutagen.id3.APIC(
                encoding=3,
                mime='image/jpeg',
                desc=name,
                type=3,
                data=data,
            )

        return _set_or_add_tag('APIC:%s' % name, image_ref_url, _create_image_clazz)

    def _set_or_add_tag(tag_name, data, create_tag, coerce_data=None):
        info = tags.get(tag_name)
        if info:
            if tag_name.startswith('APIC:'):
                return  # these are expensive

            del tags[tag_name]

        if coerce_data:
            data = coerce_data(data)

        if not data:
            return

        tag = create_tag(data)
        tags.add(tag)

    _set_text(mutagen.id3.TDRC, track.get('year'))
    _set_text(mutagen.id3.TIT2, track.get('title'))

    # track number
    _set_text(mutagen.id3.TRCK, track.get('trackNumber'))

    # lead performer
    _set_text(mutagen.id3.TPE1, track.get('albumArtist', track.get('artist')))

    # album title
    _set_text(mutagen.id3.TALB, track.get('album'))

    _set_image('Cover', track.get('albumArtRef'))

    tags.save(fname)


def download_store_track(api, full_path, track):
    stream_url = api.get_stream_url(track['nid'], device_id)
    urllib.request.urlretrieve(stream_url, full_path)


def download_user_track(mgr, full_path, track):
    fname, audio = mgr.download_song(track['id'])

    with open(full_path, 'wb') as fp:
        fp.write(audio)


if __name__ == '__main__':
    cli()
