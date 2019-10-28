import api
import constants
import m3u8


def Start():
    ObjectContainer.title1 = constants.NAME
    DirectoryObject.thumb = R(constants.ICON)


@handler(constants.PREFIX, constants.NAME, art=constants.ART, thumb=constants.ICON)
def MainMenu():
    oc = ObjectContainer(title1="Choose a Profile")
    oc.add(PrefsObject(title=L('Preferences')))

    username = Prefs['kayo_username']
    password = Prefs['kayo_password']
    if username and password:
        login_result = api.login(username, password)
        if 'access_token' in login_result:
            json_login = JSON.ObjectFromString(login_result)
            access_token = json_login['access_token']
            profiles_result = api.list_profiles(access_token)
            profiles_json = JSON.ObjectFromString(profiles_result)
            for profile in profiles_json:
                oc.add(DirectoryObject(
                    key=Callback(get_top_events, access_token=access_token, profile_id=profile['id'],
                                 profile_name=profile['name']),
                    title=profile['name']
                ))
    else:
        Log("Login Failed...")

    return oc


def get_top_events(access_token, profile_id, profile_name):
    oc = ObjectContainer(title2=profile_name)
    request = api.get_live_events(access_token, profile_id)
    request_json = JSON.ObjectFromString(request)
    live_sport = request_json[1]
    if 'contents' in live_sport:
        Log("Live Sport available")
        oc.add(DirectoryObject(
            key=Callback(get_events, access_token=access_token, profile_id=profile_id,
                         profile_name=profile_name, show_type=1),
            title="Live Sport"
        ))
    else:
        Log("No Live Sport currently")

    return oc


def get_events(access_token, profile_id, profile_name, show_type=1):
    if show_type == 1:
        string = "Live Sport"
    oc = ObjectContainer(title2=string)
    request = api.get_live_events(access_token, profile_id)
    request_json = JSON.ObjectFromString(request)
    result = request_json[show_type]
    if 'contents' in result:
        Log(string + " available")
        for sport in result['contents']:
            Log("IMAGE URL: " + sport['data']['asset']['images']['defaultUrl'])
            oc.add(VideoClipObject(
                key=Callback(get_stream, access_token=access_token, sport=sport, container=True),
                rating_key=sport['data']['asset']['id'],
                title=sport['data']['asset']['title'],
                summary=sport['data']['asset']['description'],
                thumb=sport['data']['asset']['images']['defaultUrl']
            ))
    else:
        Log("No " + string + " currently")

    return oc


def get_stream(access_token, sport, container=False, **kwargs):
    stream_id = sport['data']['asset']['id']
    stream_name = sport['data']['asset']['title']
    thumbnail = sport['data']['asset']['images']['defaultUrl']

    request = api.get_stream(access_token, stream_id)
    request_json = JSON.ObjectFromString(request)
    stream_url = request_json['data'][0]['recommendedStream']['manifest']['uri']
    streams = m3u8.load(stream_url)
    alernative_stream_url = request_json['data'][0]['alternativeStreams'][0]['manifest']['uri']
    streams_alternative = m3u8.load(alernative_stream_url)
    bandwidth = Prefs['kayo_bandwidth']
    current_stream = None

    for stream in streams.playlists:
        Log("Stream:")
        Log(str(stream.stream_info))
        Log(str(stream.uri))
        Log(str(stream.base_uri))
        stream_bandwidth = stream.stream_info.bandwidth
        if int(stream_bandwidth) <= int(bandwidth) and \
                (current_stream is None or int(current_stream.stream_info.bandwidth) < int(stream_bandwidth)):
            current_stream = stream

    for stream in streams_alternative.playlists:
        Log("Alternative Stream:")
        Log(str(stream.stream_info))
        Log(str(stream.uri))
        Log(str(stream.base_uri))
        stream_bandwidth = stream.stream_info.bandwidth
        if int(stream_bandwidth) <= int(bandwidth) and \
                (current_stream is None or int(current_stream.stream_info.bandwidth) < int(stream_bandwidth)):
            current_stream = stream

    stream_url = current_stream.base_uri + current_stream.uri
    vco = VideoClipObject(
        key=Callback(get_stream, access_token=access_token, sport=sport, container=True),
        url=stream_url,
        title=stream_name,
        summary=sport['data']['asset']['description'],
        thumb=thumbnail,
        items=[
            MediaObject(
                parts=[
                    PartObject(
                        key=get_video_url(url=stream_url)
                    )
                ],
                optimized_for_streaming=False
            )
        ]
    )

    if container:
        Log("Loading Video with container: " + stream_url)
        return ObjectContainer(objects=[vco])
    else:
        Log("Loading Video: " + stream_url)
        return vco


def get_video_url(url, live=True):
    return HTTPLiveStreamURL(url=url)

