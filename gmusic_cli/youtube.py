import httplib2

from apiclient.discovery import build
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret. You can acquire an OAuth 2.0 client ID and client secret from
# the Google Developers Console at
# https://console.developers.google.com/.
# Please ensure that you have enabled the YouTube Data API for your project.
# For more information about using OAuth2 to access the YouTube Data API, see:
#   https://developers.google.com/youtube/v3/guides/authentication
# For more information about the client_secrets.json file format, see:
#   https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
CLIENT_SECRETS_FILE = "client_secrets.json"
MISSING_CLIENT_SECRETS_MESSAGE = 'oh noes!'

# This OAuth 2.0 access scope allows for full read/write access to the
# authenticated user's account.
YOUTUBE_READ_WRITE_SCOPE = "https://www.googleapis.com/auth/youtube"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"


class YoutubeClient:
    def __init__(self, username, password):
        self.username = username
        self.password = password

        flow = flow_from_clientsecrets(
            CLIENT_SECRETS_FILE,
            scope=YOUTUBE_READ_WRITE_SCOPE,
            message=MISSING_CLIENT_SECRETS_MESSAGE,
        )

        storage = Storage("reds-oauth2.json")
        credentials = storage.get()

        if credentials is None or credentials.invalid:
            auth_uri = flow.step1_get_authorize_url(
                redirect_uri='http://localhost:12345',
            )
            print("auth_uri: %s" % auth_uri)
            code = input("code?")

            credentials = flow.step2_exchange(code)
            storage.put(credentials)

        self.yt = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION,
                        http=credentials.authorize(httplib2.Http()))

    def get_playlists(self):
        request = self.yt.playlists().list(
            part='id,snippet',
            mine=True,
        )
        response = request.execute()
        return response['items']

    def create_playlist(self, title):
        response = self.yt.playlists().insert(
            part='snippet,status',
            body={
                'snippet': {
                    'title': title,
                    'description': 'my music videos',
                },
                'status': {
                    'privacyStatus': 'private',
                },
            },
        ).execute()
        return response

    def get_playlist_items(self, playlist):
        request = self.yt.playlistItems().list(
            part='id,snippet,contentDetails',
            playlistId=playlist['id'],
            maxResults=50,
        )
        while request:
            response = request.execute()
            yield from response['items']
            request = self.yt.playlistItems().list_next(
                request, response,
            )

    def insert_playlist_item(self, playlist, youtube_id):
        playlist_id = playlist['id']

        response = self.yt.playlistItems().insert(
            part='snippet,status',
            body={
                'snippet': {
                    'playlistId': playlist_id,
                    'resourceId': {
                        'kind': 'youtube#video',
                        'videoId': youtube_id,
                    },
                },
            },
        ).execute()

        return response
