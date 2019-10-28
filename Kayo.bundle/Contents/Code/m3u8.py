import datetime
import errno
import itertools
import math
import os
import posixpath
import re
import ssl
import sys
from collections import namedtuple
from datetime import date, datetime
from urllib2 import urlopen, Request
from urlparse import urlparse, urljoin

ext_x_targetduration = '#EXT-X-TARGETDURATION'
ext_x_media_sequence = '#EXT-X-MEDIA-SEQUENCE'
ext_x_discontinuity_sequence = '#EXT-X-DISCONTINUITY-SEQUENCE'
ext_x_program_date_time = '#EXT-X-PROGRAM-DATE-TIME'
ext_x_media = '#EXT-X-MEDIA'
ext_x_playlist_type = '#EXT-X-PLAYLIST-TYPE'
ext_x_key = '#EXT-X-KEY'
ext_x_stream_inf = '#EXT-X-STREAM-INF'
ext_x_version = '#EXT-X-VERSION'
ext_x_allow_cache = '#EXT-X-ALLOW-CACHE'
ext_x_endlist = '#EXT-X-ENDLIST'
extinf = '#EXTINF'
ext_i_frames_only = '#EXT-X-I-FRAMES-ONLY'
ext_x_byterange = '#EXT-X-BYTERANGE'
ext_x_i_frame_stream_inf = '#EXT-X-I-FRAME-STREAM-INF'
ext_x_discontinuity = '#EXT-X-DISCONTINUITY'
ext_x_cue_out_start = '#EXT-X-CUE-OUT'
ext_x_cue_out = '#EXT-X-CUE-OUT-CONT'
ext_is_independent_segments = '#EXT-X-INDEPENDENT-SEGMENTS'
ext_x_scte35 = '#EXT-OATCLS-SCTE35'
ext_x_cue_start = '#EXT-X-CUE-OUT'
ext_x_cue_end = '#EXT-X-CUE-IN'
ext_x_cue_span = '#EXT-X-CUE-SPAN'
ext_x_map = '#EXT-X-MAP'
ext_x_start = '#EXT-X-START'

ATTRIBUTELISTPATTERN = re.compile(r'''((?:[^,"']|"[^"]*"|'[^']*')+)''')


def cast_date_time(s):
    result = None
    m = re.match(r'^(?P<year>\d{4})-?(?P<month>\d{2})-?(?P<day>\d{2})', s)
    if m:
        s = s[m.end():]
        result = date(int(m.groupdict()['year']), int(m.groupdict()['month']), int(m.groupdict()['day']))

    # week dates
    if result is None:
        if 'W' in s:
            formats = [
                # suffix for parsing, format, description
                ('', '%Y-W%W-%w', 'YYYY-Www-D'),
                ('', '%YW%W%w', 'YYYYWwwD'),
                ('1', '%Y-W%W%w', 'YYYY-Www'),  # week only
                ('1', '%YW%W%w', 'YYYYWww'),  # week only
            ]
            for suffix, week_format, description in formats:
                if len(description) == len(s):
                    try:
                        result = datetime.strptime(s[:len(description)] + suffix, week_format).date()
                        s = s[:len(description)]
                        break
                    except ValueError:
                        pass

    # ordinal dates
    description = 'YYYY-DDD'
    if result is None and len(s) >= len(description):
        try:
            result = datetime.strptime(s[:len(description)], '%Y-%j').date()
            s = s[:len(description)]
        except ValueError:
            pass

    description = 'YYYYDDD'
    if result is None and len(s) >= len(description):
        try:
            result = datetime.strptime(s[:len(description)], '%Y%j').date()
            s = s[:len(description)]
        except ValueError:
            pass

    # YYYY-MM # month only
    if result is None:
        m = re.match(r'^(?P<year>\d{4})-?(?P<month>\d{2})', s)
        if m:
            s = s[m.end():]
            result = date(int(m.groupdict()['year']), int(m.groupdict()['month']), 1)

    if result is None:
        description = 'YYYY'
        result = datetime.strptime(s[:len(description)], '%Y').date()
        s = s[:len(description)]

    return result


def format_date_time(value):
    return value.isoformat()


class ParseError(Exception):

    def __init__(self, lineno, line):
        self.lineno = lineno
        self.line = line

    def __str__(self):
        return 'Syntax error in manifest on line %d: %s' % (self.lineno, self.line)


def parse(content, strict=False, custom_tags_parser=None):
    '''
    Given a M3U8 playlist content returns a dictionary with all data found
    '''
    data = {
        'media_sequence': 0,
        'is_variant': False,
        'is_endlist': False,
        'is_i_frames_only': False,
        'is_independent_segments': False,
        'playlist_type': None,
        'playlists': [],
        'segments': [],
        'iframe_playlists': [],
        'media': [],
        'keys': []
    }

    state = {
        'expect_segment': False,
        'expect_playlist': False,
        'current_key': None,
    }

    lineno = 0
    for line in string_to_lines(content):
        lineno = lineno + 1
        line = line.strip()

        if line.startswith(ext_x_byterange):
            parse_byterange(line, state)
            state['expect_segment'] = True

        elif line.startswith(ext_x_targetduration):
            parse_simple_parameter(line, data, float)

        elif line.startswith(ext_x_media_sequence):
            parse_simple_parameter(line, data, int)

        elif line.startswith(ext_x_discontinuity_sequence):
            parse_simple_parameter(line, data, int)

        elif line.startswith(ext_x_program_date_time):
            _, program_date_time = parse_simple_parameter_raw_value(line, cast_date_time)
            if not data.get('program_date_time'):
                data['program_date_time'] = program_date_time
            state['current_program_date_time'] = program_date_time
            state['program_date_time'] = program_date_time

        elif line.startswith(ext_x_discontinuity):
            state['discontinuity'] = True

        elif line.startswith(ext_x_cue_out):
            parse_cueout(line, state)
            state['cue_out'] = True
            state['cue_start'] = True

        elif line.startswith(ext_x_cue_out_start):
            parse_cueout_start(line, state, string_to_lines(content)[lineno - 2])
            state['cue_out'] = True
            state['cue_start'] = True

        elif line.startswith(ext_x_cue_span):
            state['cue_out'] = True
            state['cue_start'] = True

        elif line.startswith(ext_x_version):
            parse_simple_parameter(line, data)

        elif line.startswith(ext_x_allow_cache):
            parse_simple_parameter(line, data)

        elif line.startswith(ext_x_key):
            key = parse_key(line)
            state['current_key'] = key
            if key not in data['keys']:
                data['keys'].append(key)

        elif line.startswith(extinf):
            parse_extinf(line, data, state, lineno, strict)
            state['expect_segment'] = True

        elif line.startswith(ext_x_stream_inf):
            state['expect_playlist'] = True
            parse_stream_inf(line, data, state)

        elif line.startswith(ext_x_i_frame_stream_inf):
            parse_i_frame_stream_inf(line, data)

        elif line.startswith(ext_x_media):
            parse_media(line, data, state)

        elif line.startswith(ext_x_playlist_type):
            parse_simple_parameter(line, data)

        elif line.startswith(ext_i_frames_only):
            data['is_i_frames_only'] = True

        elif line.startswith(ext_is_independent_segments):
            data['is_independent_segments'] = True

        elif line.startswith(ext_x_endlist):
            data['is_endlist'] = True

        elif line.startswith(ext_x_map):
            quoted_parser = remove_quotes_parser('uri')
            segment_map_info = parse_attribute_list(ext_x_map, line, quoted_parser)
            data['segment_map'] = segment_map_info

        elif line.startswith(ext_x_start):
            attribute_parser = {
                "time_offset": lambda x: float(x)
            }
            start_info = parse_attribute_list(ext_x_start, line, attribute_parser)
            data['start'] = start_info

        # Comments and whitespace
        elif line.startswith('#'):
            if callable(custom_tags_parser):
                custom_tags_parser(line, data, lineno)

        elif line.strip() == '':
            # blank lines are legal
            pass

        elif state['expect_segment']:
            parse_ts_chunk(line, data, state)
            state['expect_segment'] = False

        elif state['expect_playlist']:
            parse_variant_playlist(line, data, state)
            state['expect_playlist'] = False

        elif strict:
            raise ParseError(lineno, line)
    return data


def parse_key(line):
    params = ATTRIBUTELISTPATTERN.split(line.replace(ext_x_key + ':', ''))[1::2]
    key = {}
    for param in params:
        name, value = param.split('=', 1)
        key[normalize_attribute(name)] = remove_quotes(value)
    return key


def parse_extinf(line, data, state, lineno, strict):
    chunks = line.replace(extinf + ':', '').split(',', 1)
    if len(chunks) == 2:
        duration, title = chunks
    elif len(chunks) == 1:
        if strict:
            raise ParseError(lineno, line)
        else:
            duration = chunks[0]
            title = ''
    if 'segment' not in state:
        state['segment'] = {}
    state['segment']['duration'] = float(duration)
    state['segment']['title'] = remove_quotes(title)


def parse_ts_chunk(line, data, state):
    segment = state.pop('segment')
    if state.get('program_date_time'):
        segment['program_date_time'] = state.pop('program_date_time')
    if state.get('current_program_date_time'):
        segment['current_program_date_time'] = state['current_program_date_time']
        state['current_program_date_time'] = state['current_program_date_time'] + datetime.timedelta(
            seconds=segment['duration'])
    segment['uri'] = line
    segment['cue_out'] = state.pop('cue_out', False)
    if state.get('current_cue_out_scte35'):
        segment['scte35'] = state['current_cue_out_scte35']
        segment['scte35_duration'] = state['current_cue_out_duration']
    segment['discontinuity'] = state.pop('discontinuity', False)
    if state.get('current_key'):
        segment['key'] = state['current_key']
    else:
        # For unencrypted segments, the initial key would be None
        if None not in data['keys']:
            data['keys'].append(None)
    data['segments'].append(segment)


def parse_attribute_list(prefix, line, atribute_parser):
    params = ATTRIBUTELISTPATTERN.split(line.replace(prefix + ':', ''))[1::2]

    attributes = {}
    for param in params:
        name, value = param.split('=', 1)
        name = normalize_attribute(name)

        if name in atribute_parser:
            value = atribute_parser[name](value)

        attributes[name] = value

    return attributes


def parse_stream_inf(line, data, state):
    data['is_variant'] = True
    data['media_sequence'] = None
    atribute_parser = remove_quotes_parser('codecs', 'audio', 'video', 'subtitles', 'closed_captions')
    atribute_parser["program_id"] = int
    atribute_parser["bandwidth"] = lambda x: int(float(x))
    atribute_parser["average_bandwidth"] = int
    atribute_parser["frame_rate"] = float
    state['stream_info'] = parse_attribute_list(ext_x_stream_inf, line, atribute_parser)


def parse_i_frame_stream_inf(line, data):
    atribute_parser = remove_quotes_parser('codecs', 'uri')
    atribute_parser["program_id"] = int
    atribute_parser["bandwidth"] = int
    iframe_stream_info = parse_attribute_list(ext_x_i_frame_stream_inf, line, atribute_parser)
    iframe_playlist = {'uri': iframe_stream_info.pop('uri'),
                       'iframe_stream_info': iframe_stream_info}

    data['iframe_playlists'].append(iframe_playlist)


def parse_media(line, data, state):
    quoted = remove_quotes_parser('uri', 'group_id', 'language', 'name', 'characteristics')
    media = parse_attribute_list(ext_x_media, line, quoted)
    data['media'].append(media)


def parse_variant_playlist(line, data, state):
    playlist = {'uri': line,
                'stream_info': state.pop('stream_info')}

    data['playlists'].append(playlist)


def parse_byterange(line, state):
    if 'segment' not in state:
        state['segment'] = {}
    state['segment']['byterange'] = line.replace(ext_x_byterange + ':', '')


def parse_simple_parameter_raw_value(line, cast_to=str, normalize=False):
    param, value = line.split(':', 1)
    param = normalize_attribute(param.replace('#EXT-X-', ''))
    if normalize:
        value = normalize_attribute(value)
    return param, cast_to(value)


def parse_and_set_simple_parameter_raw_value(line, data, cast_to=str, normalize=False):
    param, value = parse_simple_parameter_raw_value(line, cast_to, normalize)
    data[param] = value
    return data[param]


def parse_simple_parameter(line, data, cast_to=str):
    return parse_and_set_simple_parameter_raw_value(line, data, cast_to, True)


def parse_cueout(line, state):
    param, value = line.split(':', 1)
    res = re.match('.*Duration=(.*),SCTE35=(.*)$', value)
    if res:
        state['current_cue_out_duration'] = res.group(1)
        state['current_cue_out_scte35'] = res.group(2)


def cueout_elemental(line, state, prevline):
    param, value = line.split(':', 1)
    res = re.match('.*EXT-OATCLS-SCTE35:(.*)$', prevline)
    if res:
        return (res.group(1), value)
    else:
        return None


def cueout_envivio(line, state, prevline):
    param, value = line.split(':', 1)
    res = re.match('.*DURATION=(.*),.*,CUE="(.*)"', value)
    if res:
        return (res.group(2), res.group(1))
    else:
        return None


def parse_cueout_start(line, state, prevline):
    cueout_state = cueout_elemental(line, state, prevline) or cueout_envivio(line, state, prevline)
    if cueout_state:
        state['current_cue_out_scte35'] = cueout_state[0]
        state['current_cue_out_duration'] = cueout_state[1]


def string_to_lines(string):
    return string.strip().splitlines()


def remove_quotes_parser(*attrs):
    return dict(zip(attrs, itertools.repeat(remove_quotes)))


def remove_quotes(string):
    '''
    Remove quotes from string.

    Ex.:
      "foo" -> foo
      'foo' -> foo
      'foo  -> 'foo

    '''
    quotes = ('"', "'")
    if string.startswith(quotes) and string.endswith(quotes):
        return string[1:-1]
    return string


def normalize_attribute(attribute):
    return attribute.replace('-', '_').lower().strip()


def is_url(uri):
    return uri.startswith(('https://', 'http://'))


class BasePathMixin(object):

    @property
    def absolute_uri(self):
        if self.uri is None:
            return None
        if is_url(self.uri):
            return self.uri
        else:
            if self.base_uri is None:
                raise ValueError('There can not be `absolute_uri` with no `base_uri` set')
            return urijoin(self.base_uri, self.uri)

    @property
    def base_path(self):
        if self.uri is None:
            return None
        return os.path.dirname(self.uri)

    @base_path.setter
    def base_path(self, newbase_path):
        if self.uri is not None:
            if not self.base_path:
                self.uri = "%s/%s" % (newbase_path, self.uri)
            else:
                self.uri = self.uri.replace(self.base_path, newbase_path)


class GroupedBasePathMixin(object):

    def set_base_uri(self, new_base_uri):
        for item in self:
            item.base_uri = new_base_uri

    base_uri = property(None, set_base_uri)

    def set_base_path(self, newbase_path):
        for item in self:
            item.base_path = newbase_path

    base_path = property(None, set_base_path)


class M3U8(object):
    simple_attributes = (
        # obj attribute      # parser attribute
        ('is_variant', 'is_variant'),
        ('is_endlist', 'is_endlist'),
        ('is_i_frames_only', 'is_i_frames_only'),
        ('target_duration', 'targetduration'),
        ('media_sequence', 'media_sequence'),
        ('program_date_time', 'program_date_time'),
        ('is_independent_segments', 'is_independent_segments'),
        ('version', 'version'),
        ('allow_cache', 'allow_cache'),
        ('playlist_type', 'playlist_type'),
        ('discontinuity_sequence', 'discontinuity_sequence')
    )

    def __init__(self, content=None, base_path=None, base_uri=None, strict=False, custom_tags_parser=None):
        if content is not None:
            self.data = parse(content, strict, custom_tags_parser)
        else:
            self.data = {}
        self.the_base_uri = base_uri
        if self.the_base_uri:
            if not self.the_base_uri.endswith('/'):
                self.the_base_uri = self.the_base_uri + '/'

        self.initialize_attributes()
        self.base_path = base_path

    def initialize_attributes(self):
        self.keys = [Key(base_uri=self.base_uri, **params) if params else None
                     for params in self.data.get('keys', [])]
        self.segments = SegmentList(
            [Segment(base_uri=self.base_uri, keyobject=find_key(segment.get('key', {}), self.keys), **segment)
             for segment in self.data.get('segments', [])])
        for attr, param in self.simple_attributes:
            try:
                if attr in self.data:
                    setattr(self, attr, self.data.get(param))
            except:
                Log("Attribute " + attr + " not settable?")

        self.files = []
        for key in self.keys:
            # Avoid None key, it could be the first one, don't repeat them
            if key and key.uri not in self.files:
                self.files.append(key.uri)
        self.files.extend(self.segments.uri)

        self.media = MediaList([Media(base_uri=self.base_uri, **media)
                                for media in self.data.get('media', [])])

        self.playlists = PlaylistList([Playlist(base_uri=self.base_uri, media=self.media, **playlist)
                                       for playlist in self.data.get('playlists', [])])

        self.iframe_playlists = PlaylistList()
        for ifr_pl in self.data.get('iframe_playlists', []):
            self.iframe_playlists.append(IFramePlaylist(base_uri=self.base_uri,
                                                        uri=ifr_pl['uri'],
                                                        iframe_stream_info=ifr_pl['iframe_stream_info'])
                                         )
        self.segment_map = self.data.get('segment_map')

        start = self.data.get('start', None)
        self.start = start and Start(**start)

    @property
    def base_uri(self):
        return self.the_base_uri

    @base_uri.setter
    def base_uri(self, newbase_uri):
        self.the_base_uri = newbase_uri
        self.media.base_uri = newbase_uri
        self.playlists.base_uri = newbase_uri
        self.segments.base_uri = newbase_uri
        for key in self.keys:
            if key:
                key.base_uri = newbase_uri

    @property
    def base_path(self):
        return self.the_base_path

    @base_path.setter
    def base_path(self, newbase_path):
        self.the_base_path = newbase_path
        self.update_base_path()

    def update_base_path(self):
        if self.the_base_path is None:
            return
        for key in self.keys:
            if key:
                key.base_path = self.the_base_path
        self.media.base_path = self.the_base_path
        self.segments.base_path = self.the_base_path
        self.playlists.base_path = self.the_base_path

    def add_playlist(self, playlist):
        self.is_variant = True
        self.playlists.append(playlist)

    def add_iframe_playlist(self, iframe_playlist):
        if iframe_playlist is not None:
            self.is_variant = True
            self.iframe_playlists.append(iframe_playlist)

    def add_media(self, media):
        self.media.append(media)

    def add_segment(self, segment):
        self.segments.append(segment)

    def dumps(self):
        '''
        Returns the current m3u8 as a string.
        You could also use unicode(<this obj>) or str(<this obj>)
        '''
        output = ['#EXTM3U']
        if self.is_independent_segments:
            output.append('#EXT-X-INDEPENDENT-SEGMENTS')
        if self.media_sequence:
            output.append('#EXT-X-MEDIA-SEQUENCE:' + str(self.media_sequence))
        if self.discontinuity_sequence:
            output.append('#EXT-X-DISCONTINUITY-SEQUENCE:{}'.format(
                int_or_float_to_string(self.discontinuity_sequence)))
        if self.allow_cache:
            output.append('#EXT-X-ALLOW-CACHE:' + self.allow_cache.upper())
        if self.version:
            output.append('#EXT-X-VERSION:' + self.version)
        if self.target_duration:
            output.append('#EXT-X-TARGETDURATION:' +
                          int_or_float_to_string(self.target_duration))
        if not (self.playlist_type is None or self.playlist_type == ''):
            output.append('#EXT-X-PLAYLIST-TYPE:%s' % str(self.playlist_type).upper())
        if self.start:
            output.append(str(self.start))
        if self.is_i_frames_only:
            output.append('#EXT-X-I-FRAMES-ONLY')
        if self.segment_map:
            map_output = []
            if self.segment_map.get('uri'):
                map_output.append('URI=' + quoted(self.segment_map['uri']))
            if self.segment_map.get('byterange'):
                map_output.append('BYTERANGE=' + self.segment_map['byterange'])
            output.append('#EXT-X-MAP:' + ','.join(map_output))
        if self.is_variant:
            if self.media:
                output.append(str(self.media))
            output.append(str(self.playlists))
            if self.iframe_playlists:
                output.append(str(self.iframe_playlists))
        output.append(str(self.segments))

        if self.is_endlist:
            output.append('#EXT-X-ENDLIST')

        return '\n'.join(output)

    def dump(self, filename):
        '''
        Saves the current m3u8 to ``filename``
        '''
        self.create_sub_directories(filename)

        with open(filename, 'w') as fileobj:
            fileobj.write(self.dumps())

    def create_sub_directories(self, filename):
        basename = os.path.dirname(filename)
        try:
            if basename:
                os.makedirs(basename)
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise


class Segment(BasePathMixin):
    '''
    A video segment from a M3U8 playlist

    `uri`
      a string with the segment uri

    `title`
      title attribute from EXTINF parameter

    `program_date_time`
      Returns the EXT-X-PROGRAM-DATE-TIME as a datetime. This field is only set
      if EXT-X-PROGRAM-DATE-TIME exists for this segment
      http://tools.ietf.org/html/draft-pantos-http-live-streaming-07#section-3.3.5

    `current_program_date_time`
      Returns a datetime of this segment, either the value of `program_date_time`
      when EXT-X-PROGRAM-DATE-TIME is set or a calculated value based on previous
      segments' EXT-X-PROGRAM-DATE-TIME and EXTINF values

    `discontinuity`
      Returns a boolean indicating if a EXT-X-DISCONTINUITY tag exists
      http://tools.ietf.org/html/draft-pantos-http-live-streaming-13#section-3.4.11

    `cue_out`
      Returns a boolean indicating if a EXT-X-CUE-OUT-CONT tag exists

    `scte35`
      Base64 encoded SCTE35 metadata if available

    `scte35_duration`
      Planned SCTE35 duration

    `duration`
      duration attribute from EXTINF parameter

    `base_uri`
      uri the key comes from in URI hierarchy. ex.: http://example.com/path/to

    `byterange`
      byterange attribute from EXT-X-BYTERANGE parameter

    `key`
      Key used to encrypt the segment (EXT-X-KEY)
    '''

    def __init__(self, uri, base_uri, program_date_time=None, current_program_date_time=None,
                 duration=None, title=None, byterange=None, cue_out=False,
                 discontinuity=False, key=None, scte35=None, scte35_duration=None,
                 keyobject=None):
        self.uri = uri
        self.duration = duration
        self.title = title
        self.base_uri = base_uri
        self.byterange = byterange
        self.program_date_time = program_date_time
        self.current_program_date_time = current_program_date_time
        self.discontinuity = discontinuity
        self.cue_out = cue_out
        self.scte35 = scte35
        self.scte35_duration = scte35_duration
        self.key = keyobject
        # Key(base_uri=base_uri, **key) if key else None

    def dumps(self, last_segment):
        output = []
        if last_segment and self.key != last_segment.key:
            output.append(str(self.key))
            output.append('\n')
        else:
            # The key must be checked anyway now for the first segment
            if self.key and last_segment is None:
                output.append(str(self.key))
                output.append('\n')

        if self.discontinuity:
            output.append('#EXT-X-DISCONTINUITY\n')
        if self.program_date_time:
            output.append('#EXT-X-PROGRAM-DATE-TIME:%s\n' %
                          format_date_time(self.program_date_time))
        if self.cue_out:
            output.append('#EXT-X-CUE-OUT-CONT\n')
        output.append('#EXTINF:%s,' % int_or_float_to_string(self.duration))
        if self.title:
            output.append(quoted(self.title))

        output.append('\n')

        if self.byterange:
            output.append('#EXT-X-BYTERANGE:%s\n' % self.byterange)

        output.append(self.uri)

        return ''.join(output)

    def __str__(self):
        return self.dumps(None)


class SegmentList(list, GroupedBasePathMixin):

    def __str__(self):
        output = []
        last_segment = None
        for segment in self:
            output.append(segment.dumps(last_segment))
            last_segment = segment
        return '\n'.join(output)

    @property
    def uri(self):
        return [seg.uri for seg in self]

    def by_key(self, key):
        return [segment for segment in self if segment.key == key]


class Key(BasePathMixin):
    '''
    Key used to encrypt the segments in a m3u8 playlist (EXT-X-KEY)

    `method`
      is a string. ex.: "AES-128"

    `uri`
      is a string. ex:: "https://priv.example.com/key.php?r=52"

    `base_uri`
      uri the key comes from in URI hierarchy. ex.: http://example.com/path/to

    `iv`
      initialization vector. a string representing a hexadecimal number. ex.: 0X12A

    '''

    def __init__(self, method, base_uri, uri=None, iv=None, keyformat=None, keyformatversions=None):
        self.method = method
        self.uri = uri
        self.iv = iv
        self.keyformat = keyformat
        self.keyformatversions = keyformatversions
        self.base_uri = base_uri

    def __str__(self):
        output = [
            'METHOD=%s' % self.method,
        ]
        if self.uri:
            output.append('URI="%s"' % self.uri)
        if self.iv:
            output.append('IV=%s' % self.iv)
        if self.keyformat:
            output.append('KEYFORMAT="%s"' % self.keyformat)
        if self.keyformatversions:
            output.append('KEYFORMATVERSIONS="%s"' % self.keyformatversions)

        return '#EXT-X-KEY:' + ','.join(output)

    def eq__(self, other):
        if not other:
            return False
        return self.method == other.method and \
               self.uri == other.uri and \
               self.iv == other.iv and \
               self.base_uri == other.base_uri and \
               self.keyformat == other.keyformat and \
               self.keyformatversions == other.keyformatversions

    def ne__(self, other):
        return not self.eq__(other)


class Playlist(BasePathMixin):
    '''
    Playlist object representing a link to a variant M3U8 with a specific bitrate.

    Attributes:

    `stream_info` is a named tuple containing the attributes: `program_id`,
    `bandwidth`, `average_bandwidth`, `resolution`, `codecs` and `resolution`
    which is a a tuple (w, h) of integers

    `media` is a list of related Media entries.

    More info: http://tools.ietf.org/html/draft-pantos-http-live-streaming-07#section-3.3.10
    '''

    def __init__(self, uri, stream_info, media, base_uri):
        self.uri = uri
        self.base_uri = base_uri

        resolution = stream_info.get('resolution')
        if resolution != None:
            resolution = resolution.strip('"')
            values = resolution.split('x')
            resolution_pair = (int(values[0]), int(values[1]))
        else:
            resolution_pair = None

        self.stream_info = StreamInfo(
            bandwidth=stream_info['bandwidth'],
            video=stream_info.get('video'),
            audio=stream_info.get('audio'),
            subtitles=stream_info.get('subtitles'),
            closed_captions=stream_info.get('closed_captions'),
            average_bandwidth=stream_info.get('average_bandwidth'),
            program_id=stream_info.get('program_id'),
            resolution=resolution_pair,
            codecs=stream_info.get('codecs'),
            frame_rate=stream_info.get('frame_rate')
        )
        self.media = []
        for media_type in ('audio', 'video', 'subtitles'):
            group_id = stream_info.get(media_type)
            if not group_id:
                continue

            self.media = media + filter(lambda m: m.group_id == group_id, media)


class IFramePlaylist(BasePathMixin):
    '''
    IFramePlaylist object representing a link to a
    variant M3U8 i-frame playlist with a specific bitrate.

    Attributes:

    `iframe_stream_info` is a named tuple containing the attributes:
     `program_id`, `bandwidth`, `codecs` and `resolution` which
     is a tuple (w, h) of integers

    More info: http://tools.ietf.org/html/draft-pantos-http-live-streaming-07#section-3.3.13
    '''

    def __init__(self, base_uri, uri, iframe_stream_info):
        self.uri = uri
        self.base_uri = base_uri

        resolution = iframe_stream_info.get('resolution')
        if resolution is not None:
            values = resolution.split('x')
            resolution_pair = (int(values[0]), int(values[1]))
        else:
            resolution_pair = None

        self.iframe_stream_info = StreamInfo(
            bandwidth=iframe_stream_info.get('bandwidth'),
            video=iframe_stream_info.get('video'),
            # Audio, subtitles, and closed captions should not exist in
            # EXT-X-I-FRAME-STREAM-INF, so just hardcode them to None.
            audio=None,
            subtitles=None,
            closed_captions=None,
            average_bandwidth=None,
            program_id=iframe_stream_info.get('program_id'),
            resolution=resolution_pair,
            codecs=iframe_stream_info.get('codecs'),
            frame_rate=None
        )

    def __str__(self):
        iframe_stream_inf = []
        if self.iframe_stream_info.program_id:
            iframe_stream_inf.append('PROGRAM-ID=%d' %
                                     self.iframe_stream_info.program_id)
        if self.iframe_stream_info.bandwidth:
            iframe_stream_inf.append('BANDWIDTH=%d' %
                                     self.iframe_stream_info.bandwidth)
        if self.iframe_stream_info.resolution:
            res = (str(self.iframe_stream_info.resolution[0]) + 'x' +
                   str(self.iframe_stream_info.resolution[1]))
            iframe_stream_inf.append('RESOLUTION=' + res)
        if self.iframe_stream_info.codecs:
            iframe_stream_inf.append('CODECS=' +
                                     quoted(self.iframe_stream_info.codecs))
        if self.uri:
            iframe_stream_inf.append('URI=' + quoted(self.uri))

        return '#EXT-X-I-FRAME-STREAM-INF:' + ','.join(iframe_stream_inf)


StreamInfo = namedtuple(
    'StreamInfo',
    ['bandwidth', 'closed_captions', 'average_bandwidth', 'program_id', 'resolution', 'codecs', 'audio', 'video',
     'subtitles', 'frame_rate']
)


class Media(BasePathMixin):
    '''
    A media object from a M3U8 playlist
    https://tools.ietf.org/html/draft-pantos-http-live-streaming-16#section-4.3.4.1

    `uri`
      a string with the media uri

    `type`
    `group_id`
    `language`
    `assoc-language`
    `name`
    `default`
    `autoselect`
    `forced`
    `instream_id`
    `characteristics`
      attributes in the EXT-MEDIA tag

    `base_uri`
      uri the media comes from in URI hierarchy. ex.: http://example.com/path/to
    '''

    def __init__(self, uri=None, type=None, group_id=None, language=None,
                 name=None, default=None, autoselect=None, forced=None,
                 characteristics=None, assoc_language=None,
                 instream_id=None, base_uri=None, **extras):
        self.base_uri = base_uri
        self.uri = uri
        self.type = type
        self.group_id = group_id
        self.language = language
        self.name = name
        self.default = default
        self.autoselect = autoselect
        self.forced = forced
        self.assoc_language = assoc_language
        self.instream_id = instream_id
        self.characteristics = characteristics
        self.extras = extras

    def dumps(self):
        media_out = []

        if self.uri:
            media_out.append('URI=' + quoted(self.uri))
        if self.type:
            media_out.append('TYPE=' + self.type)
        if self.group_id:
            media_out.append('GROUP-ID=' + quoted(self.group_id))
        if self.language:
            media_out.append('LANGUAGE=' + quoted(self.language))
        if self.assoc_language:
            media_out.append('ASSOC-LANGUAGE=' + quoted(self.assoc_language))
        if self.name:
            media_out.append('NAME=' + quoted(self.name))
        if self.default:
            media_out.append('DEFAULT=' + self.default)
        if self.autoselect:
            media_out.append('AUTOSELECT=' + self.autoselect)
        if self.forced:
            media_out.append('FORCED=' + self.forced)
        if self.instream_id:
            media_out.append('INSTREAM-ID=' + self.instream_id)
        if self.characteristics:
            media_out.append('CHARACTERISTICS=' + quoted(self.characteristics))

        return ('#EXT-X-MEDIA:' + ','.join(media_out))

    def __str__(self):
        return self.dumps()


class MediaList(list, GroupedBasePathMixin):

    def __str__(self):
        output = [str(playlist) for playlist in self]
        return '\n'.join(output)

    @property
    def uri(self):
        return [media.uri for media in self]


class PlaylistList(list, GroupedBasePathMixin):

    def __str__(self):
        output = [str(playlist) for playlist in self]
        return '\n'.join(output)


class Start(object):

    def __init__(self, time_offset, precise=None):
        self.time_offset = float(time_offset)
        self.precise = precise

    def __str__(self):
        output = [
            'TIME-OFFSET=' + str(self.time_offset)
        ]
        if self.precise and self.precise in ['YES', 'NO']:
            output.append('PRECISE=' + str(self.precise))

        return ext_x_start + ':' + ','.join(output)


def find_key(keydata, keylist):
    if not keydata:
        return None
    for key in keylist:
        if key:
            # Check the intersection of keys and values
            if keydata.get('uri', None) == key.uri and \
                    keydata.get('method', 'NONE') == key.method and \
                    keydata.get('iv', None) == key.iv:
                return key
    raise KeyError("No key found for key data")


def denormalize_attribute(attribute):
    return attribute.replace('_', '-').upper()


def quoted(string):
    return '"%s"' % string


def int_or_float_to_string(number):
    return str(int(number)) if number == math.floor(number) else str(number)


def urijoin(base_uri, path):
    if is_url(base_uri):
        return urlparse.urljoin(base_uri, path)
    else:
        return os.path.normpath(os.path.join(base_uri, path.strip('/')))

PYTHON_MAJOR_VERSION = sys.version_info


def loads(content, uri=None, custom_tags_parser=None):
    '''
    Given a string with a m3u8 content, returns a M3U8 object.
    Optionally parses a uri to set a correct base_uri on the M3U8 object.
    Raises ValueError if invalid content
    '''

    if uri is None:
        return M3U8(content, custom_tags_parser=custom_tags_parser)
    else:
        base_uri = parsed_url(uri)
        return M3U8(content, base_uri=base_uri, custom_tags_parser=custom_tags_parser)


def load(uri, timeout=None, headers={}, custom_tags_parser=None):
    '''
    Retrieves the content from a given URI and returns a M3U8 object.
    Raises ValueError if invalid content or IOError if request fails.
    Raises socket.timeout(python 2.7+) or urllib2.URLError(python 2.6) if
    timeout happens when loading from uri
    '''
    if is_url(uri):
        return load_from_uri(uri, timeout, headers, custom_tags_parser)
    else:
        return load_from_file(uri, custom_tags_parser)


# Support for python3 inspired by https://github.com/szemtiv/m3u8/


def load_from_uri(uri, timeout=None, headers={}, custom_tags_parser=None):
    request = Request(uri, headers=headers)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    resource = urlopen(request, timeout=timeout, context=ctx)
    base_uri = parsed_url(resource.geturl())
    if PYTHON_MAJOR_VERSION < (3,):
        content = read_python2x(resource)
    else:
        content = read_python3x(resource)
    return M3U8(content, base_uri=base_uri, custom_tags_parser=custom_tags_parser)


def parsed_url(url):
    parsed_url = urlparse(url)
    prefix = parsed_url.scheme + '://' + parsed_url.netloc
    base_path = posixpath.normpath(parsed_url.path + '/..')
    return urljoin(prefix, base_path)


def read_python2x(resource):
    return resource.read().strip()


def read_python3x(resource):
    return resource.read().decode(
        resource.headers.get_content_charset(failobj="utf-8")
    )


def load_from_file(uri, custom_tags_parser=None):
    with open(uri) as fileobj:
        raw_content = fileobj.read().strip()
    base_uri = os.path.dirname(uri)
    return M3U8(raw_content, base_uri=base_uri, custom_tags_parser=custom_tags_parser)
