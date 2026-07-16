import time, threading
from mss import mss
from PIL import Image
import io

class ScreenBuffer:
    def __init__(self, fps=2):
        self.fps = fps
        self.running = False
        self.frames = []

    def start(self):
        self.running = True
        def loop():
            with mss() as sct:
                while self.running:
                    try:
                        shot = sct.grab(sct.monitors[1])
                        # downsample quickly
                        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                        img.thumbnail((1280, 720))
                        self.frames.append((time.time(), img))
                        if len(self.frames) > 120:
                            self.frames.pop(0)
                    except Exception:
                        pass
                    time.sleep(1.0/self.fps)
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self.running = False

    def get_recent(self, n=5):
        return self.frames[-n:]
