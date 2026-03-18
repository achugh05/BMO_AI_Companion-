import tkinter as tk
from PIL import Image, ImageTk
import os
import random

class BMOAnimationTest:
    def __init__(self, root):
        self.root = root
        self.root.title("BMO Animation Sandbox")
        self.root.geometry("500x400")
        self.root.configure(bg='#73AF9C') # BMO Teal

        # 1. Setup Canvas
        self.canvas = tk.Canvas(root, width=500, height=400, bg='#73AF9C', highlightthickness=0)
        self.canvas.pack()

        # 2. Load Images from your folder
        self.frames = self.load_images("assets/thinking")
        
        if not self.frames:
            print("Error: No images found in assets/thinking!")
            return

        # 3. Create the image object on the canvas
        self.display_image = self.canvas.create_image(250, 200, image=self.frames[0])
        
        # 4. Start the animation loop
        self.update_animation()

    def load_images(self, path):
        """Loads all images from a directory and converts them for Tkinter."""
        images = []
        if os.path.exists(path):
            files = [f for f in os.listdir(path) if f.endswith(('.png', '.jpg', '.jpeg'))]
            for f in sorted(files):
                full_path = os.path.join(path, f)
                img = Image.open(full_path)
                # Resize to fit the screen
                img = img.resize((300, 300), Image.Resampling.LANCZOS)
                images.append(ImageTk.PhotoImage(img))
        return images

    def update_animation(self):
        """Picks a random frame and schedules the next update."""
        # Pick a random frame from our list
        new_frame = random.choice(self.frames)
        
        # Update the canvas image
        self.canvas.itemconfig(self.display_image, image=new_frame)
        
        # IMPORTANT: Keep a reference to the image so Python doesn't delete it
        self.current_img = new_frame

        # Schedule this function to run again in 200ms (0.2 seconds)
        # Change 200 to something else to speed up or slow down
        self.root.after(200, self.update_animation)

if __name__ == "__main__":
    root = tk.Tk()
    app = BMOAnimationTest(root)
    root.mainloop()