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


class BMOChat:
    def __init__(self, model_name: str = "json_llama_bmo"):
        
        self.model_name = model_name
        self.client = ollama.Client()
        self.conversation_history = []
        

        # Get the absolute path of the current script (llm/bmo_companion.py)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Go up one level to project root, then into the piper folder
        self.piper_path = os.path.normpath(os.path.join(current_dir, "..", "piper", "piper", "piper.exe"))
        self.voice_model = os.path.normpath(os.path.join(current_dir, "..", "piper", "en_US-libritts_r-medium.onnx"))

        self.tts_queue = queue.Queue()
        self.stop_tts = threading.Event()
        self.speaker_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.speaker_thread.start()
        self.text_buffer = ""
        self.mute_tts = False;
    
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

    def get_time(self):
        # Returns a string like 'Mon Mar 9 13:45:00 2026'
        # get pacific timezone data
        pacific_tz = ZoneInfo("America/Los_Angeles")
        # Get the current time in pacific timezone
        current_pacific_time = datetime.now(tz=pacific_tz)
        # return as a string
        return current_pacific_time.strftime("%I:%M %p on %A, %B %d")
        
    def ask_bmo(self, user_input: str) -> str:
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

    def handle_tool_request(self, action, value, user_input):
        
        #Routes the action to the correct tool and handles the follow-up.
        if action == "get_time":
            response = f"It is currently {self.get_time()}!"
            print(f"\n {response}")
            self.process_for_tts(response, final=True)
            self.conversation_history.append({'role': 'assistant', 'content': response})

        elif action == "search_web":
            # search_web now returns raw data, summarize_web_data handles the TTS
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

    def process_for_tts(self, chunk, final=False):
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
        #Background worker that consumes the queue and speaks.
        # Setup the audio stream (Piper low models are usually 22050Hz)
        with sd.RawOutputStream(samplerate=24500, blocksize=2048, channels=1, dtype='int16') as stream:
            while not self.stop_tts.is_set():
                try:
                    # Wait for a sentence from the queue
                    text = self.tts_queue.get(timeout=1)
                    if text is None: break
                    
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
                except queue.Empty:
                    continue

    def handle_json_from_bmo(self, raw_text: str):
    # Parses BMO's output and extracts the core tool data.
        # print("[DEBUG] in json handler:", raw_text)
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
    
    def handle_mode_change(self, mode): #__________________add voice lines 
        if mode == "study":
            print("placeholder for running study mode")
        
        elif mode == "gaming":
            print("placeholder for gaming mode")
            
        elif mode == "idle": 
            print("placeholder for idle mode")
            
        return f"Initiating {mode} mode"

    def summarize_web_data(self, user_input, web_result): 
        enhanced_prompt = f"""
                User asked: {user_input} 
                Web result: {web_result}
                
                Summarize the results for the users request.
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
        except Exception as e:
            print(f"[DEBUG] error on warmup: {e}")
        
def main():
    
    print("\nBMO OS v0.69")
    print("BMO: (Type 'quit', 'exit', 'bye', or power off to power down BMO)")
   
    bmo = BMOChat()
    #to reduce lag send an empty prompt to ai
    bmo.warmup()
    
    while True:
        try:
            # Get user input
            user_input = input("\nYou: ").strip()
            
            # Check for exit conditions
            if user_input.lower() in ['quit', 'exit', 'bye', 'power off']:
                print("\nPowering Off")
                bmo.stop_tts.set() # Tells the worker to stop looping
                bmo.tts_queue.put(None) # Unblocks the .get() if it's waiting
                break
            
            if not user_input:
                continue
            
            # Get BMO's response
            print("\nBMO: ", end="", flush=True)
            bmo.ask_bmo(user_input)
            
        except Exception as e:
            print(f"\n[DEBUG] something went wrong in main(): {str(e)}")
            break

if __name__ == "__main__":
    main()
 
  
#teach bmo how to change boolean states and how to exit them
#idle
#game
#study
#chat

#take photo
#canvas api
#spotify api

#ADD VOICE ASAP
#how to go back to bmo if gaming
#change faces
#take photo with laptop camera