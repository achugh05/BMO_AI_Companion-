from spotify_setup import sp, pi_device_id
import time
def spotify_play_request(user_req,request_type):
    if not pi_device_id:
        print("Device ID not found, cannot play.")
        return "Spotify device unavailable"

    #Song
    if request_type == 'song':
        
        print(f"Searching for: {user_req}")

        #Search and grab first track
        try:
            result = sp.search(q=user_req, limit=1, type='track')
            tracks = result.get('tracks', {}).get('items', [])
        except Exception as e:
            print(f"Spotify Search Error: {e}")
            return "Error searching Spotify"
        
        if not tracks:
            print("No track found.")
            return "No track found"

        track = tracks[0]
        track_uri = track['uri']
        track_name = track['name']
        artist_name = track['artists'][0]['name']

        print(f"Found: {track_name} by {artist_name}")

        #Play the track
        try:
            sp.start_playback(device_id=pi_device_id,uris=[track_uri])
        except Exception as e:
            print(f"Playback Error: {e}")
            return "Error starting playback"

        return f"{track_name} by {artist_name}"

    #Playlist
    elif request_type == 'playlist':

      print(f"Searching for playlist: '{user_req}'...")
    
      #Grabbing the first playlist in the search results
      try:
        result = sp.search(q=user_req, limit=1, type='playlist')
        playlists = result.get('playlists', {}).get('items', [])
      except Exception as e:
        print(f"Spotify Search Error: {e}")
        return "Error searching Spotify"

      # Filter out any None values that the Spotify API might return
      valid_playlists = [p for p in playlists if p is not None]
      if not valid_playlists:
          print("No playlist found.")
          return "No playlist found"

      playlist = valid_playlists[0]
      playlist_uri = playlist['uri']

      print(f"Found Playlist: '{playlist['name']}' by {playlist['owner']['display_name']}")

      #Play playlist
      try:
        sp.start_playback(device_id=pi_device_id, context_uri=playlist_uri)
      except Exception as e:
        print(f"Playback Error: {e}")
        return "Error starting playback"

      return f"{playlist['name']} from {playlist['owner']['display_name']}"
    
    #If neither track nor playlist
    print('Invalid request, must be either song or playlist')
    return "Invalid request"
    
#Pause playback
def pause_song():
    sp.pause_playback(device_id=pi_device_id)

#Continue playback
def continue_song():
    sp.start_playback(device_id=pi_device_id)
    
#Skip song/track
def next_song():
    sp.next_track(device_id=pi_device_id)

#Play previous track
def previous_song():
    sp.previous_track(device_id=pi_device_id)

#Current song
def current_song():
    time.sleep(1)
    try:
        current = sp.current_playback()
    except Exception as e:
        print(f"Error fetching current song: {e}")
        return None

    #Check if current playback is empty
    if current and 'item' in current:
        current_track = current['item']
        current_track_name = current_track['name']
        current_artist_name = current_track['artists'][0]['name']
        return f"{current_track_name} by {current_artist_name}"
    else:
        print("No song currently playing.")
        return None