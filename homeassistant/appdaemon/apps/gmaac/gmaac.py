import appdaemon.plugins.hass.hassapi as hass
from gmusicapi import Mobileclient
import random
import pickle
import os.path

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
    self.select_playmode = self.args["select_mode"]

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
    self._song = []

    self.artist = ''
    self.artist_art = ''
    self.album = ''
    self.album_art = ''
    self.title = ''

    self._playmode = self.get_state(self.select_playmode)

    self.listen_state(self.connect, self.boolean_connect)
    self.listen_state(self.power, self.boolean_power, new="on")
    self.listen_state(self.sync, self.boolean_sync, new="on")  
    self.listen_state(self.playmode, self.select_playmode)
    self.listen_state(self.get_tracks, self.boolean_load_pl, new="on")
   
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

  def login(self):
    mode=self.args["login_type"]
    if mode == 'oauth':
      self.oauth_login()
    elif mode == 'legacy':
      self.legacy_login()
    else:
      self.turn_off(self.boolean_connect)
      raise SystemExit("Invalid login_type: {}".format(mode))

  def legacy_login(self):
    ''' This legacy login may stop working at any time '''
    authtoken_path = ".gm_authtoken"
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

  def playmode(self, entity, attribute, old, new, kwargs):
    self._playmode = self.get_state(self.select_playmode)

  def get_tracks(self, entity, attribute, old, new, kwargs):
    if self._playmode == 'Station':
      self.load_station(entity=None,attribute=None,old=None,new=None,kwargs=None)
    elif self._playmode == 'Playlist':
      self.load_playlist(entity=None,attribute=None,old=None,new=None,kwargs=None)
    else:
      self.log("invalid playmode: {}".format(self._playmode))
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
    # self.log("--------------------------------------------")
    # self.log("--- GET TRACK ----------------")
    self._song = ''
    self._next_track_no = self._next_track_no + 1

    if self._next_track_no >= len(self._tracks):
      self._next_track_no = 0       ## Restart curent playlist (Loop)
      random.shuffle(self._tracks)  ## (re)Shuffle on Loop
  
    _track = self._tracks[self._next_track_no]
    if _track is None:
      self.reset_booleans() 
      return
     
    if self._playmode == 'Station':
      self._song = _track   ## use with station
      self._source = "2"    ## assume "2" here
      # self.log("Station Song: {}".format(self._song))      
    elif self._playmode == 'Playlist':
      if "track" in self._song:
        self._song = _track['track']  ## use with playlist
        # self.log("Playlist Song: {}".format(self._song))
      else:
        self._song = _track
        # self.log("Playlist Track: {}".format(self._song))
      self._source = self._song['source']
      # self.log("Source = {}".format(self._source))
    else:
      self.log("invalid playmode: {}".format(self._playmode))
    
    self.play_track()


  def play_track(self):
    if 'trackId' in self._song:
      # self.log("Found: trackId")
      _uid = self._song['trackId']
    elif 'storeId' in self._song:
      # self.log("Found: storeId")
      _uid = self._song['storeId']
    elif 'id' in self._song:
      # self.log("Found: id")
      _uid = self._song['id']
    else:
      self.log("KeyError: SONG ID NOT FOUND!")

    if _uid:
      _url = self.gmc.get_stream_url(_uid)
      self.call_service("media_player/play_media", entity_id = self._player_id, media_content_id = _url, media_content_type = self.args["media_type"])
    else:
      self.log("Track ID not found!")
      # self.get_track(entity=None,attribute=None,old=None,new=None,kwargs=None)

    ''' Optional Song Information '''
    try:
      self.artist = (self._song['artist'])
      self.album = (self._song['album'])
      self.title = (self._song['title'])

      _album_art_ref = (self._song['albumArtRef'])  ## Returns a list with single dict
      _album_art = _album_art_ref[0]                ## Returns a usable dict
      self.album_art = (_album_art['url'])          ## Finally what we need
    except:
      pass

    # _artist_art_ref = (self._song['artistArtRef'])  ## returns a list with single dict
    # _artist_art = _artist_art_ref[0]                ## returns a usable dict
    # self.artist_art = (_artist_art['url'])

    # self.log("--------------------------------------------")
    # self.log("--- TRACK INFORMATION  -----------")
    # self.log("Artist: {}".format(self.artist))
    # self.log(" Album: {}".format(self.album))
    # self.log(" Title: {}".format(self.title))
    # self.log(" ")
    # # self.log("Artist Art:{}".format(self.artist_art))
    # self.log("Album Art: {}".format(self.album_art))
    # self.log("--------------------------------------------")
    

  def show_info (self, entity, attribute, old, new, kwargs):
    if self._source == "2":
      self.set_state(self._player_id, attributes={"media_title":self.title, "media_artist":self.artist, "media_album_name":self.album, "entity_picture":self.album_art})
    
  def clear_info (self, entity, attribute, old, new, kwargs):
    if new != 'playing' or new != 'paused':
      self.set_state(self._player_id, attributes={"media_title":'', "media_artist":'', "media_album_name":'', "entity_picture":''})


  def media_player_off(self, entity, attribute, old, new, kwargs):
    self.call_service("media_player/turn_off", entity_id = self._player_id)

  def gmusic_api_logout(self, entity, attribute, old, new, kwargs):
    self.gmc.logout()
    self.reset_booleans()



######################################################
######################################################

# song_id = "http://192.0.1.19:9999/get_song?id=Tjn7abpxorbog6pbihxq7leu2by"
# media_player = "media_player.bedroom_stereo"

# class GoogleMusicProxySimple(hass.Hass):

#   def initialize(self):
#       self.listen_state(self.music_on,"input_boolean.stream_music", new="on")
#       self.listen_state(self.music_off,"input_boolean.stream_music", new="off")

#   def music_on(self, entity, attribute, old, new, kwargs):
#     #  song_id = "http://192.0.1.19:9999/get_song?id=Tjn7abpxorbog6pbihxq7leu2by"
#     #  media_player = "media_player.bedroom_stereo"
#       self.call_service("media_player/play_media", entity_id = media_player, media_content_id = song_id, media_content_type = "music")
         
#   def music_off(self, entity, attribute, old, new, kwargs):
#     #  media_player = "media_player.bedroom_stereo"
#       self.call_service("media_player/turn_off", entity_id = media_player)

######################################################

# class GoogleMusicProxySimple2(hass.Hass):

#   def initialize(self):s
#       self.listen_state(self.music_on,"input_boolean.stream_music", new="on")
#       self.listen_state(self.music_off,"input_boolean.stream_music", new="off")
    
#   def music_on(self, entity, attribute, old, new, kwargs):
#       netpath = 'http://{}:{}/get_song?id={}'.format(self.args["gproxy"], self.args["port"], self.args["song_id"])
#       self.call_service("media_player/play_media", entity_id = self.args["media_player"], media_content_id = netpath, media_content_type = self.args["media_type"])
  
#   def music_off(self, entity, attribute, old, new, kwargs):
#       self.call_service("media_player/turn_off", entity_id = self.args["media_player"])
