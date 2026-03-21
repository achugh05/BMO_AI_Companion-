import os
import ollama
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import re
import threading
import queue
import subprocess
import numpy as np
import sounddevice as sd
from ddgs import DDGS
import tkinter as tk
from PIL import Image, ImageTk
import random
import speech_recognition as sr
import whisper


# ================================================================================================================================
                                                 # BMOFace Class: Handles Face Animations
# ================================================================================================================================

class BMOFace:
    def __init__(self, root):
        self.root = root
        self.root.title("BMO OS v1.0")
        self.root.geometry("800x480")
        self.bmo_color = "#73AF9C"
        self.root.configure(bg=self.bmo_color)
        
        self.canvas = tk.Canvas(self.root, width=800, height=480, bg=self.bmo_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        #KILL KEY
        self.root.bind("<Escape>", lambda e: os._exit(0))

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

    def load_frames(self, folder_name):
        frames = []
        path = os.path.join("assets", folder_name)
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
            delay = random.randint(150, 500)
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
        
        #listening/transcribing initialization
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 1.0
        self.stt_model = whisper.load_model("base")
        self.is_processing_audio = False
        
        # llm initialization
        self.model_name = model_name
        self.client = ollama.Client()
        self.conversation_history = []
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # Go up one level to project root, then into the piper folder
        self.piper_path = os.path.normpath(os.path.join(current_dir, "..", "piper", "piper", "piper.exe"))
        self.voice_model = os.path.normpath(os.path.join(current_dir, "..", "piper", "en_US-libritts_r-medium.onnx"))

        #tts initialization
        self.tts_queue = queue.Queue()
        self.stop_tts = threading.Event()
        self.text_buffer = ""
        self.mute_tts = False;
        
        self.speaker_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.speaker_thread.start()
        
# ================================================================================================================================
                                    # BMOChat user input handler, warmup function, and json handler
# ================================================================================================================================
        
    def ask_bmo(self, user_input: str) -> str:
        """handles initial user input"""
        
        # TRIGGER: Start Thinking
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
    
    def handle_json_from_bmo(self, raw_text: str):
    # Parses BMO's output and extracts the core tool data.
    
        try:
            # Find the actual JSON block (ignores extra brackets or preamble text)
            match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
            if not match:
                return None, None
            
            json_str = match.group(1).strip()
            
            # Fix common "extra bracket" or "trailing comma" issues
            # Remove trailing commas before a closing bracket
            json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
            
            # Attempt to parse
            data = json.loads(json_str)
            return data.get("action"), data.get("value")
        
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
    
    def handle_mode_change(self, mode): #__________________add voice lines 
        if mode == "study":
            print("placeholder for running study mode")
        
        elif mode == "gaming":
            print("placeholder for gaming mode")
            
        elif mode == "idle": 
            print("placeholder for idle mode")
            
        return f"Initiating {mode} mode"

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
        
        if action == "get_time":
            response = f"It is currently {self.get_time()}!"
            print(f"\n {response}")
            self.process_for_tts(response, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': response})

        elif action == "search_web":
            # search_web returns raw data, summarize_web_data prompts the llm again
            search_data = self.web_search(value)
            response = self.summarize_web_data(user_input, search_data)
            print(f"\n {response}")
            self.conversation_history.append({'role': 'assistant', 'content': value})
            self.process_for_tts(response, final=True)

        elif action == "capture_image":
            response = "Taking Photo!" #_________________________________________voice line here
            print(f"\n {response}")
            self.process_for_tts(response, final=True)
            # Add camera logic here _______________________________________________________________________________________________
            
        elif action == "mode_change":
            response = self.handle_mode_change(value)
            self.process_for_tts(response, final=True)

        elif action == "output_text":
            print(f"\n {value}")
            self.process_for_tts(value, final=False)
            self.conversation_history.append({'role': 'assistant', 'content': value})
        elif action == "greeting": 
            print(f"\n {value}")
            self.process_for_tts(value, final=False)
            self.conversation_history.append({'role': 'assistant', 'content': value})
        elif action == "summary": 
            print(f"\n {value}")
            self.process_for_tts(value, final=False)
            self.conversation_history.append({'role': 'assistant', 'content': value})
        elif action: 
            print(f"\n {value}")
            self.process_for_tts(value, final=False)
            self.conversation_history.append({'role': 'assistant', 'content': value})
            
# ================================================================================================================================
                                                # BMOChat Piper TTS Functions
# ================================================================================================================================

    def process_for_tts(self, chunk, final=False):
        #takes raw text, prepares it and adds it to tts queue---is used to send any and all text to tts queue
        
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
        #Background thread that consumes the queue and speaks.
        
        # Setup the audio stream
        with sd.RawOutputStream(samplerate=24500, blocksize=2048, channels=1, dtype='int16') as stream:
            while not self.stop_tts.is_set():
                try:
                    # Wait for a sentence from the queue
                    text = self.tts_queue.get(timeout=1)
                    if text is None: break
                    
                    # TRIGGER: Start Talking
                    self.face.set_state("talking")
                    
                    # Open Piper as a subprocess
                    # Inside _tts_worker:
                    process = subprocess.Popen(
                    [self.piper_path, "--model", self.voice_model, "--output-raw", 
                    "--length_scale", "0.9",  # Makes BMO talk slightly faster/slower
                    "--noise_scale", "0.6", # randomness of the voice
                    "--noise_w", "0.9"    # Adjusts the rhythm/cadence   
                    ],            
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL
                    )
                    
                    # Send text to Piper
                    process.stdin.write(text.encode('utf-8') + b'\n')
                    process.stdin.close()
                    
                    # Read raw audio data and write to sounddevice
                    while True:
                        audio_data = process.stdout.read(1024)
                        if not audio_data: break
                        stream.write(audio_data)
                    
                    process.wait()
                    self.tts_queue.task_done()
                    
                    # TRIGGER: Back to Idle if nothing else is waiting
                    if self.tts_queue.empty():
                        self.face.set_state("idle")
                        self.is_processing_audio = False
                        
                except queue.Empty:
                    continue
# ================================================================================================================================
                                                # BMOChat Listen and Trasnscribe Functions
# ================================================================================================================================
    def start_listening(self, event=None):
        # change the face
        if self.is_processing_audio:
            return # Don't start a new listening thread
            
        self.is_processing_audio = True
        
        self.face.set_state("thinking")
        
        # Start the Listening Thread
        threading.Thread(target=self.listen_and_transcribe, daemon=True).start()     
    
    def listen_and_transcribe(self):
        try:
            with sr.Microphone(sample_rate=16000) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=10)
                
                #Conversion
                raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
                audio_float32 = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0

                result = self.stt_model.transcribe(audio_float32, fp16=False)
                user_text = result['text'].strip()

                if user_text:
                    print(f"[DEBUG] Text: {user_text}")
                    self.ask_bmo(user_text)
                else:
                    self.face.set_state("idle")
                    self.is_processing_audio = False
                    
        except Exception as e:
            print(f"[DEBUG] Voice Error: {e}")
            self.face.set_state("idle")
            self.is_processing_audio = False

# ================================================================================================================================
                                                # MAIN: INITIATES BMO CHAT AND FACE on startup
# ================================================================================================================================

def main():
    root = tk.Tk()
    
    face = BMOFace(root)
    
    bmo = BMOChat(face) 
    
    bmo.warmup()
    
    root.bind("<space>", bmo.start_listening)
    
    print("\nBMO OS v0.69")
    print("Type 'quit', 'exit', 'bye', or power off to power down BMO")
    print("Press space to talk to BMO")
    
    # Start thread for terminal input
    root.mainloop()

def terminal_input_thread(bmo_chat):
    # input() on a thread so GUI doesn't freeze
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ['quit', 'exit', 'bye']:
                os._exit(0) # Kill everything
            if user_input:
                print("\nBMO: ", end="", flush=True)
                bmo_chat.ask_bmo(user_input)
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
#take photo with laptop camera
#ALARM CLOCK STATE

#add thinking voice lines