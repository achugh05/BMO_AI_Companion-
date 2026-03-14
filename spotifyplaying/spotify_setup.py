import spotipy
from spotipy.oauth2 import SpotifyOAuth

#Variables
client_id = ''
client_secret = ''
redirect_uri = 'http://127.0.0.1:8888/callback'

#Authenticate
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri=redirect_uri,
    scope='user-modify-playback-state user-read-playback-state'
))

devices = sp.devices()
pi_device_id = None
pi_name = 'raspotify'  # Change this if your device name is different

#Search for the Raspberry Pi device on spotify
for device in devices['devices']:
  
  if pi_name in device['name'].lower(): 
    pi_device_id = device['id']
    print(f"Found Raspberry Pi, Device ID: {pi_device_id}")
    break
else:
    print("Could not find Raspotify.")