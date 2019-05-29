"""
Attempting to support Google Music as a media player
"""
import asyncio
import logging
import time
import random
import pickle
import os.path
from datetime import timedelta

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.condition import state
from homeassistant.helpers.event import track_state_change
from homeassistant.helpers.event import call_later

import homeassistant.components.input_select as input_select

from homeassistant.const import (
    ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_START,
    STATE_PLAYING, STATE_PAUSED, STATE_OFF, STATE_IDLE)

from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA, SERVICE_TURN_ON, SERVICE_TURN_OFF,
    SERVICE_PLAY_MEDIA, SERVICE_MEDIA_PAUSE, ATTR_MEDIA_VOLUME_LEVEL,
    SERVICE_VOLUME_UP, SERVICE_VOLUME_DOWN, SERVICE_VOLUME_SET,
    ATTR_MEDIA_CONTENT_ID, ATTR_MEDIA_CONTENT_TYPE, DOMAIN as DOMAIN_MP)

from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC, SUPPORT_STOP, SUPPORT_PLAY, SUPPORT_PAUSE,
    SUPPORT_PLAY_MEDIA, SUPPORT_PREVIOUS_TRACK, SUPPORT_NEXT_TRACK,
    SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET, SUPPORT_VOLUME_STEP,
    SUPPORT_TURN_ON, SUPPORT_TURN_OFF, SUPPORT_SHUFFLE_SET, SUPPORT_SELECT_SOURCE)

# The domain of your component. Should be equal to the name of your component.
DOMAIN = 'gmusic_player'

SUPPORT_GMUSIC_PLAYER = SUPPORT_TURN_ON | SUPPORT_TURN_OFF | SUPPORT_PLAY_MEDIA | \
    SUPPORT_PLAY | SUPPORT_PAUSE | SUPPORT_STOP | SUPPORT_SELECT_SOURCE | \
    SUPPORT_VOLUME_SET | SUPPORT_VOLUME_STEP | SUPPORT_VOLUME_MUTE | \
    SUPPORT_PREVIOUS_TRACK | SUPPORT_NEXT_TRACK | SUPPORT_SHUFFLE_SET

CONF_USERNAME = 'user'
CONF_DEVICE_ID = 'device_id'
CONF_LOGIN_TYPE = 'login_type'
CONF_PASSWORD = 'password'
CONF_TOKEN_PATH = 'token_path'
CONF_OAUTH_CRED = 'oauth_cred'
CONF_SPEAKERS = 'media_player'
CONF_SOURCE = 'source'
CONF_PLAYLISTS = 'playlist'
CONF_STATIONS = 'station'
CONF_SHUFFLE = 'shuffle'
CONF_SHUFFLE_MODE = 'shuffle_mode'

DEFAULT_DEVICE_ID = 'not_set'
DEFAULT_LOGIN_TYPE = 'not_set'
DEFAULT_PASSWORD = 'not_set'
DEFAULT_TOKEN_PATH = "./."
DEFAULT_OAUTH_CRED = 'not_set'
DEFAULT_SPEAKERS = 'not_set'
DEFAULT_SOURCE = 'not_set'
DEFAULT_PLAYLISTS = 'not_set'
DEFAULT_STATIONS = 'not_set'
DEFAULT_SHUFFLE = True
DEFAULT_SHUFFLE_MODE = 1

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_LOGIN_TYPE): cv.string,
        vol.Optional(CONF_PASSWORD, default=DEFAULT_PASSWORD): cv.string,
        vol.Optional(CONF_TOKEN_PATH, default=DEFAULT_TOKEN_PATH): cv.string,
        vol.Optional(CONF_OAUTH_CRED, default=DEFAULT_OAUTH_CRED): cv.string,
        vol.Optional(CONF_SPEAKERS, default=DEFAULT_SPEAKERS): cv.string,
        vol.Optional(CONF_SOURCE, default=DEFAULT_SOURCE): cv.string,
        vol.Optional(CONF_PLAYLISTS, default=DEFAULT_PLAYLISTS): cv.string,
        vol.Optional(CONF_STATIONS, default=DEFAULT_STATIONS): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

# Shortcut for the logger
_LOGGER = logging.getLogger(__name__)

def setup_platform(hass, config, add_devices, discovery_info=None):
    """ Setup Gmusic player. """
    add_devices([GmusicComponent(hass, config)])
    return True

class GmusicComponent(MediaPlayerDevice):
    def __init__(self, hass, config):
        from gmusicapi import Mobileclient
        # https://github.com/simon-weber/gmusicapi/issues/424
        class GMusic(Mobileclient):
            def login(self, username, password, device_id, authtoken=None):
                if authtoken:
                    self.session._authtoken       = authtoken
                    self.session.is_authenticated = True
                    try:
                        # Send a test request to ensure our authtoken is still valide and working
                        self.get_registered_devices()
                        return True
                    except:
                        # Faild with the test-request so we set "is_authenticated=False"
                        # and go through the login-process again to get a new "authtoken"
                        self.session.is_authenticated = False
                if device_id:
                    if super(GMusic, self).login(username, password, device_id):
                        return True
                # Prevent further execution in case we failed with the login-process
                raise Exception("Legacy login failed! Please check logs for any gmusicapi related WARNING")

        self.hass = hass
        #self._api = GMusic()
        self._api = Mobileclient()

        _login_type = config.get(CONF_LOGIN_TYPE, DEFAULT_LOGIN_TYPE)
        _device_id = config.get(CONF_DEVICE_ID)

        if _login_type == 'legacy':
            _authtoken = config.get(CONF_TOKEN_PATH, DEFAULT_TOKEN_PATH) + "gmusic_authtoken"
            if os.path.isfile(_authtoken):
                with open(_authtoken, 'rb') as handle:
                    authtoken = pickle.load(handle)
            else:
                authtoken = None
            _username = config.get(CONF_USERNAME)
            _password = config.get(CONF_PASSWORD, DEFAULT_PASSWORD)
            logged_in = self._api.login(_username, _password, _device_id, authtoken)
            if not logged_in:
                _LOGGER.error("Failed legacy log in, check http://unofficial-google-music-api.readthedocs.io/en/latest/reference/mobileclient.html#gmusicapi.clients.Mobileclient.login")
                return False
            with open(_authtoken, 'wb') as f:
                pickle.dump(self._api.session._authtoken, f)

        elif _login_type == 'oauth':
            _oauth_cred = config.get(CONF_OAUTH_CRED, DEFAULT_OAUTH_CRED)
            if os.path.isfile(_oauth_cred):
                try:
                    logged_in = self._api.oauth_login(_device_id, _oauth_cred)
                    if not logged_in:
                        raise Exception("Login failed! Please check logs for any gmusicapi related WARNING")
                except:
                    raise Exception("Failed oauth login, check https://unofficial-google-music-api.readthedocs.io/en/latest/reference/mobileclient.html#gmusicapi.clients.Mobileclient.perform_oauth")
            else:
                raise Exception("Invalid - Not a file! oauth_cred: ", _oauth_cred)

        else:
            raise Exception("Invalid! login_type: ", _login_type)

        self._name = "gmusic_player"
        self._playlist = "input_select." + config.get(CONF_PLAYLISTS, DEFAULT_PLAYLISTS)
        self._media_player = "input_select." + config.get(CONF_SPEAKERS, DEFAULT_SPEAKERS)
        self._station = "input_select." + config.get(CONF_STATIONS, DEFAULT_STATIONS)
        self._source = "input_select." + config.get(CONF_SOURCE, DEFAULT_SOURCE)

        self._entity_ids = []  ## media_players - aka speakers
        self._playlists = []
        self._playlist_to_index = {}
        self._stations = []
        self._station_to_index = {}
        self._tracks = []
        self._track = []
        self._attributes = {}
        self._next_track_no = 0

        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, self._update_playlists)
        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, self._update_stations)

        self._shuffle = config.get(CONF_SHUFFLE, DEFAULT_SHUFFLE)
        self._shuffle_mode = config.get(CONF_SHUFFLE_MODE, DEFAULT_SHUFFLE_MODE)

        self._unsub_tracker = None
        self._playing = False
        self._state = STATE_OFF
        self._volume = 0.0
        self._is_mute = False
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None
        self._track_artist_cover = None
        self._attributes['_player_state'] = STATE_OFF

    @property
    def name(self):
        """ Return the name of the player. """
        return self._name

    @property
    def icon(self):
        return 'mdi:music-circle'

    @property
    def supported_features(self):
        """ Flag media player features that are supported. """
        return SUPPORT_GMUSIC_PLAYER

    @property
    def should_poll(self):
        """ No polling needed. """
        return False

    @property
    def state(self):
        """ Return the state of the device. """
        return self._state

    @property
    def device_state_attributes(self):
        """ Return the device state attributes. """
        return self._attributes

    @property
    def is_volume_muted(self):
        """ Return True if device is muted """
        return self._is_mute

    @property
    def is_on(self):
        """ Return True if device is on. """
        return self._playing

    @property
    def media_content_type(self):
        """ Content type of current playing media. """
        return MEDIA_TYPE_MUSIC

    @property
    def media_title(self):
        """ Title of current playing media. """
        return self._track_name

    @property
    def media_artist(self):
        """ Artist of current playing media """
        return self._track_artist

    @property
    def media_album_name(self):
        """ Album name of current playing media """
        return self._track_album_name

    @property
    def media_image_url(self):
        """ Image url of current playing media. """
        return self._track_album_cover

    @property
    def media_image_remotely_accessible(self):
        " True  --> entity_picture: http://lh3.googleusercontent.com/Ndilu... "
        " False --> entity_picture: /api/media_player_proxy/media_player.gmusic_player?token=4454... "
        return True
    
    @property
    def volume_level(self):
      """Volume level of the media player (0..1)."""
      return self._volume


    def turn_on(self, *args, **kwargs):
        """ Turn on the selected media_player from input_select """
        self._playing = False
        if not self._update_entity_ids():
            return
        _player = self.hass.states.get(self._entity_ids)
        data = {ATTR_ENTITY_ID: _player.entity_id}
        if _player.state == STATE_OFF:
            self._unsub_tracker = track_state_change(self.hass, _player.entity_id, self._sync_player)
            self._turn_on_media_player(data)
        elif _player.state != STATE_OFF:
            self._turn_off_media_player(data)
            call_later(self.hass, 1, self.turn_on)

    def _turn_on_media_player(self, data=None):
        """Fire the on action."""
        if data is None:
            data = {ATTR_ENTITY_ID: self._entity_ids}
        self._state = STATE_IDLE
        self.schedule_update_ha_state()
        self.hass.services.call(DOMAIN_MP, 'turn_on', data)


    def turn_off(self, entity_id=None, old_state=None, new_state=None, **kwargs):
        """ Turn off the selected media_player """
        self._playing = False
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None

        _player = self.hass.states.get(self._entity_ids)
        data = {ATTR_ENTITY_ID: _player.entity_id}
        self._turn_off_media_player(data)

    def _turn_off_media_player(self, data=None):
        """Fire the off action."""
        self._playing = False
        self._state = STATE_OFF
        self._attributes['_player_state'] = STATE_OFF
        self.schedule_update_ha_state()
        if data is None:
            data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'turn_off', data)


    def _update_entity_ids(self):
        """ sets the current media_player from input_select """
        media_player = self.hass.states.get(self._media_player)
        if media_player is None:
            _LOGGER.error("(%s) is not a valid input_select entity.", self._media_player)
            return False
        _entity_ids = "media_player." + media_player.state
        if self.hass.states.get(_entity_ids) is None:
            _LOGGER.error("(%s) is not a valid media player.", media_player.state)
            return False
        # Example: self._entity_ids = media_player.bedroom_stereo
        self._entity_ids = _entity_ids
        return True


    def _sync_player(self, entity_id=None, old_state=None, new_state=None):
        """ Perform actions based on the state of the selected media_player """
        # self._unsub_tracker = track_state_change(self.hass, self._entity_ids, self._sync_player)
        if not self._playing:
            return
        _player = self.hass.states.get(self._entity_ids)

        """ full state of device _player, include attributes. """
        #self._attributes['_player_full'] = _player

        """ entity_id of _player. """
        _player_id = _player.entity_id
        self._attributes['_player_id'] = _player_id

        """ _player "friendley_name" """
        _player_friendly = _player.attributes['friendly_name']
        self._attributes['_player_friendly'] = _player_friendly

        """ _player state - Example [playing -or- idle]. """
        _player_state = _player.state
        self._attributes['_player_state'] = _player_state

        """ Set new volume if it has been changed on the _player """
        if 'volume_level' in _player.attributes:
            self._volume = round(_player.attributes['volume_level'],2)

        if _player.state == 'off':
            self._state = STATE_OFF
            self.turn_off()

        self.schedule_update_ha_state()


    def _update_playlists(self, now=None):
        """ Sync playlists from Google Music library """
        self._playlist_to_index = {}
        self._playlists = self._api.get_all_user_playlist_contents()
        idx = -1
        for playlist in self._playlists:
            idx = idx + 1
            name = playlist.get('name','')
            if len(name) < 1:
                continue
            self._playlist_to_index[name] = idx

        playlists = list(self._playlist_to_index.keys())
        self._attributes['playlists'] = playlists

        data = {"options": list(playlists), "entity_id": self._playlist}
        self.hass.services.call(input_select.DOMAIN, input_select.SERVICE_SET_OPTIONS, data)


    def _update_stations(self, now=None):
        """ Sync stations from Google Music library """
        self._station_to_index = {}
        self._stations = self._api.get_all_stations()
        idx = -1
        for station in self._stations:
            idx = idx + 1
            name = station.get('name','')
            library = station.get('inLibrary')
            if len(name) < 1:
                continue
            if library == True:
                self._station_to_index[name] = idx

        stations = list(self._station_to_index.keys())
        stations.insert(0,"I'm Feeling Lucky")
        self._attributes['stations'] = stations

        data = {"options": list(stations), "entity_id": self._station}
        self.hass.services.call(input_select.DOMAIN, input_select.SERVICE_SET_OPTIONS, data)


    def _load_playlist(self):
        """ Load selected playlist to the track_queue """
        if not self._update_entity_ids():
            return
        """ if source == Playlist """
        _playlist_id = self.hass.states.get(self._playlist)
        if _playlist_id is None:
            _LOGGER.error("(%s) is not a valid input_select entity.", self._playlist)
            return  
        
        playlist = _playlist_id.state        
        idx = self._playlist_to_index.get(playlist)
        if idx is None:
            _LOGGER.error("playlist to index is none!")
            self._turn_off_media_player()
            return
        self._tracks = self._playlists[idx]['tracks']        
        
        #self.log("Loading [{}] Tracks From: {}".format(len(self._tracks), _playlist_id))
        random.shuffle(self._tracks)
        self._next_track_no = -1
        self._play()       


    def _load_station(self):
        """ Load selected station to the track_queue """
        if not self._update_entity_ids():
            return        
        """ if source == station """
        _station_id = self.hass.states.get(self._station)
        if _station_id is None:
            _LOGGER.error("(%s) is not a valid input_select entity.", self._station)
            return
        
        station = _station_id.state        
        if station == "I'm Feeling Lucky":
            self._tracks = self._api.get_station_tracks('IFL', num_tracks=100)
        else:
            idx = self._station_to_index.get(station)
            if idx is None:
                self._turn_off_media_player()
                return
            _id = self._stations[idx]['id']
            self._tracks = self._api.get_station_tracks(_id, num_tracks=100)
        
        # self.log("Loading [{}] Tracks From: {}".format(len(self._tracks), _station_id))
        self._next_track_no = -1
        self._play()

    def _play(self):
        self._playing = True
        self._unsub_tracker = track_state_change(self.hass, self._entity_ids, self._get_track, from_state='playing', to_state='idle')
        self._get_track()


    def _get_track(self, entity_id=None, old_state=None, new_state=None, retry=3):
        """ Get a track and play it from the track_queue. """
        if not self._playing:
            return
        _track = None
        
        _total_tracks = len(self._tracks)
        self._next_track_no = self._next_track_no + 1
        
        if self._next_track_no >= _total_tracks:
            random.shuffle(self._tracks)    ## (re)Shuffle on Loop
            self._next_track_no = 0         ## Restart curent playlist (Loop)
            
        try:
            _track = self._tracks[self._next_track_no]
        except IndexError:
            _LOGGER.error("Out of range! Number of tracks in track_queue == (%s)", _total_tracks)
            self._turn_off_media_player() 
            
        if _track is None:
            self._turn_off_media_player() 
            return
        """ If source is a playlist, track is inside of track """
        if 'track' in _track:
            _track = _track['track']
        """ Find the unique track id. """
        if 'trackId' in _track:
            uid = _track['trackId']
        elif 'storeId' in _track:
            uid = _track['storeId']
        elif 'id' in _track:
            uid = _track['id']
        else:
            _LOGGER.error("Failed to get ID for track: (%s)", _track)
            if retry < 1:
                self._turn_off_media_player()
                return
            return self._get_track(retry=retry-1)
        """ If available, get track information. """
        if 'title' in _track:
            self._track_name = _track['title']
        else:
            self._track_name = None
        if 'artist' in _track:
            self._track_artist = _track['artist']
        else:
            self._track_artist = None
        if 'album' in _track:
            self._track_album_name = _track['album']
        else:
            self._track_album_name = None
        if 'albumArtRef' in _track:
            _album_art_ref = _track['albumArtRef']   ## returns a list
            self._track_album_cover = _album_art_ref[0]['url'] ## of dic
        else:
            self._track_album_cover = None
        if 'artistArtRef' in _track:
            _artist_art_ref = _track['artistArtRef']
            self._track_artist_cover = _artist_art_ref[0]['url']
        else:
            self._track_artist_cover = None
        """ Get the stream URL and play on media_player """
        try:
            _url = self._api.get_stream_url(uid)
        except Exception as err:
            _LOGGER.error("Failed to get URL for track: (%s)", uid)
            if retry < 1:
                self._turn_off_media_player()
                return
            return self._get_track(retry=retry-1)
        self._state = STATE_PLAYING
        self.schedule_update_ha_state()
        data = {
            ATTR_MEDIA_CONTENT_ID: _url,
            ATTR_MEDIA_CONTENT_TYPE: "audio/mp3",
            ATTR_ENTITY_ID: self._entity_ids
            }
        self.hass.services.call(DOMAIN_MP, SERVICE_PLAY_MEDIA, data)


    def play_media(self, media_type, media_id):
        if media_type == "station":
             _LOGGER.error("(%s): (%s)",  media_type, media_id)
            #data = media_id
            #self.hass.services.call(input_select, select_option, media_id)        
            #self._load_station
        elif media_type == "playlist":
            #self._load_playlist(media_id)
            _LOGGER.error("(%s): (%s)",  media_type, media_id)

    def media_play(self, **kwargs):
        """Send play command."""
        if self._state == STATE_PAUSED:
            self._state = STATE_PLAYING
            self.schedule_update_ha_state()
            data = {ATTR_ENTITY_ID: self._entity_ids}
            self.hass.services.call(DOMAIN_MP, 'media_play', data)
        else:
            _source = self.hass.states.get(self._source)
            source = _source.state
            if source == 'Playlist':
                self._load_playlist()
            elif source == 'Station':
                self._load_station()
            else:
                _LOGGER.error("Invalid source: (%s)", source)
                self.turn_off()
                return

    def media_pause(self, **kwargs):
        """ Send media pause command to media player """
        self._state = STATE_PAUSED
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'media_pause', data)

    def media_play_pause(self, **kwargs):
        """Simulate play pause media player."""
        if self._state == STATE_PLAYING:
            self.media_pause()
        else:
            self.media_play()

    def media_previous_track(self, **kwargs):
        """Send the previous track command."""
        if self._state == STATE_PAUSED or self._state == STATE_PLAYING:
            self._next_track_no = self._next_track_no - 2
            self.hass.states.set(self._entity_ids, STATE_IDLE)
            self.schedule_update_ha_state()
    
    def media_next_track(self, **kwargs):
        """Send next track command."""
        if self._state == STATE_PAUSED or self._state == STATE_PLAYING:
            self.hass.states.set(self._entity_ids, STATE_IDLE)
            self.schedule_update_ha_state()
    
    def media_stop(self, **kwargs):
        """Send stop command."""
        self._state = STATE_IDLE
        self._playing = False
        self._track_artist = None
        self._track_album_name = None
        self._track_name = None
        self._track_album_cover = None
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'media_stop', data)        
    

    def set_volume_level(self, volume):
        """Set volume level."""
        #self._client.set_volume(int(100 * volume))
        data = {ATTR_ENTITY_ID: self._entity_ids, 'volume_level': volume}
        self.hass.services.call(DOMAIN_MP, 'volume_set', data)

    def volume_up(self, **kwargs):
        """Volume up the media player."""
        # newvolume = min(self._client.volume + 4, 100)
        # self._client.set_volume(newvolume)
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'volume_up', data)

    def volume_down(self, **kwargs):
        """Volume down media player."""
        # newvolume = max(self._client.volume - 4, 0)
        # self._client.set_volume(newvolume)
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'volume_down', data)

    def mute_volume(self, mute):
        """Send mute command."""
        if self._is_mute == False:
            self._is_mute = True
        else:
            self._is_mute = False
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._entity_ids, "is_volume_muted": self._is_mute}
        self.hass.services.call(DOMAIN_MP, 'volume_mute', data)
