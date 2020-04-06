import click
import collections
import gmusicapi
import mutagen.id3
import os
import tempfile
import unicodedata
import urllib.request

from gmusic_cli.util import (
    ProgressTimer,
    to,
)

THUMBS_UP_RATING = '5'
THUMBS_DOWN_RATING = '1'


@click.option('--artist')
@click.option('--artist-id', multiple=True)
@click.option('--album')
@click.option('--album-id', multiple=True)
@click.option('--thumbs-up', is_flag=True)
@click.option('--library/--global', is_flag=True, default=True)
@click.option('--min-album-rating', default=0, show_default=True)
@click.option('--char-prefix', is_flag=True)
@click.argument('destination', type=click.Path(file_okay=False))
@click.pass_context
def cli(
    ctx, artist_id, album_id, destination, library, char_prefix, **kwargs,
):
    api: gmusicapi.Mobileclient = ctx.obj['api']

    if library:
        tracks = ctx.obj['tracks']
    else:
        tracks = _get_global_tracks(api, artist_id, album_id)

    filter_tracks = track_filterer_factory(tracks, **kwargs)
    tracks = filter_tracks()

    track_fnames = (
        (track, get_file_name(track, add_char_prefix=char_prefix))
        for track in tracks
    )

    track_fnames = (
        (t, fname, os.path.join(destination, fname))
        for t, fname in track_fnames
    )

    def should_download(track, fname, path):
        if not os.path.exists(path):
            return True

        estimated_size = int(track.get('estimatedSize'))
        disk_size = os.path.getsize(path)
        min_size = estimated_size * .50
        if disk_size < min_size:
            print(f'deleting {fname}, corrupt : {min_size} > {disk_size}')
            os.unlink(path)
            return True

        return False

    missing_tracks = [
        info for info in track_fnames
        if should_download(*info)
    ]

    api: gmusicapi.Mobileclient = ctx.obj['api']
    mgr: gmusicapi.Musicmanager = ctx.obj['mgr']

    devices = api.get_registered_devices()
    for device in devices:
        if device['type'] == 'ANDROID':
            break
    else:
        click.echo("No registered devices found")
        return exit(1)

    device_id = device['id'].lstrip('0x')

    print("Downloading %s tracks ... " % len(missing_tracks))
    progress = ProgressTimer(len(missing_tracks), click.echo)

    for index, (track, fname, full_path) in enumerate(missing_tracks):
        """Couldn't find a consistent way to differentiate between uploaded 
        tracks and store tracks, just try one, then the other"""

        dirname = os.path.dirname(full_path)
        os.makedirs(dirname, exist_ok=True)

        try:
            if 'nid' in track:
                download_store_track(api, full_path, track, device_id)
                success = True
            else:
                success = False
        except Exception as e:
            print('\terror getting store track, trying for user track: %s' % e)
            success = False

        if not success:
            try:
                download_user_track(mgr, full_path, track)
            except Exception as e:
                print('\terror getting user track: %s' % e)

        set_metadata(full_path, track)

        progress.progress(index)


def track_filterer_factory(
    tracks, *, thumbs_up, artist, album, min_album_rating,
):
    filters = []
    if artist:
        filters.append(lambda t: t.get('albumArtist', '').lower() == artist.lower())

    if thumbs_up:
        filters.append(lambda t: t.get('rating') == THUMBS_UP_RATING)

    if album:
        filters.append(lambda t: t.get('album', '').lower() == album.lower())

    if min_album_rating:
        album_ratings = collections.defaultdict(int)
        for track in tracks:
            aid = track.get('albumId')
            if not aid:
                continue

            track_rating = track.get('rating')
            if track_rating == THUMBS_UP_RATING:
                album_ratings[aid] += 1
            elif track_rating == THUMBS_DOWN_RATING:
                album_ratings[aid] -= 1

        def match_good_album(track):
            album_id = track.get('albumId')
            if not album_id:
                return False

            rating = album_ratings[album_id]
            if rating < min_album_rating:
                return False

        filters.append(match_good_album)

    if not filters:
        return lambda ts: ts

    @to(list)
    def matcher():
        for t in tracks:
            if all((match(t) for match in filters)):
                yield t

    return matcher


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


def get_sortable_artist(artist):
    """
    Clean up artist names

    >>> get_sortable_artist('The Strokes')
    'Strokes, The'
    >>> get_sortable_artist('Anberlin')
    'Anberlin'
    >>> get_sortable_artist('A Perfect Circle')
    'Perfect Circle, A'
    """
    for prefix in ('the', 'a', 'an'):
        if artist[:len(prefix) + 1].lower() == f'{prefix} ':
            artist = artist[len(prefix) + 1:] + ', ' + artist[:len(prefix)]
            break

    return artist


def get_path_char(path):
    """
    Get the path prefix char
    >>> get_path_char('2pac')
    '#'
    >>> get_path_char('blink-182')
    'B'
    """
    char = path[0]
    if char.isnumeric():
        return '#'

    return char.upper()


artist_fixes = {
    'Christoper Titus': 'Christopher Titus',
}


def get_file_name(track, *, add_char_prefix):
    """
    Get the path and file name of a track.
    >>> get_file_name({'albumArtist': 'The Weeknd', 'title': 'Starboy (feat. Daft Punk)', 'trackNumber': 1, 'album': 'Starboy', 'year': 2016})
    'W/Weeknd, The/[2016] Starboy/01 - Starboy (feat. Daft Punk).mp3'
    """
    artist = track.get('albumArtist')
    is_compilation_album = artist == 'Various Artists'
    if not artist or is_compilation_album:
        artist = track.get('artist')
    if not artist:
        artist = 'Unknown artist'
    artist = artist_fixes.get(artist, artist)
    artist = _clean_file_name(artist)

    title = track.get('title')
    if not title:
        title = 'Unnamed track'
    title = _clean_file_name(title)

    track_number = track.get('trackNumber', 0)
    year = track.get('year', 0)
    album = _clean_file_name(track.get('album'))
    artist = artist.rstrip('.')
    album = album.rstrip('.')

    if is_compilation_album:
        album = get_sortable_artist(album)
        path_char = 'VA-' + get_path_char(album)
        if year:
            format_string = u'{album} [{year}]{sep}{track:02d} - {artist} - {title}.mp3'
        else:
            format_string = u'{album}{sep}{track:02d} - {artist} - {title}.mp3'
    else:
        artist = get_sortable_artist(artist)
        path_char = get_path_char(artist)
        if year and album:
            format_string = u'{artist}{sep}[{year}] {album}{sep}{track:02d} - {title}.mp3'
        elif album:
            format_string = u'{artist}{sep}{album}{sep}{track:02d} - {title}.mp3'
        else:
            format_string = u'{artist}{sep}{title}.mp3'

    if add_char_prefix:
        format_string = '{char}{sep}' + format_string

    magic_sep = '!@#@!'
    file_name = format_string.format(
        char=path_char,
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


def download_store_track(api: gmusicapi.Mobileclient, full_path, track, device_id):
    dirname = os.path.dirname(full_path)
    temp_path = tempfile.mktemp(dir=dirname)
    try:
        stream_url = api.get_stream_url(track['nid'], device_id=device_id)
        urllib.request.urlretrieve(stream_url, temp_path)
        os.rename(temp_path, full_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def download_user_track(mgr:  gmusicapi.Musicmanager, full_path, track):
    dirname = os.path.dirname(full_path)
    fp, temp_path = tempfile.mkstemp(dir=dirname)

    try:
        fname, audio = mgr.download_song(track['id'])
        with fp:
            fp.write(audio)
        os.rename(temp_path, full_path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@to(list)
def _get_global_tracks(api: gmusicapi.Mobileclient, artist_ids, album_ids):
    artist_ids = list(artist_ids)
    album_ids = list(album_ids)

    for artist_id in artist_ids:
        results = api.get_artist_info(artist_id)
        for album_stub in results['albums']:
            album_id = album_stub['albumId']
            album_ids.append(album_id)

    if not album_ids:
        return

    click.echo(f'finding info on {len(album_ids)} ...')
    for album_id in album_ids:
        album = api.get_album_info(album_id)
        yield from album['tracks']
