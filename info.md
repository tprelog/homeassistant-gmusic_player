## Google Music in HA -- as a media player

### Based on the original gmusic in HA code by @Danielhiversen  
Stream from your Google Music library with Home Assistant  

### Configuration after Install
- Everything for the configuration is provided using packages.
- You should only need to edit a few things to get this up and running.
- If you have never used a packages file [SEE HERE.](https://www.home-assistant.io/docs/configuration/packages/#create-a-packages-folder)  

---
**Add both of the following files to your Home Assistant `packages` directory**  
 - [`packages/gmusic_config.yaml`](https://github.com/tprelog/homeassistant-gmusic_player/blob/master/packages/gmusic_config.yaml)
 - [`packages/gmusic_player.yaml`](https://github.com/tprelog/homeassistant-gmusic_player/blob/master/packages/gmusic_player.yaml)

---
### Configuration Options -- ` packages/gmusic_config.yaml `

Key | Type | Required | Description
--- | --- | --- | ---
`username` | `string` | `YES` | Set your google music username.
`password` | `string` | `YES` | Set your google music password.
`device_id`| `string` | `YES` | Set your valid device_id here.
`token_path` | `string` | `NO` | Directory with RW access for `gmusic_authtoken`
`gmusicproxy` | `string` | `NO` | Url for your local gmusic proxy server
`shuffle` | `boolean` | `NO` | Default: `True`
`shuffle_mode` | `integer` | `NO` | Default: `1`


### You also need to configure your media_players here
 - At the bottom, edit the example media_players so they match your own

```yaml
    speakers: # Example media_players
    - bedroom_stereo
    - workshop_stereo
```
