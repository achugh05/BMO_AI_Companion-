"""
BMO OS v0.69 - AI Companion
Author: Ansh Chugh
Description: A Raspberry Pi-based desktop assistant inspired by Adventure Time's BMO.
Features: LLM Chat (Ollama), STT (Whisper), TTS (Piper), Computer Vision Study Mode, 
          Spotify Integration, and Retro-Gaming Launchers.
Note: This is a work-in-progress with a ton of known bugs and hardware-specific dependencies.

Huge thanks to Brenpoly for the inspiration.
"""

import os
import ollama
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import re
import requests
import time
import threading
import queue
import subprocess
import webview
import numpy as np
import sounddevice as sd
from ddgs import DDGS
import tkinter as tk
from PIL import Image, ImageTk
import random
import speech_recognition as sr
from faster_whisper import WhisperModel
from picamera2 import Picamera2, Preview
import pandas as pd
from flask import Flask, session, render_template_string, redirect, jsonify
from canvas.canvasrequest import canvasFunction
from study_session_core import run_study_session

# ================================================================================================================================
                                                 # BMOFace Class: Handles Face Animations
# ================================================================================================================================

class BMOFace:
    def __init__(self, root):
        self.root = root
        self.root.title("BMO OS v0.69")
        self.root.update_idletasks()
        self.root.geometry("800x480")
        self.root.attributes('-fullscreen', True)
        self.root.config(cursor="none")
        self.bmo_color = "#C6FFDC"
        self.root.configure(bg=self.bmo_color)
        #self.root.overrideredirect(True)
        
        self.canvas = tk.Canvas(self.root, width=800, height=480, bg=self.bmo_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        #KILL KEY
        self.root.bind("<Escape>", lambda e: os._exit(0))
        
        # FULLSCREEN TOGGLE KEY
        self.root.bind("<BackSpace>", self.toggle_fullscreen)

        # Load Animation Library
        self.animations = {
            "idle": self.load_frames("idle"),
            "talking": self.load_frames("talking"),
            "thinking": self.load_frames("thinking"),
            "sleeping": self.load_frames("sleeping")
        }

        self.current_state = "sleeping"
        self.face_sprite = self.canvas.create_image(400, 240)
        self.current_img_ref = None
        
        self.animate()

    def toggle_fullscreen(self, event=None):
        # Get the current state (returns 1 for True, 0 for False)
        is_fullscreen = self.root.attributes('-fullscreen')
        
        # Toggle to the opposite state
        self.root.attributes('-fullscreen', not is_fullscreen)
        
        # If exiting fullscreen, you might want to ensure the taskbar 
        # and title bar reappear correctly
        if is_fullscreen:
            self.root.overrideredirect(False) 
        return "break" # Prevents the event from propagating
    
    def load_frames(self, folder_name):
        frames = []

        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base_path, "assets", folder_name)

        if os.path.exists(path):
            files = sorted([f for f in os.listdir(path) if f.endswith(('.png', '.jpg'))])
            for f in files:
                img = Image.open(os.path.join(path, f)).resize((800, 480), Image.Resampling.LANCZOS)
                frames.append(ImageTk.PhotoImage(img))
        return frames

    def set_state(self, new_state):
        if new_state in self.animations:
            self.current_state = new_state

    def animate(self):
        current_frames = self.animations.get(self.current_state, [])
        if current_frames:
            next_image = random.choice(current_frames)
            self.canvas.itemconfig(self.face_sprite, image=next_image)
            self.current_img_ref = next_image

        # Timing based on state
        if self.current_state == "sleeping": 
            delay = random.randint(1500, 2500)
        elif self.current_state == "idle":
            delay = random.randint(1000, 2000)
        elif self.current_state == "thinking": 
            delay = random.randint(1000, 2000)
        elif self.current_state == "talking": 
            delay = random.randint(150, 300)
        else: 
            delay = 2000
        
        self.root.after(delay, self.animate)
    
# ================================================================================================================================
                                    # BMOChat Class: Handles Ollama, User Inputs, and TTS Queue
# ================================================================================================================================

class BMOChat:
    def __init__(self, face_canvas, model_name: str = "json_llama_bmo"):
        
        #face initialization
        self.face = face_canvas  
        self.root = face_canvas.root   
        
        #listening/transcribing initialization
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 0.8
        self.stt_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        self.is_processing_audio = False
        
        # llm initialization
        self.model_name = model_name
        self.client = ollama.Client()
        self.conversation_history = []
        current_dir = os.path.dirname(os.path.abspath(__file__))

        self.piper_path = os.path.normpath(os.path.join(current_dir, "..", "piper", "piper"))
        self.voice_model = os.path.normpath(os.path.join(current_dir, "..", "piper", "en_GB-southern_english_female-low.onnx"))

        #tts initialization
        self.tts_queue = queue.Queue()
        self.stop_tts = threading.Event()
        self.text_buffer = ""
        self.mute_tts = False;
        
        self.speaker_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.speaker_thread.start()

        #music 
        self.music_process = None
        self.music_window = None

        self.study_log_path = "/home/jaceg/BMO_OS/BMO_AI_Companion/study_focus_imx500/logs/study_session_summary.csv"
        self.study_proc = None

        #debug variable
        self.master = False
        
# ================================================================================================================================
                                    # BMOChat user input handler, warmup function, and json handler
# ================================================================================================================================
        
    def ask_bmo(self, user_input: str) -> str:
        """handles initial user input"""
     
        user_input_low = user_input.lower()

        # 1. Debug Bypass
        if user_input_low.startswith("master "):
            self.run_debug_command(user_input)
            return

        # 2. KEYWORD FAST PATH (Bypass LLM for reliability)
        if any(word in user_input_low for word in ["play music", "open spotify", "music mode"]):
            self.handle_mode_change("music")
            return
        elif any(word in user_input_low for word in ["gaming mode", "game mode" "play games", "video games", "es-de"]):
            self.handle_mode_change("gaming")
            return
        elif any(word in user_input_low for word in ["study mode", "start studying", "focus mode"]):
            self.handle_mode_change("study")
            return
        elif any(word in user_input_low for word in ["photo", "capture image"]):
            self.handle_tool_request("capture_image", None, user_input)
            return
        elif any(word in user_input_low for word in ["what time", "current time", "the time"]):
            self.handle_tool_request("get_time", None, user_input)
            return
        elif any(word in user_input_low for word in ["canvas", "grades", "assignments", "assignment", "due date", "due dates"]):
            self.handle_tool_request("get_canvas", None, user_input)
            return
        else:
               
            print("\nBMO: ", end="", flush=True)
            # TRIGGER: Start Thinking
            self.face.set_state("thinking")
            chosen_line = self.get_random_voiceline("thinking")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(2)
            self.face.set_state("thinking")
            
            self.conversation_history.append({'role': 'user', 'content': user_input})

            try:
                # Get the first response (could be text or a JSON tool request)
                stream = self.client.chat(
                    model=self.model_name,
                    messages=self.conversation_history,
                    stream=True, 
                )

                full_response = ""
                
                for chunk in stream:
                    content = chunk.message.content
                    full_response += content   
                    print(content, end="", flush=True)
                    self.process_for_tts(content)

                # Flush any remaining text in the buffer
                self.process_for_tts("", final=True)
                self.conversation_history.append({'role': 'assistant', 'content': full_response})
                
                # Check for JSON
                action, value = self.handle_json_from_bmo(full_response)
                
                # If BMO asked for a tool, execute it
                if action:
                    self.handle_tool_request(action, value, user_input)

            except Exception as e:
                print(f"\n[DEBUG] error in ask_bmo: {str(e)}")
    
    def run_debug_command(self, command):
        """Bypasses the LLM and directly triggers tools/modes for testing."""
        print(f"\n[DEV MODE] Executing bypass for: '{command}'")

        # Normalize the command for easier matching
        cmd = re.sub("master", "", command)
        
        try:
            if "music" in cmd:
                self.handle_mode_change("music")
            elif "study" in cmd:
                self.handle_mode_change("study")
            elif "gaming" in cmd:
                self.handle_mode_change("gaming")
                
            elif "photo" in cmd or "camera" in cmd:
                # We can call the tool handler directly!
                self.handle_tool_request("capture_image", None, cmd)
            elif "time" in cmd:
                self.handle_tool_request("get_time", None, cmd)
            elif "canvas" in cmd:
                self.handle_tool_request("get_canvas", None, cmd)
            elif "search" in cmd:
                # Example: 'test search Raspberry Pi 4'
                query = cmd.replace("search", "").strip()
                if query:
                    self.handle_tool_request("search_web", query, cmd)
                else:
                    print("[DEV MODE] Please provide a search term.")
            else:
                print("[DEV MODE] Unknown test command.")
                print("Available: master music, master study, master photo, master time, master canvas [grades or assignments], master search [query]")
                
        except Exception as e:
            print(f"[DEV MODE] Crash during test: {e}")

    def handle_json_from_bmo(self, raw_text: str):
        try:
            # Look for the first balanced { } block
            match = re.search(r'(\{.*?\})', raw_text, re.DOTALL) 
            if not match:
                return None, None
            
            json_str = match.group(1).strip()
            data = json.loads(json_str)
            
            # If the 'value' is itself a stringified JSON (common in your logs), parse it again
            val = data.get("value")
            if isinstance(val, str) and val.startswith("{"):
                try:
                    val = json.loads(val)
                except:
                    pass
            
            return data.get("action"), val
        except Exception as e:
            print(f"[DEBUG] Error parsing json: {e}")
            return None, None
     
    def warmup(self):
        #Loads the model into RAM by sending an empty request. 
        #The keep_alive=-1 ensures it stays in memory indefinitely.

        try:
            # Sending an empty prompt preloads the model
            self.client.generate(
                model=self.model_name, 
                prompt='', 
                keep_alive=-1  # -1 keeps it in RAM forever
            )
            
            #wake up bmo
            self.face.set_state("idle")
        except Exception as e:
            print(f"[DEBUG] error on warmup: {e}")
        
# ================================================================================================================================
                                                # BMOChat Tools, Modes, and Tool Handler
# ================================================================================================================================

    def web_search(self, query: str) -> str:
        #Perform web search using Duck duck go web search tool
                # 'us-en' region is often more stable for CLI queries
        try:
            with DDGS() as ddgs:
                results = []
                # 1. text search
                results = list(ddgs.text(query, region='us-en', max_results=3))
                if results: 
                    r = results[0]
                    #print(f"[DEBUG] Found Text: {r.get('title')}", flush=True)
            
                    # Safe get
                    title = r.get('title', 'No Title')
                    body = r.get('body', r.get('snippet', 'No Body'))
                    return f"[DEBUG] SEARCH RESULTS for '{query}':\nTitle: {title}\nSnippet: {body[:300]}"
                else: 
                    print(f"[DEBUG] Search returned 0 results.", flush=True)
                    return "SEARCH_EMPTY"
        except Exception as e:
            print(f"[DEBUG] Search Error: {e}", flush=True)
            return "SEARCH_ERROR"

    def summarize_web_data(self, user_input, web_result): 
        enhanced_prompt = f"""
                User asked: {user_input} 
                Web result: {web_result}
                
                Use the web result to answer the users request. DO NOT RETURN JSON.
                 """
        
        messages = self.conversation_history + [
            {'role': 'user', 'content': enhanced_prompt}
            ]
           
        # Get response from BMO
        raw_response = self.client.chat(
        model=self.model_name,
        messages=messages,
            )
            
        response = raw_response['message']['content']

        # Update conversation history
        self.conversation_history.append({'role': 'assistant', 'content': response})
        
        return response
    
    def handle_mode_change(self, mode):

        if mode == "study":
            print("[DEBUG] Study Mode Activated. Hibernating BMO...")
            chosen_line = self.get_random_voiceline("study_start")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(2)
            self.face.set_state("idle")
            
            # Unload Ollama to free up 2GB+ of RAM for the CV tasks
            try:
                requests.post("http://localhost:11434/api/generate", 
                              json={"model": self.model_name, "keep_alive": 0}, timeout=2)
                print("[DEBUG] Ollama model evicted.")
            except Exception as e:
                print(f"[DEBUG] Ollama unload failed: {e}")

            # 2. Hide BMO Face and Lock Ears
            self.is_processing_audio = True 
            self.root.withdraw()

            # Launch the Study Session (Blocking Call)
            try:
                print("[DEBUG] Starting IMX500 Study AI...")
                summary = run_study_session(
                    model_path="/home/jaceg/BMO_OS/BMO_AI_Companion-/study_focus_imx500/models/focus_v4/network.rpk",
                    labels_path="/home/jaceg/BMO_OS/BMO_AI_Companion-/study_focus_imx500/labels.txt",
                    session_minutes=5,
                    threshold=0.1,
                    bbox_normalization=True,
                    bbox_order="xy",
                    preserve_aspect_ratio=True,
                    summary_csv="/home/jaceg/BMO_OS/BMO_AI_Companion-/study_focus_imx500/logs/study_session_summary.csv"
                )
                
                # 4. Process Results after session ends
                if summary:
                    self.root.deiconify()    
                    chosen_line = self.get_random_voiceline("study_end")
                    self.play_bmo_sound(chosen_line)
                    self.face.set_state("talking")
                    time.sleep(2)
                    self.face.set_state("idle")
                    self.announce_study_results(summary)

            except Exception as e:
                print(f"[DEBUG] Study Session Error: {e}")

            # 5. Wake BMO back up
            self.face.set_state("idle")
            self.is_processing_audio = False
            return 
        
        elif mode == "gaming":
            print("[DEBUG] Gaming Mode Activated. Initiating Deep Hibernate...")
                
            chosen_line = self.get_random_voiceline("game_start")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(1)
            self.face.set_state("idle")
            
            # 1. Unload Ollama
            try:
                # Make sure self.model_name is set in __init__ (e.g., self.model_name = "llama3")
                requests.post("http://localhost:11434/api/generate", 
                              json={"model": self.model_name, "keep_alive": 0}, timeout=2)
                print("[DEBUG] Ollama model evicted from RAM.")
            except Exception as e:
                print(f"[DEBUG] Could not reach Ollama: {e}")
                
            self.is_processing_audio = True 
            self.root.withdraw()
            
            try:
                appimage_path = "/home/jaceg/Downloads/ES-DE_aarch64.AppImage"
                
                # Setup Environment for Pi 4 GPU
                env_vars = os.environ.copy()
                env_vars["MESA_GL_VERSION_OVERRIDE"] = "3.3" 
                env_vars["MESA_GLSL_VERSION_OVERRIDE"] = "330"
                env_vars["SDL_VIDEO_GL_DRIVER"] = "libGL.so.1" 

                print(f"[DEBUG] Launching ES-DE AppImage...")
                # Use shell=False for AppImages generally works better
                subprocess.run([appimage_path], env=env_vars, check=True) 

            except Exception as e:
                print(f"\n[DEBUG] Failed to launch ES-DE: {e}")
                
            # Recovery
            print("[DEBUG] ES-DE closed. Waking BMO up...")

            self.root.deiconify()
            chosen_line = self.get_random_voiceline("game_end")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(1)

            self.face.set_state("idle")
            self.is_processing_audio = False
            
            return 
            
        elif mode == "music": 
            print("[DEBUG] Music Mode Activated. Pausing BMO...")
            chosen_line = self.get_random_voiceline("music_start")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(2)
            self.face.set_state("idle")

            # 1. State Setup
            self.is_processing_audio = True 
            self.root.withdraw() # Hide BMO's face
            
            # 2. The "Thread Jump"
            # We tell the Main Thread to run the UI. 
            # This is the only way to avoid the "pywebview must be run on a main thread" error.
            self.root.after(0, self.launch_music_ui)
            
            return 
        
    def announce_study_results(self, summary):
        """Uses the summary returned by the study core to provide feedback."""
        self.is_processing_audio = False

        score = summary.get("focused_pct", 0)
        
        if score > 80:
            msg = f"Awesome! You were focused {score}% of the time. Great job!"
        elif score > 50:
            msg = f"You were focused for {score}% of the session. Room for improvement!"
        else:
            msg = f"Only {score}% focus? You spent too much time on your phone!"
            
        self.process_for_tts(msg, final=True)
   
    def launch_music_ui(self):
        
        try: 
            # 1. Launch the background Flask server
            self.music_process = subprocess.Popen(["python3", "/home/jaceg/BMO_OS/BMO_AI_Companion-/spotifyplaying/ui_music.py"])
            
            # 2. Create and Start the Window (This blocks until the window is closed)
            webview.create_window(
                'BMO Spotify', 
                'http://127.0.0.1:5005', 
                width=800, height=480, 
                frameless=True, on_top=True
            )
            webview.start()
            
            # --- Code execution PAUSES here until you close the Spotify window ---
            
        except Exception as e:
            print(f"[DEBUG] Music UI Error: {e}")
        
        # 3. Cleanup & Recovery
        print("[DEBUG] Spotify Window closed. Resuming BMO...")
        if hasattr(self, 'music_process') and self.music_process:
            self.music_process.terminate()
       
        self.face.set_state("idle")
        self.is_processing_audio = False

    def get_time(self):
        # Returns a string like 'Mon Mar 9 13:45:00 2026'
        # get pacific timezone data
        pacific_tz = ZoneInfo("America/Los_Angeles")
        # Get the current time in pacific timezone
        current_pacific_time = datetime.now(tz=pacific_tz)
        # return as a string
        return current_pacific_time.strftime("%I:%M %p on %A, %B %d")

    def handle_tool_request(self, action, value, user_input):
        #Routes the action to the correct tool and handles the follow-up.
        chosen_line = self.get_random_voiceline("thinking")
        self.root.deiconify() # Bring the face back
        self.play_bmo_sound(chosen_line)
        self.face.set_state("talking")
        time.sleep(2)
        self.face.set_state("thinking")

        if action == "get_time":
            response = f"It is currently {self.get_time()}!"
            print(f"\n {response}")
            self.process_for_tts(response, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': response})
        if action == "get_canvas":
            response = canvasFunction(user_input)
            print(f"\n {response}")
            self.process_for_tts(response, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': response})    

        elif action == "search_web":
            # search_web returns raw data, summarize_web_data prompts the llm again
            self.face.set_state("thinking")
            search_data = self.web_search(value)
            response = self.summarize_web_data(user_input, search_data)
            print(f"\n {response}")
            self.conversation_history.append({'role': 'assistant', 'content': value})
            self.process_for_tts(response, final=True)

        elif action == "capture_image":
            self.capture_image()
            
        elif action == "mode_change":
            response = self.handle_mode_change(value)
            self.process_for_tts(response, final=True)

        elif action == "output_text":
            print(f"\n {value}")
            self.process_for_tts(value, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': value})
        elif action == "greeting": 
            print(f"\n {value}")
            self.process_for_tts(value, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': value})
        elif action == "summary": 
            print(f"\n {value}")
            self.process_for_tts(value, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': value})
        elif action: 
            print(f"\n {value}")
            self.process_for_tts(value, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': value})

    def capture_image(self):
        """Shows a preview, counts down, and saves a photo."""
        picam2 = None
        try:
            # 1. Initialize Camera
            picam2 = Picamera2()
            config = picam2.create_preview_configuration()
            picam2.configure(config)
            
            # 2. Start Preview (This opens a window on your Pi screen)
            # Using QTGL for a modern, hardware-accelerated preview
            picam2.start_preview(Preview.QTGL)
            picam2.start()
            
            print("\n[BMO CAMERA] Starting countdown...")
            
            chosen_line = self.get_random_voiceline("photo_start")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(2)
            self.face.set_state("idle")
                
            # 4. Save the file with a timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"bmo_capture_{timestamp}.jpg"
            
            picam2.capture_file(filename)
            print(f"[BMO CAMERA] Photo saved as {filename}")
            
            # 5. Success feedback
            chosen_line = self.get_random_voiceline("photo_end")
            self.play_bmo_sound(chosen_line)
            self.face.set_state("talking")
            time.sleep(1)
            self.face.set_state("idle")
            self.is_processing_audio = False

            
        except Exception as e:
            print(f"[DEBUG] Camera Error: {e}")
            self.process_for_tts("I am sorry, my camera is malfunctioning.", final=True)
            
        finally:
            # close the camera to free up the hardware
            if picam2:
                picam2.stop_preview()
                picam2.stop()
                picam2.close()       
# ================================================================================================================================
                                                # BMOChat Piper TTS Functions
# ================================================================================================================================

    def process_for_tts(self, chunk, final=False):
        #takes raw text, prepares it and adds it to tts queue---is used to send any and all text to tts queue
        if chunk is None:
            return
        # Check for the start of JSON
        if "{" in chunk:
            self.mute_tts = True
            self.text_buffer = "" # Clear buffer of any partial JSON junk
            return

        # If in "Mute Mode", check for the end of JSON
        if self.mute_tts:
            if "}" in chunk:
                self.mute_tts = False

            else:
                return # Still muted, skip this chunk

        # Normal buffering logic
        self.text_buffer += chunk
        
        # Split into sentences using a regex that keeps punctuation
        # This looks for . ! ? or newline followed by space
        sentences = re.split(r'(?<=[.!?\n])\s+', self.text_buffer)

        if not final:
            if len(sentences) > 1:
                for s in sentences[:-1]:
                    self._enqueue(s)
                self.text_buffer = sentences[-1]
        else:
            for s in sentences:
                self._enqueue(s)
            self.text_buffer = ""
            self.mute_tts = False # Reset for the next turn

    def _enqueue(self, text):
    # Internal helper to clean and push to the thread.
        clean_text = text.replace('*', '').strip()
        if clean_text:
            self.tts_queue.put(clean_text)
    def _tts_worker(self):
    
    
    # Use the verified stable rate for the Pi 4 Jack
        TARGET_RATE = 19000

        while not self.stop_tts.is_set():
            try:
                # We open the stream once and keep it open as long as possible
                with sd.RawOutputStream(
                    samplerate=TARGET_RATE, 
                    blocksize=2048, 
                    channels=1, 
                    dtype='int16', 
                    device=0
                ) as stream:
                
                    print("[DEBUG] BMO's Voice Box is ready.")
                
                    while not self.stop_tts.is_set():
                        try:
                            # Wait for text (timeout=None means it sleeps until text arrives)
                            text = self.tts_queue.get(timeout=None)
                            if text is None: break
                            
                            # Set busy lock and face
                            self.is_processing_audio = True
                            self.face.set_state("talking")

                            # Open Piper with the matching hardware rate
                            process = subprocess.Popen(
                                [
                                    self.piper_path, 
                                    "--model", self.voice_model, 
                                    "--output-raw", 
                                    "--rate", str(TARGET_RATE), # Match the stream!
                                    "--length_scale", "1.0",
                                    "--noise_scale", "0.667",
                                    "--noise_w", "0.333"
                                ],            
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL
                            )

                            # Feed the text to Piper
                            process.stdin.write(text.encode('utf-8') + b'\n')
                            process.stdin.close()

                            # Stream the audio to the hardware
                            while True:
                                audio_data = process.stdout.read(1024)
                                if not audio_data: 
                                    break
                                
                                try:
                                    stream.write(audio_data)
                                except sd.PortAudioError:
                                    print("[DEBUG] Audio hardware glitch mid-speech. Recovering...")
                                    break # Exit inner loop to re-open the stream
                            
                            process.wait()
                            self.tts_queue.task_done()

                            # ONLY unlock BMO and change face if the queue is actually empty
                            if self.tts_queue.empty():
                                self.face.set_state("idle")
                                self.is_processing_audio = False

                        except queue.Empty:
                            # No text to speak? Just loop and wait.
                            continue

            except Exception as e:
                # This catches hardware "Busy" or "Not Found" errors
                print(f"[DEBUG] TTS Hardware Error: {e}. Retrying in 2s...")
                self.is_processing_audio = False # Ensure we don't stay locked if hardware dies
                time.sleep(2)

    
# ================================================================================================================================
                                                # BMOChat Listen and Trasnscribe Functions
# ================================================================================================================================
    def start_listening(self, event=None):
        # change the face
        if self.is_processing_audio:
            print("[DEBUG] BMO is processing audio already.")
            return
            
        self.is_processing_audio = True
        
        self.face.set_state("thinking")
        print("[DEBUG] BMO is listening...")
        
        # Start the Listening Thread
        threading.Thread(target=self.listen_and_transcribe, daemon=True).start()     
    
    def listen_and_transcribe(self):
        try:
            with sr.Microphone(device_index=1, sample_rate=44100) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source)
                
                print("[DEBUG] Audio Recieved...Processing Now")
                #Conversion
                raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
                audio_float32 = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

                segments, info = self.stt_model.transcribe(audio_float32, beam_size=1)
                user_text = "".join([segment.text for segment in segments]).strip()

                if user_text:
                    print(f"[DEBUG] Text: {user_text}")
                    self.ask_bmo(user_text)
                else:
                    print("[DEBUG] No Voice Heard, Try Again")
                    self.face.set_state("idle")
                    self.is_processing_audio = False
                    
        except Exception as e:
            print(f"[DEBUG] Voice Error: {e}")
            self.face.set_state("idle")
            self.is_processing_audio = False
# ================================================================================================================================
                                                # BMOChat Voicelines
# ================================================================================================================================

    def play_bmo_sound(self, sound_input):
            """
            Plays a single .wav or a list of .wavs in sequence.
            sound_input: "filename" OR ["file_part1", "file_part2"]
            """
            def worker():
                # Convert single string to a list for unified processing
                sounds = [sound_input] if isinstance(sound_input, str) else sound_input
                
                for sound in sounds:
                    path = f"/home/jaceg/BMO_OS/BMO_AI_Companion-/assets/sounds/{sound}.wav"
                    if os.path.exists(path):
                        # -q is quiet, -D matches your verified device 1 from _tts_worker
                        subprocess.run(["aplay", "-q", "-D", "plughw:0,0", path])
                        if len(sounds) > 1: 
                            time.sleep(1)
                    else:
                        print(f"[DEBUG] Sound file missing: {path}")

            # Run in a thread so BMO doesn't 'freeze' while the audio plays
            threading.Thread(target=worker, daemon=True).start()

    def get_random_voiceline(self, category):
        # Define your library here
        library = {
            "thinking": [
                "think_1", 
                "think_2", 
                "think_3", 
                "think_4", 
                ["think_shush_1", "think_shush_2"],
                ["think_load_1", "think_load_2", "think_load_3"]
                ],
            "photo_start": [ 
                "photo_countdown_smile"
                # ["photo_countdown_start", "photo_countdown_3", "photo_countdown_2", "photo_countdown_1", "photo_countdown_smile"]
                ],
            "photo_end": [
                "photo_success" ,
                ["photo_success", "photo_flirt_1"],
                ["photo_success", "photo_insult_1"],
                ["photo_success", "photo_flirt_2"], 
                ["photo_success", "photo_insult_2"]
                ],
            "game_start": [
                "game_start",
                ["game_start", "game_start_line_1"],
                ["game_start", "game_start_line_2"]
                ],
            "game_end": [
                "game_end_line"
            ],
            "study_start": [
                "study_start",
                ["study_start", "study_start_line"]
                ],
            "study_end": [
                "study_end"
            ], 
            "music_start": [
                "music_start",
                ["music_start", "music_start_line"]
                ],
            "music_end": [
                "music_end"
            ]
        }
        
        options = library.get(category, [])
        return random.choice(options) if options else None

# ================================================================================================================================
                                                # MAIN: INITIATES BMO CHAT AND FACE on startup
# ================================================================================================================================

def main():
    root = tk.Tk()
    
    face = BMOFace(root)
    
    bmo = BMOChat(face) 
    
    bmo.warmup()
    
    root.bind("<Return>", bmo.start_listening)
    
    print("\nBMO OS v0.69")
    print("Type 'quit', 'exit', 'bye', or power off to power down BMO")
    print("Press backspace to toggle fullscreen")
    print("Press escape to end the program")
    print("Press enter to talk to BMO")
    t = threading.Thread(target=terminal_input_thread, args=(bmo,), daemon=True)
    t.start()

    # Start thread for terminal input
    root.mainloop()

def terminal_input_thread(bmo_chat):
    while True:
        try:
            user_input = input("\n ").strip()
            
            # Check the State Lock
            if bmo_chat.is_processing_audio:
                print("BMO is busy! Please wait for her to finish.")
                continue

            if user_input.lower() in ['quit', 'exit', 'bye']:
                os._exit(0)
                
            if user_input:
                # Lock the system manually for terminal input
                if "master" not in user_input:
                    bmo_chat.is_processing_audio = True
                
                # Use a thread for the LLM call so the terminal doesn't hang
                threading.Thread(target=bmo_chat.ask_bmo, args=(user_input,), daemon=True).start()
                
        except EOFError:
            break
        
if __name__ == "__main__":  
    main()
   
#game
#study

#take photo
#canvas api
#spotify api

#how to go back to bmo if gaming
#ALARM CLOCK STATE

#add thinking voice lines