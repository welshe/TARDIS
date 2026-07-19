import time, threading
from mss import mss
from PIL import Image, ImageChops
import io
import hashlib

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

    def get_frame_at(self, timestamp):
        """Get the frame closest to a specific timestamp"""
        if not self.frames:
            return None
        closest = min(self.frames, key=lambda x: abs(x[0] - timestamp))
        return closest[1]

    def compute_diff(self, frame1, frame2, threshold=30):
        """Compute difference between two frames"""
        if frame1 is None or frame2 is None:
            return None
        
        # Ensure same size
        if frame1.size != frame2.size:
            frame2 = frame2.resize(frame1.size)
        
        # Compute difference
        diff = ImageChops.difference(frame1, frame2)
        
        # Convert to grayscale for easier analysis
        diff_gray = diff.convert('L')
        
        # Count pixels above threshold
        diff_data = diff_gray.getdata()
        changed_pixels = sum(1 for p in diff_data if p > threshold)
        total_pixels = diff_gray.size[0] * diff_gray.size[1]
        change_percentage = (changed_pixels / total_pixels) * 100 if total_pixels else 0.0
        
        # Create highlighted diff image using composite for speed
        mask = diff_gray.point(lambda p: 255 if p > threshold else 0)
        red_overlay = Image.new('RGB', frame1.size, (255, 0, 0))
        diff_highlight = Image.composite(red_overlay, frame1, mask)
        
        return {
            'change_percentage': change_percentage,
            'changed_pixels': changed_pixels,
            'total_pixels': total_pixels,
            'diff_image': diff_highlight,
            'diff_hash': self._hash_image(diff_highlight)
        }

    def _hash_image(self, img):
        """Create a hash of an image for comparison"""
        # Resize to small thumbnail for hashing
        thumb = img.copy()
        thumb.thumbnail((64, 64))
        img_bytes = io.BytesIO()
        thumb.save(img_bytes, format='PNG')
        return hashlib.md5(img_bytes.getvalue()).hexdigest()[:16]

    def detect_layout_shift(self, frame1, frame2):
        """Detect if layout has shifted significantly (for grounding failures)"""
        diff_result = self.compute_diff(frame1, frame2)
        if not diff_result:
            return False
        
        # Layout shift is significant if >15% of pixels changed
        return diff_result['change_percentage'] > 15.0

    def get_movement_regions(self, frame1, frame2, threshold=30):
        """Identify regions of the screen that have changed"""
        if frame1 is None or frame2 is None:
            return []
        
        # Ensure same size
        if frame1.size != frame2.size:
            frame2 = frame2.resize(frame1.size)
        
        diff = ImageChops.difference(frame1, frame2)
        diff_gray = diff.convert('L')
        
        # Find bounding boxes of changed regions
        regions = []
        pixels = diff_gray.load()
        width, height = diff_gray.size
        
        visited = set()
        
        def flood_fill(start_x, start_y):
            if (start_x, start_y) in visited:
                return None
            if pixels[start_x, start_y] <= threshold:
                return None
            
            min_x, max_x = start_x, start_x
            min_y, max_y = start_y, start_y
            stack = [(start_x, start_y)]
            
            while stack:
                x, y = stack.pop()
                if (x, y) in visited:
                    continue
                if x < 0 or x >= width or y < 0 or y >= height:
                    continue
                if pixels[x, y] <= threshold:
                    continue
                
                visited.add((x, y))
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, y)
                max_y = max(max_y, y)
                
                # Add neighbors
                stack.extend([(x+1, y), (x-1, y), (x, y+1), (x, y-1)])
            
            return (min_x, min_y, max_x - min_x, max_y - min_y)
        
        for y in range(0, height, 10):  # Sample every 10 pixels
            for x in range(0, width, 10):
                region = flood_fill(x, y)
                if region:
                    regions.append(region)
        
        return regions

    def capture_with_metadata(self):
        """Capture current screen with metadata"""
        with mss() as sct:
            shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            original_size = img.size
            img.thumbnail((1280, 720))
            
            return {
                'timestamp': time.time(),
                'image': img,
                'original_size': original_size,
                'hash': self._hash_image(img)
            }
