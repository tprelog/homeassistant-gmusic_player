import appdaemon.plugins.hass.hassapi as hass
from gmusicapi import Mobileclient
import random
import pickle
import os.path

''' version: 0.0.2 '''
class GMAAC(hass.Hass):
  def initialize(self):
    self.gmc = Mobileclient()
    
    self.boolean_connect = self.args["boolean_connect"]
    self.boolean_sync = self.args["boolean_sync"]
    self.boolean_power = self.args["boolean_power"]
    self.select_player = self.args["select_player"]
    self.select_playlist = self.args["select_playlist"]
    self.select_station = self.args["select_station"]
    self.boolean_load_pl = self.args["boolean_load_pl"]
    self.select_source = self.args["select_source"]
    self.boolean_next = self.args["boolean_next"]
    self.boolean_prev = self.args["boolean_prev"]
    
    self.turn_off(self.boolean_connect)

    self._player_id = ''
    self._playlist_id = ''
    self._playlists = []
    self._playlist_to_index = {}
    self._station_id = ''
    self._stations = []
    self._station_to_index = {}
    self._tracks = []
    self._next_track_no = 0
    self._track = []
    
    self._source = self.get_state(self.select_source)

    self.listen_state(self.connect, self.boolean_connect)
    self.listen_state(self.power, self.boolean_power, new="on")
    self.listen_state(self.sync, self.boolean_sync, new="on")  
    self.listen_state(self.set_source, self.select_source)
    self.listen_state(self.get_tracks, self.boolean_load_pl, new="on")
    self.listen_state(self.next_track, self.boolean_next, new="on")
    self.listen_state(self.prev_track, self.boolean_prev, new="on")
    
    self.turn_on(self.boolean_connect)

  def reset_booleans(self):
    '''
    Do not include "boolean_connect" here!
    - NOT HERE: self.turn_off(self.boolean_connect)
    That should be turned off directly when needed
    '''
    self.turn_off(self.boolean_load_pl)
    self.turn_off(self.boolean_sync)
    self.turn_off(self.boolean_power)
    self.turn_off(self.boolean_next)
    self.turn_off(self.boolean_prev)

  def login(self):
    _login = self.args["login_type"]
    if _login == 'oauth':
      self.oauth_login()
    elif _login == 'legacy':
      self.legacy_login()
    else:
      self.turn_off(self.boolean_connect)
      raise SystemExit("Invalid login_type: {}".format(_login))

  def legacy_login(self):
    ''' This legacy login may stop working at any time '''
    authtoken_path = self.args["authtoken_path"] + "gmusic_authtoken"
    email=self.args["user"]
    password=self.args["password"]
    device_id=self.args["device_id"]
    if os.path.isfile(authtoken_path):
      with open(authtoken_path, 'rb') as handle:
        authtoken = pickle.load(handle)
    else:
      authtoken = None
    self._api_login = self.gmc.login(email, password, device_id, authtoken)
    if not self._api_login:
      self.turn_off(self.boolean_connect)
      raise SystemExit("legacy login failed")
    with open(authtoken_path, 'wb') as f:
      pickle.dump(self.gmc.session._authtoken, f)

  def oauth_login(self):
    if self.args["oauth_credentials"]:
      try:
        self._api_login = self.gmc.oauth_login(device_id=self.args["device_id"], oauth_credentials=self.args["oauth_credentials"], locale=self.args["locale"])
      except:
        self.turn_off(self.boolean_connect)
        raise SystemExit("oauth login failed")


  def connect(self, entity, attribute, old, new, kwargs):
    _connect = self.get_state(self.boolean_connect)
    self.reset_booleans()
    if _connect == "on":
      self.login()
      if self._api_login == True:
        self.sync(entity=None,attribute=None,old=None,new=None,kwargs=None)
    else: ## This will not trigger when app level constaint is set on the input_boolean
        self.gmusic_api_logout(entity=None,attribute=None,old=None,new=None,kwargs=None)


  def power(self, entity, attribute, old, new, kwargs):
    self._power = self.get_state(self.boolean_power)
    if self._power == "on":
      self.select_media_player()
      self.log("Powered ON -- Connected: {}".format(self._player_id))
    elif self._power == "off":
      self.unselect_media_player()
      self.log("Powered OFF -- Disconnected: {}".format(self._player_id))

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


  def update_playlists(self, entity, attribute, old, new, kwargs):
    self._playlist_to_index = {}
    self._playlists = self.gmc.get_all_user_playlist_contents()
    idx = -1
    for playlist in self._playlists:
      idx = idx + 1
      name = playlist.get('name',' ')
      if len(name) < 1:
        continue
      self._playlist_to_index[name] = idx
      # self.log("Playlist: {} - {}".format(idx, name))
    data = list(self._playlist_to_index.keys())
    self.call_service("input_select/set_options", entity_id=self.select_playlist, options=data)
    self.turn_off(self.boolean_sync)

    self.log("--------------------------------------------")
    self.log(data)
    for _pl in self._playlist_to_index:
      _num = self._playlist_to_index.get(_pl) + 1
      self.log("{}: {}".format(_num, _pl))
    self.log("--------------------------------------------")


  def update_stations(self, entity, attribute, old, new, kwargs):
    self._station_to_index = {}
    self._stations = self.gmc.get_all_stations()
    idx = -1
    for station in self._stations:
      idx = idx + 1
      name = station.get('name',' ')
      library = station.get('inLibrary')
      if len(name) < 1:
        continue
      if library == True:
        self._station_to_index[name] = idx
        # self.log("station: {} - {}: Library = {}".format(idx, name, library))    
    data = list(self._station_to_index.keys())
    data.insert(0,"I'm Feeling Lucky")
    self.call_service("input_select/set_options", entity_id=self.select_station, options=data)
    self.turn_off(self.boolean_sync)

    self.log("--------------------------------------------")
    self.log(data)
    for _pl in self._station_to_index:
      _num = self._station_to_index.get(_pl) + 1
      self.log("{}: {}".format(_num, _pl))
    self.log("--------------------------------------------")

  def sync(self, entity, attribute, old, new, kwargs):
    self.update_playlists(entity=None,attribute=None,old=None,new=None,kwargs=None)
    self.update_stations(entity=None,attribute=None,old=None,new=None,kwargs=None)

  def set_source(self, entity, attribute, old, new, kwargs):
    self._source = self.get_state(self.select_source)

  def get_tracks(self, entity, attribute, old, new, kwargs):
    if self._source == 'Station':
      self.load_station(entity=None,attribute=None,old=None,new=None,kwargs=None)
    elif self._source == 'Playlist':
      self.load_playlist(entity=None,attribute=None,old=None,new=None,kwargs=None)
    else:
      self.log("invalid source: {}".format(self._source))
      self.reset_booleans()


  def load_playlist(self, entity, attribute, old, new, kwargs):
    self.turn_on(self.boolean_power)
    self._playlist_id = self.get_state(self.select_playlist)

    idx = self._playlist_to_index.get(self._playlist_id)
    self._tracks = self._playlists[idx]['tracks']
    random.shuffle(self._tracks)

    self.log("--------------------------------------------")
    self.log("Loading [{}] Tracks From: {}".format(len(self._tracks), self._playlist_id))
    # self.log(self._tracks)
    self.log("--------------------------------------------")
    
    self._next_track_no = -1
    self.get_track(entity=None,attribute=None,old=None,new=None,kwargs=None)
    self.turn_off(self.boolean_load_pl)


  def load_station(self, entity, attribute, old, new, kwargs):
    self.turn_on(self.boolean_power)
    self._station_id = self.get_state(self.select_station)
    if self._station_id == "I'm Feeling Lucky":
      self._tracks = self.gmc.get_station_tracks('IFL', num_tracks=100)
    else:      
      idx = self._station_to_index.get(self._station_id)
      id = self._stations[idx]['id']
      self._tracks = self.gmc.get_station_tracks(id, num_tracks=100)

    self.log("--------------------------------------------")
    self.log("Loading [{}] Tracks From: {}".format(len(self._tracks), self._station_id))
    # self.log(self._tracks)
    self.log("--------------------------------------------")
    
    self._next_track_no = -1
    self.get_track(entity=None,attribute=None,old=None,new=None,kwargs=None)
    self.turn_off(self.boolean_load_pl)


  def get_track(self, entity, attribute, old, new, kwargs):
    self._track = ''    
    self._next_track_no = self._next_track_no + 1
    if self._next_track_no >= len(self._tracks):
      self._next_track_no = 0       ## Restart curent playlist (Loop)
      random.shuffle(self._tracks)  ## (re)Shuffle on Loop
    
    _track = self._tracks[self._next_track_no]
    if _track is None:
      self.reset_booleans()
    if 'track' in _track:
      _track = _track['track']
    self._track = _track
    
    if 'trackId' in _track:
      _uid = _track['trackId']
    elif 'storeId' in _track:
      _uid = _track['storeId']
    elif 'id' in _track:
      _uid = _track['id']
    else:
      self.log("TRACK ID NOT FOUND!")
    
    self.play_track(_uid)


  def play_track(self, uid):
    try:
      _url = self.gmc.get_stream_url(uid)
      self.call_service("media_player/play_media", entity_id = self._player_id, media_content_id = _url, media_content_type = self.args["media_type"])
    except:
      self.log(" --- FAILED TO PLAY TRACK --- ")
      self.log("uid: {}".format(uid))
      self.log("_url: {}".format(_url))
      # self.get_track(entity=None,attribute=None,old=None,new=None,kwargs=None)


  def next_track (self, entity, attribute, old, new, kwargs):
    if new == 'on':
      self.get_track(entity=None,attribute=None,old=None,new=None,kwargs=None)
      self.turn_off(self.boolean_next)    

  def prev_track (self, entity, attribute, old, new, kwargs):
    if new == 'on':
      self._next_track_no = self._next_track_no - 2
      self.get_track(entity=None,attribute=None,old=None,new=None,kwargs=None)
      self.turn_off(self.boolean_prev)


  def show_info (self, entity, attribute, old, new, kwargs):
    _attr = {}
    _track = self._track
    if 'artist' in _track:
      _attr['media_artist'] = _track['artist']
    if 'album' in _track: 
      _attr['media_album_name'] = _track['album']
    if 'title' in _track: 
      _attr['media_title'] = _track['title']
    if 'albumArtRef' in _track:
      _album_art_ref = _track['albumArtRef']   ## returns a list
      _attr['entity_picture'] = _album_art_ref[0]['url'] ## of dic
    if 'artistArtRef' in _track:
      _artist_art_ref = _track['artistArtRef']
      self.artist_art = _artist_art_ref[0]['url']
    if _attr:
     self.set_state(self._player_id, attributes=_attr)
  
  def clear_info (self, entity, attribute, old, new, kwargs):
    if new != 'playing' or new != 'paused':
      self.set_state(self._player_id, attributes={"media_title":'', "media_artist":'', "media_album_name":'', "entity_picture":''})


  def media_player_off(self, entity, attribute, old, new, kwargs):
    self.call_service("media_player/turn_off", entity_id = self._player_id)

  def gmusic_api_logout(self, entity, attribute, old, new, kwargs):
    self.gmc.logout()
    self.reset_booleans()
