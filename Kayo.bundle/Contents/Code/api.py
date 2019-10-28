import constants


def login(username, password):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    body = {
        'audience': "kayosports.com.au",
        'grant_type': "http://auth0.com/oauth/grant-type/password-realm",
        'scope': "openid offline_access",
        'realm': "prod-martian-database",
        'client_id': constants.CLIENT_ID,
        'username': username,
        'password': password
    }
    request = HTTP.Request(constants.AUTH_URL, headers=headers, data=JSON.StringFromObject(body))
    return request.content


def list_profiles(access_token):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update({"Authorization": "Bearer " + access_token})
    request = HTTP.Request(constants.PROFILES_URL, headers=headers)
    return request.content


def get_live_events(access_token, profile_id):
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update({"Authorization": "Bearer " + access_token})
    request = HTTP.Request(constants.LIVE_EVENTS_URL.replace('${profileId}', profile_id), headers=headers)
    return request.content


def get_stream(access_token, stream_id):
    headers = {"Content-Type": "application/json", "Accept": "application/json", "Origin": "kayosports.com.au",
               "Authorization": "Bearer " + access_token}
    body = {}
    request = HTTP.Request(constants.STREAM_URL.replace('${streamId}', stream_id), headers=headers,
                           data=JSON.StringFromObject(body))
    return request.content

