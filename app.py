from flask import Flask, render_template, jsonify, request, redirect, url_for
import os
import json
import asyncio
import threading
import time
import re
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo

app = Flask(__name__)

# Configuration - Use environment variables for production
SCOPES = ['https://www.googleapis.com/auth/drive.file']
VIDEOS_FOLDER = 'telegram_videos'
GDRIVE_FOLDER_NAME = 'Telegram Videos'
UPLOADED_TRACKER = 'uploaded_videos.json'

# Telegram API credentials - Use environment variables in production
API_ID = int(os.environ.get('API_ID', '27395677'))
API_HASH = os.environ.get('API_HASH', 'b7ee4d7b5b578e5a2ebba4dd0ff84838')
PHONE_NUMBER = os.environ.get('PHONE_NUMBER', '+918512094758')
TARGET_CHAT = os.environ.get('TARGET_CHAT', 'campusxdsmp1_0')

# Global status variables
download_status = {"running": False, "progress": "", "total_videos": 0, "current": 0}
upload_status = {"running": False, "progress": "", "total_files": 0, "current": 0}
monitoring_status = {"running": False, "interval": 30, "last_run": None}

def sanitize_filename(text, max_length=100):
    """Convert message text to a safe filename"""
    if not text or not isinstance(text, str):
        return None
    
    # Remove "Title » " prefix if it exists
    text = re.sub(r'^Title\s*»\s*', '', text, flags=re.IGNORECASE)
    
    # Remove or replace invalid characters
    filename = re.sub(r'[<>:"/\\|?*]', '', text)  # Remove invalid chars
    filename = re.sub(r'[^\w\s\-_\.\(\)]', '', filename)  # Keep only safe chars
    filename = re.sub(r'\s+', ' ', filename)  # Replace multiple spaces with single
    filename = filename.strip()
    
    # Truncate if too long (leave room for extension)
    if len(filename) > max_length:
        filename = filename[:max_length].rsplit(' ', 1)[0]  # Break at word boundary
    
    return filename if filename else None

def get_video_filename(message):
    """Generate filename from message text or fallback to message ID"""
    clean_name = None
    
    # Try to get filename from message text
    if message.text:
        clean_name = sanitize_filename(message.text)
    
    # If no clean name, use message ID as fallback
    if not clean_name:
        clean_name = f"video_{message.id}"
    
    # Ensure it ends with .mp4
    if not clean_name.lower().endswith('.mp4'):
        clean_name += '.mp4'
    
    return clean_name

class DriveUploader:
    def __init__(self):
        self.service = None
        self.folder_id = None
        self.uploaded = self.load_tracker()
    
    def authenticate(self):
        try:
            creds = None
            
            # For production, credentials might be stored as environment variables
            if os.path.exists('token.json'):
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception as e:
                        print(f"Token refresh failed: {e}")
                        creds = None
                
                if not creds:
                    if not os.path.exists('credentials.json'):
                        print("credentials.json not found - Google Drive authentication will fail")
                        return False
                    
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    # Use different ports for different environments
                    try:
                        creds = flow.run_local_server(port=0)
                    except Exception as e:
                        print(f"OAuth flow failed: {e}")
                        return False
                
                # Save the credentials for the next run
                try:
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
                except Exception as e:
                    print(f"Failed to save token: {e}")
            
            self.service = build('drive', 'v3', credentials=creds)
            return True
            
        except Exception as e:
            print(f"Authentication failed: {e}")
            return False
    
    def create_folder(self):
        try:
            results = self.service.files().list(
                q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            ).execute()
            
            if results.get('files'):
                self.folder_id = results['files'][0]['id']
                print(f"Found existing folder: {GDRIVE_FOLDER_NAME}")
            else:
                folder = self.service.files().create(body={
                    'name': GDRIVE_FOLDER_NAME,
                    'mimeType': 'application/vnd.google-apps.folder'
                }).execute()
                self.folder_id = folder.get('id')
                print(f"Created new folder: {GDRIVE_FOLDER_NAME}")
            
            return True
            
        except Exception as e:
            print(f"Failed to create/find folder: {e}")
            return False
    
    def load_tracker(self):
        try:
            if os.path.exists(UPLOADED_TRACKER):
                with open(UPLOADED_TRACKER, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Failed to load tracker: {e}")
        return {}
    
    def save_tracker(self):
        try:
            with open(UPLOADED_TRACKER, 'w', encoding='utf-8') as f:
                json.dump(self.uploaded, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Failed to save tracker: {e}")
    
    def upload_videos(self):
        global upload_status
        upload_status["running"] = True
        upload_status["progress"] = "Starting upload process..."
        
        try:
            if not os.path.exists(VIDEOS_FOLDER):
                upload_status["progress"] = "Videos folder not found"
                return
            
            video_files = []
            for f in os.listdir(VIDEOS_FOLDER):
                if f.lower().endswith(('.mp4', '.avi', '.mkv', '.mov', '.webm')):
                    video_files.append(f)
            
            new_videos = [f for f in video_files if f not in self.uploaded]
            upload_status["total_files"] = len(new_videos)
            
            if not new_videos:
                upload_status["progress"] = "No new videos to upload"
                return
            
            for i, filename in enumerate(new_videos, 1):
                upload_status["current"] = i
                upload_status["progress"] = f"Uploading: {filename}"
                
                filepath = os.path.join(VIDEOS_FOLDER, filename)
                
                try:
                    media = MediaFileUpload(filepath, resumable=True)
                    file_metadata = {'name': filename, 'parents': [self.folder_id]}
                    
                    result = self.service.files().create(
                        body=file_metadata, 
                        media_body=media,
                        fields='id'
                    ).execute()
                    
                    self.uploaded[filename] = {
                        'drive_id': result.get('id'),
                        'uploaded_at': datetime.now().isoformat(),
                        'size': os.path.getsize(filepath)
                    }
                    self.save_tracker()
                    
                    upload_status["progress"] = f"✓ Uploaded: {filename}"
                    
                except Exception as e:
                    upload_status["progress"] = f"✗ Failed to upload {filename}: {str(e)}"
                    print(f"Upload error for {filename}: {e}")
                    continue
        
        except Exception as e:
            upload_status["progress"] = f"Error: {str(e)}"
            print(f"Upload process error: {e}")
        
        finally:
            upload_status["running"] = False

async def download_telegram_videos():
    global download_status
    download_status["running"] = True
    download_status["progress"] = "Initializing Telegram client..."
    
    client = None
    try:
        client = TelegramClient('session', API_ID, API_HASH)
        await client.start(PHONE_NUMBER)
        
        if not os.path.exists(VIDEOS_FOLDER):
            os.makedirs(VIDEOS_FOLDER)
        
        download_status["progress"] = f"Fetching messages from {TARGET_CHAT}..."
        
        # Get video messages
        video_messages = []
        try:
            async for message in client.iter_messages(TARGET_CHAT):
                if (message.media and 
                    isinstance(message.media, MessageMediaDocument) and 
                    message.media.document and 
                    hasattr(message.media.document, 'attributes') and
                    message.media.document.attributes):
                    
                    for attr in message.media.document.attributes:
                        if isinstance(attr, DocumentAttributeVideo):
                            video_messages.append(message)
                            break
        except Exception as e:
            download_status["progress"] = f"Error fetching messages: {str(e)}"
            return
        
        download_status["total_videos"] = len(video_messages)
        download_status["progress"] = f"Found {len(video_messages)} videos"
        
        if not video_messages:
            download_status["progress"] = "No videos found in the channel"
            return
        
        # Download videos
        for i, message in enumerate(video_messages, 1):
            download_status["current"] = i
            
            try:
                filename = get_video_filename(message)
                filepath = os.path.join(VIDEOS_FOLDER, filename)
                
                if os.path.exists(filepath):
                    download_status["progress"] = f"Skipping {filename} (already exists)"
                    continue
                
                download_status["progress"] = f"Downloading: {filename}"
                
                await client.download_media(message, file=filepath)
                download_status["progress"] = f"✓ Downloaded: {filename}"
                
            except Exception as e:
                error_msg = f"✗ Failed to download video {i}: {str(e)}"
                download_status["progress"] = error_msg
                print(error_msg)
                continue
        
        download_status["progress"] = "Download completed!"
    
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        download_status["progress"] = error_msg
        print(f"Download process error: {e}")
    
    finally:
        if client and client.is_connected():
            await client.disconnect()
        download_status["running"] = False

def run_download():
    try:
        asyncio.run(download_telegram_videos())
    except Exception as e:
        print(f"Download runner error: {e}")
        download_status["running"] = False
        download_status["progress"] = f"Error: {str(e)}"

def run_upload():
    try:
        uploader = DriveUploader()
        if uploader.authenticate():
            if uploader.create_folder():
                uploader.upload_videos()
            else:
                upload_status["progress"] = "Failed to create/access Google Drive folder"
        else:
            upload_status["progress"] = "Failed to authenticate with Google Drive"
    except Exception as e:
        print(f"Upload runner error: {e}")
        upload_status["running"] = False
        upload_status["progress"] = f"Error: {str(e)}"

def monitoring_loop(interval_minutes):
    global monitoring_status
    while monitoring_status["running"]:
        try:
            print(f"[{datetime.now()}] Monitoring: Running auto download and upload...")
            run_download()
            time.sleep(5)  # Small delay between operations
            run_upload()
            monitoring_status["last_run"] = datetime.now().isoformat()
            
            if monitoring_status["running"]:  # Check if still running
                time.sleep(interval_minutes * 60)
        except Exception as e:
            print(f"Monitoring loop error: {e}")
            time.sleep(60)  # Wait a minute before retrying

# API Endpoints with error handling
@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        "download": download_status,
        "upload": upload_status,
        "monitoring": monitoring_status
    })

@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({
        "status": "ok", 
        "timestamp": datetime.now().isoformat(),
        "videos_folder_exists": os.path.exists(VIDEOS_FOLDER),
        "credentials_exists": os.path.exists('credentials.json'),
        "token_exists": os.path.exists('token.json')
    })

@app.route('/api/start-download', methods=['POST'])
def api_start_download():
    if download_status["running"]:
        return jsonify({"status": "already_running"})
    
    try:
        thread = threading.Thread(target=run_download)
        thread.daemon = True
        thread.start()
        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/start-upload', methods=['POST'])
def api_start_upload():
    if upload_status["running"]:
        return jsonify({"status": "already_running"})
    
    try:
        thread = threading.Thread(target=run_upload)
        thread.daemon = True
        thread.start()
        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/start-monitoring', methods=['POST'])
def api_start_monitoring():
    if monitoring_status["running"]:
        return jsonify({"status": "already_running"})
    
    try:
        data = request.json or {}
        interval = max(1, min(1440, data.get('interval', 30)))  # Between 1 minute and 24 hours
        monitoring_status["interval"] = interval
        monitoring_status["running"] = True
        
        thread = threading.Thread(target=monitoring_loop, args=(interval,))
        thread.daemon = True
        thread.start()
        return jsonify({"status": "started", "interval": interval})
    except Exception as e:
        monitoring_status["running"] = False
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/stop-monitoring', methods=['POST'])
def api_stop_monitoring():
    if not monitoring_status["running"]:
        return jsonify({"status": "not_running"})
    
    monitoring_status["running"] = False
    return jsonify({"status": "stopped"})

@app.route('/api/auto-mode', methods=['POST'])
def api_auto_mode():
    if download_status["running"] or upload_status["running"]:
        return jsonify({"status": "operation_in_progress"})
    
    try:
        # Run download first, then upload, then start monitoring
        def run_auto_sequence():
            run_download()
            time.sleep(5)
            run_upload()
        
        thread = threading.Thread(target=run_auto_sequence)
        thread.daemon = True
        thread.start()
        
        # Start monitoring after a delay
        def start_monitoring_delayed():
            time.sleep(10)  # Wait for operations to start
            if not monitoring_status["running"]:
                monitoring_status["interval"] = 30
                monitoring_status["running"] = True
                monitoring_thread = threading.Thread(target=monitoring_loop, args=(30,))
                monitoring_thread.daemon = True
                monitoring_thread.start()
        
        monitor_thread = threading.Thread(target=start_monitoring_delayed)
        monitor_thread.daemon = True
        monitor_thread.start()
        
        return jsonify({"status": "started"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/list-uploaded', methods=['GET'])
def api_list_uploaded():
    try:
        uploader = DriveUploader()
        return jsonify(uploader.load_tracker())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Original Web Endpoints
@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/download', methods=['POST'])
def start_download():
    return api_start_download()

@app.route('/upload', methods=['POST'])
def start_upload():
    return api_start_upload()

@app.route('/download_status')
def get_download_status():
    return jsonify(download_status)

@app.route('/upload_status')
def get_upload_status():
    return jsonify(upload_status)

@app.route('/files')
def list_files():
    try:
        files = []
        if os.path.exists(VIDEOS_FOLDER):
            uploader = DriveUploader()
            uploaded_files = uploader.load_tracker()
            
            for filename in os.listdir(VIDEOS_FOLDER):
                if filename.lower().endswith(('.mp4', '.avi', '.mkv', '.mov', '.webm')):
                    filepath = os.path.join(VIDEOS_FOLDER, filename)
                    if os.path.exists(filepath):
                        size_mb = os.path.getsize(filepath) / 1024 / 1024
                        files.append({
                            'name': filename,
                            'size': f"{size_mb:.1f} MB",
                            'uploaded': filename in uploaded_files
                        })
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Error handlers for production
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# Embedded HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Video Manager</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f5f5f5; }
        .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 5px; background: white; }
        .button { padding: 10px 20px; margin: 10px; background: #007cba; color: white; border: none; border-radius: 5px; cursor: pointer; }
        .button:disabled { background: #ccc; cursor: not-allowed; }
        .button:hover:not(:disabled) { background: #005a8b; }
        .status { margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 3px; border-left: 4px solid #007cba; word-wrap: break-word; }
        .progress { margin: 10px 0; font-weight: bold; }
        .file-list { max-height: 300px; overflow-y: auto; }
        .file-item { padding: 5px; border-bottom: 1px solid #eee; word-wrap: break-word; }
        .uploaded { color: green; }
        .error { color: red; background: #ffe6e6; border-left-color: #ff0000; }
    </style>
</head>
<body>
    <h1>Telegram Video Manager</h1>
    
    <div class="section">
        <h2>Download from Telegram</h2>
        <button id="downloadBtn" class="button" onclick="startDownload()">Start Download</button>
        <div id="downloadStatus" class="status">Ready to download</div>
        <div id="downloadProgress" class="progress"></div>
    </div>
    
    <div class="section">
        <h2>Upload to Google Drive</h2>
        <button id="uploadBtn" class="button" onclick="startUpload()">Start Upload</button>
        <div id="uploadStatus" class="status">Ready to upload</div>
        <div id="uploadProgress" class="progress"></div>
    </div>
    
    <div class="section">
        <h2>Video Files</h2>
        <button class="button" onclick="loadFiles()">Refresh Files</button>
        <div id="fileList" class="file-list"></div>
    </div>

    <script>
        function updateElementClass(elementId, text, isError = false) {
            const element = document.getElementById(elementId);
            element.textContent = text;
            if (isError) {
                element.classList.add('error');
            } else {
                element.classList.remove('error');
            }
        }

        function startDownload() {
            fetch('/download', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'started') {
                        document.getElementById('downloadBtn').disabled = true;
                        updateDownloadStatus();
                    } else if (data.status === 'error') {
                        updateElementClass('downloadStatus', `Error: ${data.message}`, true);
                    }
                })
                .catch(err => updateElementClass('downloadStatus', `Error: ${err.message}`, true));
        }

        function startUpload() {
            fetch('/upload', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'started') {
                        document.getElementById('uploadBtn').disabled = true;
                        updateUploadStatus();
                    } else if (data.status === 'error') {
                        updateElementClass('uploadStatus', `Error: ${data.message}`, true);
                    }
                })
                .catch(err => updateElementClass('uploadStatus', `Error: ${err.message}`, true));
        }

        function updateDownloadStatus() {
            fetch('/download_status')
                .then(r => r.json())
                .then(data => {
                    const isError = data.progress && data.progress.includes('Error');
                    updateElementClass('downloadStatus', data.progress, isError);
                    
                    if (data.total_videos > 0) {
                        document.getElementById('downloadProgress').textContent = 
                            `Progress: ${data.current}/${data.total_videos} videos`;
                    }
                    
                    if (data.running) {
                        setTimeout(updateDownloadStatus, 2000);
                    } else {
                        document.getElementById('downloadBtn').disabled = false;
                        loadFiles(); // Refresh file list when download completes
                    }
                })
                .catch(err => updateElementClass('downloadStatus', `Error: ${err.message}`, true));
        }

        function updateUploadStatus() {
            fetch('/upload_status')
                .then(r => r.json())
                .then(data => {
                    const isError = data.progress && data.progress.includes('Error');
                    updateElementClass('uploadStatus', data.progress, isError);
                    
                    if (data.total_files > 0) {
                        document.getElementById('uploadProgress').textContent = 
                            `Progress: ${data.current}/${data.total_files} files`;
                    }
                    
                    if (data.running) {
                        setTimeout(updateUploadStatus, 2000);
                    } else {
                        document.getElementById('uploadBtn').disabled = false;
                        loadFiles(); // Refresh file list when upload completes
                    }
                })
                .catch(err => updateElementClass('uploadStatus', `Error: ${err.message}`, true));
        }

        function loadFiles() {
            fetch('/files')
                .then(r => r.json())
                .then(files => {
                    if (files.error) {
                        document.getElementById('fileList').innerHTML = `<div class="error">Error: ${files.error}</div>`;
                        return;
                    }
                    
                    const fileList = document.getElementById('fileList');
                    if (files.length === 0) {
                        fileList.innerHTML = '<div>No video files found</div>';
                        return;
                    }
                    
                    fileList.innerHTML = files.map(file => 
                        `<div class="file-item">
                            <strong>${file.name}</strong> (${file.size})
                            ${file.uploaded ? '<span class="uploaded">✓ Uploaded</span>' : ''}
                        </div>`
                    ).join('');
                })
                .catch(err => {
                    document.getElementById('fileList').innerHTML = `<div class="error">Error loading files: ${err.message}</div>`;
                });
        }

        // Load files on page load
        loadFiles();
        
        // Auto-refresh status every 30 seconds
        setInterval(() => {
            if (document.getElementById('downloadBtn').disabled) {
                updateDownloadStatus();
            }
            if (document.getElementById('uploadBtn').disabled) {
                updateUploadStatus();
            }
        }, 30000);
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    # Create necessary directories
    if not os.path.exists(VIDEOS_FOLDER):
        os.makedirs(VIDEOS_FOLDER)
    
    # Get port from environment variable (required for Render)
    port = int(os.environ.get('PORT', 5000))
    
    # Run with production settings for deployment
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_ENV') == 'development'
    )
