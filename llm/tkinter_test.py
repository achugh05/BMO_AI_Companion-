import tkinter as tk
from PIL import Image, ImageTk
import os
import random

class BMOFace:
    def __init__(self, root):
        self.root = root
        self.root.title("BMO OS v1.0")
        self.root.geometry("800x480")
        
        # BMO Colors & Setup
        self.bmo_color = "#73AF9C"
        self.root.configure(bg=self.bmo_color)
        
        self.canvas = tk.Canvas(self.root, width=800, height=480, bg=self.bmo_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 1. Initialize Animation Library
        # This loads all folders inside /assets/
        self.animations = {
            "idle": self.load_frames("idle"),
            "talking": self.load_frames("talking"),
            "thinking": self.load_frames("thinking")
        }

        # 2. Set Starting State
        self.current_state = "idle"
        
        # 3. Create the Face Sprite in the center
        # We start with the first frame of 'idle'
        if self.animations["idle"]:
            self.face_sprite = self.canvas.create_image(400, 240, image=self.animations["idle"][0])
        else:
            # Fallback if idle is empty
            self.face_sprite = self.canvas.create_image(800, 480)
            print("Warning: 'assets/idle' is empty!")

        # 4. Bind keys for manual testing
        self.root.bind("1", lambda e: self.set_state("idle"))
        self.root.bind("2", lambda e: self.set_state("talking"))
        self.root.bind("3", lambda e: self.set_state("thinking"))
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        print("Controls: Press 1 (Idle), 2 (Talking), 3 (Thinking)")
        
        # 5. Kick off the animation loop
        self.animate()

    def load_frames(self, folder_name):
        """Helper to find, resize, and convert images to Tkinter format."""
        frames = []
        path = os.path.join("assets", folder_name)
        
        if os.path.exists(path):
            files = sorted([f for f in os.listdir(path) if f.endswith(('.png', '.jpg', '.jpeg'))])
            for f in files:
                try:
                    img = Image.open(os.path.join(path, f))
      
                    frames.append(ImageTk.PhotoImage(img))
                except Exception as e:
                    print(f"Error loading {f}: {e}")
        return frames

    def set_state(self, new_state):
        """Change BMO's current emotion."""
        if new_state in self.animations and self.animations[new_state]:
            print(f"BMO State -> {new_state}")
            self.current_state = new_state
        else:
            print(f"Error: Folder for '{new_state}' is missing or empty.")

    def animate(self):
        """The core loop that picks a random frame and schedules the next one."""
        # Get the list of frames for whatever state BMO is in right now
        current_frames = self.animations.get(self.current_state, [])

        if current_frames:
            # Pick a random frame from the active list
            next_image = random.choice(current_frames)
            
            # Update the canvas sprite
            self.canvas.itemconfig(self.face_sprite, image=next_image)
            
            # Keep reference to prevent garbage collection
            self.current_img_ref = next_image

        # Adjust the speed of the 'heartbeat' based on the state
        if self.current_state == "talking":
            delay = random.randint(100, 250)
        elif self.current_state == "thinking":
            delay = random.randint(200, 400)
        else: # Idle
            delay = random.randint(2000, 4000)

        # Schedule this function to run again
        self.root.after(delay, self.animate)

if __name__ == "__main__":
    root = tk.Tk()
    app = BMOFace(root)
    root.mainloop()
    