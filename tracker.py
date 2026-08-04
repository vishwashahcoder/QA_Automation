import os
import json
import base64
import sqlite3
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 8000
CAPTURE_DIR = "captures"
DB_NAME = "activity_log.db"

def init_db():
    """Initializes the SQLite database schema if it doesn't exist."""
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            reason TEXT,
            window_title TEXT,
            process_name TEXT,
            screenshot_path TEXT
        )
    """)
    conn.commit()
    conn.close()

class ActivityTrackerHandler(BaseHTTPRequestHandler):
    """Custom request handler to handle CORS options and /capture POST endpoints."""
    
    def do_OPTIONS(self):
        # Enable CORS for Chrome Extension requests
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if self.path == "/capture":
            # Enable CORS
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            # Read content payload length
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode("utf-8"))
                url = data.get("url", "")
                title = data.get("title", "")
                event = data.get("event", "")
                screenshot_data = data.get("screenshot", "")

                if not screenshot_data or not screenshot_data.startswith("data:image/png;base64,"):
                    self.wfile.write(json.dumps({"status": "error", "message": "Invalid image format"}).encode("utf-8"))
                    return

                # Decode Base64 Image
                header, base64_str = screenshot_data.split(",", 1)
                image_bytes = base64.b64decode(base64_str)

                # Generate file path
                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                parsed_url = urlparse(url)
                
                # Make host name clean for a safe filename
                safe_host = "".join([c if c.isalnum() else "_" for c in parsed_url.netloc])
                filename = f"{timestamp_str}_{safe_host}_{event}.png"
                filepath = os.path.join(CAPTURE_DIR, filename)

                # Save screenshot to captures folder
                with open(filepath, "wb") as f:
                    f.write(image_bytes)

                # Log entry to SQLite
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO activity_log (timestamp, reason, window_title, process_name, screenshot_path) VALUES (?, ?, ?, ?, ?)",
                    (datetime.now().isoformat(), event, title, parsed_url.netloc, filepath)
                )
                conn.commit()
                conn.close()

                print(f"[{datetime.now().strftime('%H:%M:%S')}] Saved ({event}): {url} -> {filepath}")
                self.wfile.write(json.dumps({"status": "success", "path": filepath}).encode("utf-8"))

            except Exception as e:
                print(f"Error handling capture: {e}")
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run(server_class=HTTPServer, handler_class=ActivityTrackerHandler):
    init_db()
    server_address = ("", PORT)
    httpd = server_class(server_address, handler_class)
    print("=" * 60)
    print("           ACTIVITY-BASED RECEIVER SERVER")
    print("=" * 60)
    print(f"Server listening on: http://localhost:{PORT}")
    print(f"Screenshots folder:  {os.path.abspath(CAPTURE_DIR)}")
    print(f"Database file:       {os.path.abspath(DB_NAME)}")
    print("Press Ctrl+C in this console to stop the server.")
    print("-" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        httpd.server_close()
        print("Server stopped successfully.")

if __name__ == "__main__":
    run()
