"""
Support Google Music as a media player
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

from homeassistant.const import (
    ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_START,
    STATE_PLAYING, STATE_PAUSED, STATE_OFF, STATE_IDLE)

from homeassistant.components.media_player import (
    MediaPlayerDevice, PLATFORM_SCHEMA)

from homeassistant.components.media_player import (
    SERVICE_TURN_ON, SERVICE_TURN_OFF,
    SERVICE_PLAY_MEDIA, SERVICE_MEDIA_PAUSE,
    SERVICE_VOLUME_UP, SERVICE_VOLUME_DOWN, SERVICE_VOLUME_SET,
    ATTR_MEDIA_CONTENT_ID, ATTR_MEDIA_CONTENT_TYPE, DOMAIN as DOMAIN_MP)

from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC, SUPPORT_NEXT_TRACK, SUPPORT_PAUSE,
    SUPPORT_PLAY, SUPPORT_PREVIOUS_TRACK, SUPPORT_SELECT_SOURCE, SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET, SUPPORT_VOLUME_STEP, SUPPORT_TURN_ON, SUPPORT_TURN_OFF)

from homeassistant.helpers.event import track_state_change #, track_time_change
import homeassistant.components.input_select as input_select

# The domain of your component. Should be equal to the name of your component.
DOMAIN = 'gmusic_player'

CONF_USERNAME = 'user'
CONF_PASSWORD = 'password'
CONF_DEVICE_ID = 'device_id'
CONF_SOURCE = 'source'
CONF_PLAYLISTS = 'playlist'
CONF_STATIONS = 'station'
CONF_SPEAKERS = 'media_player'
CONF_TOKEN_PATH = 'token_path'

DEFAULT_TOKEN_PATH = "./."

SUPPORT_GMUSIC = SUPPORT_PAUSE | SUPPORT_VOLUME_STEP | \
    SUPPORT_PREVIOUS_TRACK | SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE | \
    SUPPORT_PLAY | SUPPORT_TURN_ON | SUPPORT_TURN_OFF | \
    SUPPORT_SELECT_SOURCE | SUPPORT_NEXT_TRACK

                  
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required(CONF_SOURCE): cv.string,
        vol.Required(CONF_PLAYLISTS): cv.string,
        vol.Required(CONF_STATIONS): cv.string,
        vol.Required(CONF_SPEAKERS): cv.string,
        vol.Optional(CONF_TOKEN_PATH, default=DEFAULT_TOKEN_PATH): cv.string,
    })
}, extra=vol.ALLOW_EXTRA)

# Shortcut for the logger
_LOGGER = logging.getLogger(__name__)

def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the Gmusic player."""
    add_devices([GmusicComponent(hass, config)])
    return True

class GmusicComponent(MediaPlayerDevice):
    def __init__(self, hass, config):
        from gmusicapi import Mobileclient
        # https://github.com/simon-weber/gmusicapi/issues/424
        class GMusic(Mobileclient):
            def login(self, username, password, device_id, authtoken=None):
                if authtoken:
                    self.android_id               = device_id
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
                raise SystemExit
        
        self.hass = hass
        authtoken_path = config.get(CONF_TOKEN_PATH, DEFAULT_TOKEN_PATH) + "gmusic_authtoken"
        if os.path.isfile(authtoken_path):
            with open(authtoken_path, 'rb') as handle:
                authtoken = pickle.load(handle)
        else:
            authtoken = None
        
        self._api = GMusic()
        logged_in = self._api.login(config.get(CONF_USERNAME), config.get(CONF_PASSWORD), config.get(CONF_DEVICE_ID), authtoken)
        if not logged_in:
            _LOGGER.error("Failed to log in, check http://unofficial-google-music-api.readthedocs.io/en/latest/reference/mobileclient.html#gmusicapi.clients.Mobileclient.login")
            return False
        with open(authtoken_path, 'wb') as f:
            pickle.dump(self._api.session._authtoken, f)
        
        self._name = "gmusic_player"
        ## NOTE: Consider rename here. Example 'self._playlist' -->>> 'self._playlist_select' or 'self._select_playlist'
        self._playlist = "input_select." + config.get(CONF_PLAYLISTS)
        self._media_player = "input_select." + config.get(CONF_SPEAKERS)
        self._station = "input_select." + config.get(CONF_STATIONS)
        self._source = "input_select." + config.get(CONF_SOURCE)
        
        self._entity_ids = []  ## media_players or speakers
        
        self._playlists = []
        self._playlist_to_index = {}
        self._stations = []
        self._station_to_index = {}
        self._tracks = []
        self._track = []
        self._next_track_no = 0
        
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None
        
        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, self._update_playlists)
        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, self._update_stations)
        
        self._playing = False
        self._is_mute = False
        self._unsub_tracker = None
        self._state = STATE_OFF
    
    @property
    def name(self):
        """Return the name of the player."""
        return self._name

    @property
    def icon(self):
        return 'mdi:play'

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        return SUPPORT_GMUSIC

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def is_volume_muted(self):
        return self._is_mute

    @property
    def is_on(self):
        """Return True if device is on."""
        return self._playing
    
    @property
    def media_content_type(self):
        """Content type of current playing media."""
        return MEDIA_TYPE_MUSIC
   
    @property
    def media_title(self):
        """Title of current playing media."""
        return self._track_name

    @property
    def media_artist(self):
        """Artist of current playing media, music track only."""
        return self._track_artist

    @property
    def media_album_name(self):
        """Album name of current playing media, music track only."""
        return self._track_album_name
  
    @property
    def media_image_url(self):
        """Image url of current playing media."""
        return self._track_album_cover
    
    @property
    def media_image_remotely_accessible(self):
        return True
    
    '''
    @property
    def volume_level(self):
      """Volume level of the media player (0..1)."""
      return self._volume

    @property
    def source(self):
        """Return  current source name."""
        source_name = "Unknown"
        client = self._client
        if client.active_playlist_id in client.playlists:
            source_name = client.playlists[client.active_playlist_id]['name']
        return source_name

    @property
    def source_list(self):
        """List of available input sources."""
        source_names = [s["name"] for s in self._client.playlists.values()]
        return source_names

    def select_source(self, source):
        """Select input source."""
        client = self._client
        sources = [s for s in client.playlists.values() if s['name'] == source]
        if len(sources) == 1:
            client.change_song(sources[0]['id'], 0)
    '''

    def turn_on(self, **kwargs):
        """Fire the on action."""
        self._playing = False
        self._state = STATE_IDLE
        if not self._update_entity_ids():
            return         
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'turn_on', data)
    
    def turn_off(self, **kwargs):
        """Fire the off action."""
        self._playing = False
        self._state = STATE_OFF
        #self._clear_track_meta()
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'turn_off', data)
    
    def _turn_off_media_player(self):
        """ from existing code """
        self.turn_off()

    def _clear_track_meta(self):
        self._track_name = None
        self._track_artist = None
        self._track_album_name = None
        self._track_album_cover = None
        self.schedule_update_ha_state()
        
    '''
    def select_media_player(self):
        self._player_id = "media_player."+self.get_state(self.select_player)
        ## Set callbacks for media player
        self.power_off = self.listen_state(self.power, self.boolean_power, new="off", duration="1")
        self.advance_track = self.listen_state(self.get_track, self._player_id, new="idle",  duration="2")
        self.show_meta = self.listen_state(self.show_info, self._player_id, new="playing")
        self.clear_meta = self.listen_state(self.clear_info, self._player_id, new="off", duration="1")
  
    def unselect_media_player(self):
        self.media_player_off(entity=None,attribute=None,old=None,new=None,kwargs=None)
        try: ## Cancel callbacks for media player
            self.cancel_listen_state(self.power_off)
            self.cancel_listen_state(self.advance_track)
            self.cancel_listen_state(self.show_meta)
            self.cancel_listen_state(self.clear_meta)
        except:
            self.log("cancel callback exception!")
            pass
    '''

    def _update_entity_ids(self):
        media_player = self.hass.states.get(self._media_player)
        if media_player is None:
            _LOGGER.error("%s is not a valid input_select entity.", self._media_player)
            return False
        _entity_ids = "media_player." + media_player.state
        if self.hass.states.get(_entity_ids) is None:
            _LOGGER.error("%s is not a valid media player.", media_player.state)
            return False
        self._entity_ids = _entity_ids 
        return True


    def _update_playlists(self, now=None):
        """ Sync playlists from Google Music library """
        if self.hass.states.get(self._playlist) is None:
            _LOGGER.error("%s is not a valid input_select entity.", self._playlist)
            return
        self._playlist_to_index = {}
        self._playlists = self._api.get_all_user_playlist_contents()
        idx = -1
        for playlist in self._playlists:
            idx = idx + 1
            name = playlist.get('name','')
            if len(name) < 1:
                continue
            self._playlist_to_index[name] = idx
        data = {"options": list(self._playlist_to_index.keys()), "entity_id": self._playlist}
        self.hass.services.call(input_select.DOMAIN, input_select.SERVICE_SET_OPTIONS, data)

    def _update_stations(self, now=None):
        """ Sync stations from Google Music library """
        if self.hass.states.get(self._station) is None:
            _LOGGER.error("%s is not a valid input_select entity.", self._station)
            return
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
        options = list(self._station_to_index.keys())
        options.insert(0,"I'm Feeling Lucky")
        data = {"options": list(options), "entity_id": self._station}
        self.hass.services.call(input_select.DOMAIN, input_select.SERVICE_SET_OPTIONS, data)               



    def _load_playlist(self):
        """ load tracks from the selected playlist to the track_queue """
        if not self._update_entity_ids():
            return        
        """ if source == Playlist """
        _playlist_id = self.hass.states.get(self._playlist)
        if _playlist_id is None:
            _LOGGER.error("%s is not a valid input_select entity.", self._playlist)
            return  
        
        option = _playlist_id.state        
        idx = self._playlist_to_index.get(option)
        if idx is None:
            self._turn_off_media_player()
            return
        
        self._tracks = self._playlists[idx]['tracks']
        
        #self.log("Loading [{}] Tracks From: {}".format(len(self._tracks), _playlist_id))
        random.shuffle(self._tracks)
        self._next_track_no = -1
        """ Playlist End"""
        
        self._playing = True
        self._get_track()        
        ## NOTE: Move this to connect or power on
        self._unsub_tracker = track_state_change(self.hass, self._entity_ids, self._get_track, from_state='playing', to_state='idle')


    def _load_station(self):
        """ load tracks from the selected station to the track_queue """
        if not self._update_entity_ids():
            return        
        """ if source == station """
        _station_id = self.hass.states.get(self._station)
        if _station_id is None:
            _LOGGER.error("%s is not a valid input_select entity.", self._station)
            return
        
        _option = _station_id.state        
        if _option == "I'm Feeling Lucky":
            self._tracks = self._api.get_station_tracks('IFL', num_tracks=100)
        else:
            idx = self._station_to_index.get(_option)
            if idx is None:
                self._turn_off_media_player()
                return
            _id = self._stations[idx]['id']
            self._tracks = self._api.get_station_tracks(_id, num_tracks=100)
        
        # self.log("Loading [{}] Tracks From: {}".format(len(self._tracks), _station_id))
        self._next_track_no = -1
        """ station end """
        
        self._playing = True
        self._get_track()
        ## NOTE: Move this to connect or power on
        self._unsub_tracker = track_state_change(self.hass, self._entity_ids, self._get_track, from_state='playing', to_state='idle')



    def _get_track(self, entity_id=None, old_state=None, new_state=None, retry=3):
        """ get a track from the track_queue """
        if not self._playing:
            return
        
        self._track = ''
        self._next_track_no = self._next_track_no + 1
        
        if self._next_track_no >= len(self._tracks):
            self._next_track_no = 0         ## Restart curent playlist (Loop)
            random.shuffle(self._tracks)    ## (re)Shuffle on Loop
            
        _track = self._tracks[self._next_track_no]
        if _track is None:
            self._turn_off_media_player() 
            return
        
        """ reset track if needed """
        if 'track' in _track:
            _track = _track['track']
            self._track = _track
        
        """ get the track id """
        if 'trackId' in _track:
            _uid = _track['trackId']
        elif 'storeId' in _track:
            _uid = _track['storeId']
        elif 'id' in _track:
            _uid = _track['id']
        else:
            _LOGGER.error("Failed to get ID for track: (%s)", _track)
            if retry < 1:
                self._turn_off_media_player()
                return
            return self._get_track(retry=retry-1)
        
        """ get track meta_data """
        if 'artist' in _track:
            self._track_artist = _track['artist']
        if 'album' in _track: 
            self._track_album_name = _track['album']
        if 'title' in _track: 
            self._track_name = _track['title']
        if 'albumArtRef' in _track:
            _album_art_ref = _track['albumArtRef']   ## returns a list
            self._track_album_cover = _album_art_ref[0]['url'] ## of dic
        if 'artistArtRef' in _track:
            _artist_art_ref = _track['artistArtRef']
            _cover2 = _artist_art_ref[0]['url']         
        
        self._play_track(_uid, retry)

    
    def _play_track(self, uid, retry):
        """ get the stream URL and play track on speakers """
        try:
            _url = self._api.get_stream_url(uid)        
        except Exception as err:
            _LOGGER.error("Failed to get URL for track: (%s)", uid)
            if retry < 1:
                self._turn_off_media_player()
                return
            return self._get_track(retry=retry-1)
        
        data = {
            ATTR_MEDIA_CONTENT_ID: _url,
            ATTR_MEDIA_CONTENT_TYPE: "audio/mp3",
            ATTR_ENTITY_ID: self._entity_ids
            }
        
        self._state = STATE_PLAYING
        self.schedule_update_ha_state()
        self.hass.services.call(DOMAIN_MP, SERVICE_PLAY_MEDIA, data)

    
    def media_play_pause(self, **kwargs):
        """Simulate play pause media player."""
        if self._state == STATE_PLAYING:
            self.media_pause()
        else:
            self.media_play()

    def media_play(self, **kwargs):
        """Send play command."""
        if self._state == STATE_PAUSED:
            self._state = STATE_PLAYING
            self.schedule_update_ha_state()  
            data = {ATTR_ENTITY_ID: self._entity_ids}
            self.hass.services.call(DOMAIN_MP, 'media_play', data)
        else:
            _source = self.hass.states.get(self._source)
            _option = _source.state
            if _option == 'Playlist':
                self._load_playlist()
            elif _option == 'Station':
                self._load_station()
            else:
                _LOGGER.error("Invalid source: (%s)", _option)
                self._turn_off_media_player()
                return

    def media_pause(self, **kwargs):
        """ Send media pause command to media player """
        self._state = STATE_PAUSED
        self.schedule_update_ha_state()
        data = {ATTR_ENTITY_ID: self._entity_ids}
        self.hass.services.call(DOMAIN_MP, 'media_pause', data)
    
    def media_next_track(self, **kwargs):
        """Send next track command."""
        if self._state == STATE_PAUSED or self._state == STATE_PLAYING:
            self.hass.states.set(self._entity_ids, STATE_IDLE)
            self.schedule_update_ha_state()

    def media_previous_track(self, **kwargs):
        """Send the previous track command."""
        if self._state == STATE_PAUSED or self._state == STATE_PLAYING:
            self._next_track_no = self._next_track_no - 2
            self.hass.states.set(self._entity_ids, STATE_IDLE)
            self.schedule_update_ha_state()
    

    def mute_volume(self, mute):
        """Send mute command."""
        #self._client.set_volume(0)
        if self._is_mute == False:
            self._is_mute = True
        else:
            self._is_mute = False
        data = {ATTR_ENTITY_ID: self._entity_ids, "is_volume_muted": self._is_mute}
        self.hass.services.call(DOMAIN_MP, 'volume_mute', data)
        self.schedule_update_ha_state()

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
