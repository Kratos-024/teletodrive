from flask import Flask, render_template, jsonify, request, redirect, url_for
import os
import json
import asyncio
import threading
import time
import re
import tempfile
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo
import io

app = Flask(__name__)

# Configuration - Use environment variables for production
SCOPES = ['https://www.googleapis.com/auth/drive.file']
GDRIVE_FOLDER_NAME = 'Telegram Videos'
UPLOADED_TRACKER = 'uploaded_videos.json'

# Telegram API credentials - Use environment variables in production
API_ID = int(os.environ.get('API_ID', '27395677'))
API_HASH = os.environ.get('API_HASH', 'b7ee4d7b5b578e5a2ebba4dd0ff84838')
PHONE_NUMBER = os.environ.get('PHONE_NUMBER', '+918512094758')
TARGET_CHAT = os.environ.get('TARGET_CHAT', 'campusxdsmp1_0')

# Global status variables
download_status = {"running": False, "progress": "", "total_videos": 0, "current": 0, "completed": 0}
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
            
            # Load existing credentials
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
                    try:
                        creds = flow.run_local_server(port=0)
                    except Exception as e:
                        print(f"OAuth flow failed: {e}")
                        return False
                
                # Save credentials
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
    
    def upload_stream(self, file_stream, filename, file_size=None):
        """Upload file stream directly to Google Drive"""
        try:
            file_metadata = {
                'name': filename,
                'parents': [self.folder_id]
            }
            
            # Create media upload from stream
            media = MediaIoBaseUpload(
                file_stream, 
                mimetype='video/mp4',
                resumable=True,
                chunksize=1024*1024  # 1MB chunks
            )
            
            # Upload file
            result = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,size'
            ).execute()
            
            # Track uploaded file
            self.uploaded[filename] = {
                'drive_id': result.get('id'),
                'uploaded_at': datetime.now().isoformat(),
                'size': file_size or result.get('size', 0)
            }
            self.save_tracker()
            
            return result.get('id')
            
        except Exception as e:
            print(f"Upload failed for {filename}: {e}")
            return None

async def download_and_upload_directly():
    """Download videos and upload directly to Google Drive without local storage"""
    global download_status
    download_status["running"] = True
    download_status["progress"] = "Initializing..."
    download_status["completed"] = 0
    
    client = None
    try:
        # Initialize Telegram client
        client = TelegramClient('session', API_ID, API_HASH)
        await client.start(PHONE_NUMBER)
        download_status["progress"] = "Connected to Telegram"
        
        # Initialize Google Drive
        uploader = DriveUploader()
        if not uploader.authenticate():
            download_status["progress"] = "Failed to authenticate with Google Drive"
            return
        
        if not uploader.create_folder():
            download_status["progress"] = "Failed to create/access Google Drive folder"
            return
        
        download_status["progress"] = "Connected to Google Drive"
        
        # Get video messages
        download_status["progress"] = f"Scanning {TARGET_CHAT} for videos..."
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
            download_status["progress"] = f"Error scanning messages: {str(e)}"
            return
        
        download_status["total_videos"] = len(video_messages)
        download_status["progress"] = f"Found {len(video_messages)} videos"
        
        if not video_messages:
            download_status["progress"] = "No videos found in the channel"
            return
        
        # Process videos - download and upload directly
        for i, message in enumerate(video_messages, 1):
            download_status["current"] = i
            
            try:
                filename = get_video_filename(message)
                
                # Skip if already uploaded
                if filename in uploader.uploaded:
                    download_status["progress"] = f"Skipping {filename} (already uploaded)"
                    download_status["completed"] += 1
                    continue
                
                download_status["progress"] = f"Processing {filename}..."
                
                # Get file size for progress tracking
                file_size = getattr(message.media.document, 'size', 0)
                
                # Download to memory buffer
                download_status["progress"] = f"Downloading {filename}..."
                file_buffer = io.BytesIO()
                
                await client.download_media(message, file=file_buffer)
                file_buffer.seek(0)  # Reset buffer position
                
                # Upload directly from buffer
                download_status["progress"] = f"Uploading {filename} to Google Drive..."
                
                drive_id = uploader.upload_stream(file_buffer, filename, file_size)
                
                if drive_id:
                    download_status["progress"] = f"✓ Completed: {filename}"
                    download_status["completed"] += 1
                else:
                    download_status["progress"] = f"✗ Upload failed: {filename}"
                
                # Clear buffer from memory
                file_buffer.close()
                
                # Small delay to prevent overwhelming the APIs
                await asyncio.sleep(1)
                
            except Exception as e:
                error_msg = f"✗ Error processing {filename if 'filename' in locals() else f'video {i}'}: {str(e)}"
                download_status["progress"] = error_msg
                print(error_msg)
                continue
        
        download_status["progress"] = f"Completed! Processed {download_status['completed']}/{download_status['total_videos']} videos"
    
    except Exception as e:
        error_msg = f"Process error: {str(e)}"
        download_status["progress"] = error_msg
        print(error_msg)
    
    finally:
        if client and client.is_connected():
            await client.disconnect()
        download_status["running"] = False

def run_direct_process():
    """Run the direct download and upload process"""
    try:
        asyncio.run(download_and_upload_directly())
    except Exception as e:
        print(f"Process runner error: {e}")
        download_status["running"] = False
        download_status["progress"] = f"Error: {str(e)}"

def monitoring_loop(interval_minutes):
    """Monitoring loop for automatic processing"""
    global monitoring_status
    while monitoring_status["running"]:
        try:
            print(f"[{datetime.now()}] Monitoring: Running auto process...")
            run_direct_process()
            monitoring_status["last_run"] = datetime.now().isoformat()
            
            if monitoring_status["running"]:
                time.sleep(interval_minutes * 60)
        except Exception as e:
            print(f"Monitoring loop error: {e}")
            time.sleep(60)

# API Endpoints
@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify({
        "download": download_status,
        "monitoring": monitoring_status
    })

@app.route('/api/health', methods=['GET'])
def api_health():
    return jsonify({
        "status": "ok", 
        "timestamp": datetime.now().isoformat(),
        "credentials_exists": os.path.exists('credentials.json'),
        "token_exists": os.path.exists('token.json'),
        "mode": "direct_upload"
    })

@app.route('/api/start-process', methods=['POST'])
def api_start_process():
    if download_status["running"]:
        return jsonify({"status": "already_running"})
    
    try:
        thread = threading.Thread(target=run_direct_process)
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
        interval = max(5, min(1440, data.get('interval', 30)))  # Between 5 minutes and 24 hours
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

@app.route('/api/list-uploaded', methods=['GET'])
def api_list_uploaded():
    try:
        uploader = DriveUploader()
        uploaded_files = uploader.load_tracker()
        return jsonify(uploaded_files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Web Interface Endpoints
@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/start-process', methods=['POST'])
def start_process():
    return api_start_process()

@app.route('/process_status')
def get_process_status():
    return jsonify(download_status)

@app.route('/uploaded-files')
def list_uploaded_files():
    try:
        uploader = DriveUploader()
        uploaded_files = uploader.load_tracker()
        
        file_list = []
        for filename, info in uploaded_files.items():
            size_mb = info.get('size', 0) / 1024 / 1024 if info.get('size') else 0
            file_list.append({
                'name': filename,
                'size': f"{size_mb:.1f} MB",
                'uploaded_at': info.get('uploaded_at', 'Unknown'),
                'drive_id': info.get('drive_id', '')
            })
        
        return jsonify(file_list)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Error handlers
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
    <title>Telegram to Google Drive - Direct Upload</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background-color: #f5f5f5; }
        .header { text-align: center; margin-bottom: 30px; }
        .badge { background: #28a745; color: white; padding: 4px 8px; border-radius: 12px; font-size: 12px; }
        .section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; border-radius: 8px; background: white; }
        .button { padding: 12px 24px; margin: 10px; background: #007cba; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
        .button:disabled { background: #ccc; cursor: not-allowed; }
        .button:hover:not(:disabled) { background: #005a8b; }
        .button.success { background: #28a745; }
        .button.danger { background: #dc3545; }
        .status { margin: 15px 0; padding: 15px; background: #f8f9fa; border-radius: 6px; border-left: 4px solid #007cba; word-wrap: break-word; }
        .progress { margin: 10px 0; font-weight: bold; color: #333; }
        .stats { display: flex; gap: 20px; margin: 15px 0; }
        .stat { flex: 1; text-align: center; padding: 10px; background: #e9ecef; border-radius: 6px; }
        .file-list { max-height: 400px; overflow-y: auto; border: 1px solid #dee2e6; border-radius: 6px; }
        .file-item { padding: 10px; border-bottom: 1px solid #eee; display: flex; justify-content: between; align-items: center; }
        .file-item:last-child { border-bottom: none; }
        .file-name { font-weight: bold; flex: 1; margin-right: 10px; word-break: break-word; }
        .file-meta { font-size: 12px; color: #666; }
        .uploaded { color: #28a745; }
        .error { color: #dc3545; background: #f8d7da; border-left-color: #dc3545; }
        .success { color: #155724; background: #d4edda; border-left-color: #28a745; }
        .monitoring-controls { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .interval-input { padding: 8px; border: 1px solid #ddd; border-radius: 4px; width: 100px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Telegram to Google Drive</h1>
        <span class="badge">Direct Upload - No Local Storage</span>
        <p>Downloads videos from Telegram and uploads directly to Google Drive</p>
    </div>
    
    <div class="section">
        <h2>Process Control</h2>
        <button id="processBtn" class="button" onclick="startProcess()">Start Processing</button>
        <div id="processStatus" class="status">Ready to start processing videos</div>
        <div id="processProgress" class="progress"></div>
        
        <div class="stats">
            <div class="stat">
                <div>Current</div>
                <div id="currentStat">0</div>
            </div>
            <div class="stat">
                <div>Total Found</div>
                <div id="totalStat">0</div>
            </div>
            <div class="stat">
                <div>Completed</div>
                <div id="completedStat">0</div>
            </div>
        </div>
    </div>
    
    <div class="section">
        <h2>Auto Monitoring</h2>
        <div class="monitoring-controls">
            <input type="number" id="intervalInput" class="interval-input" value="30" min="5" max="1440" placeholder="Minutes">
            <button id="startMonitoringBtn" class="button success" onclick="startMonitoring()">Start Monitoring</button>
            <button id="stopMonitoringBtn" class="button danger" onclick="stopMonitoring()" disabled>Stop Monitoring</button>
        </div>
        <div id="monitoringStatus" class="status">Monitoring is stopped</div>
    </div>
    
    <div class="section">
        <h2>Uploaded Files</h2>
        <button class="button" onclick="loadUploadedFiles()">Refresh List</button>
        <div id="fileList" class="file-list">
            <div style="padding: 20px; text-align: center; color: #666;">Click "Refresh List" to load uploaded files</div>
        </div>
    </div>

    <script>
        let statusUpdateInterval = null;
        let monitoringUpdateInterval = null;

        function updateElementClass(elementId, text, className = '') {
            const element = document.getElementById(elementId);
            element.textContent = text;
            element.className = element.className.replace(/\b(error|success)\b/g, '');
            if (className) {
                element.classList.add(className);
            }
        }

        function startProcess() {
            fetch('/start-process', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'started') {
                        document.getElementById('processBtn').disabled = true;
                        document.getElementById('processBtn').textContent = 'Processing...';
                        startStatusUpdates();
                    } else if (data.status === 'error') {
                        updateElementClass('processStatus', `Error: ${data.message}`, 'error');
                    } else if (data.status === 'already_running') {
                        updateElementClass('processStatus', 'Process is already running', 'error');
                    }
                })
                .catch(err => updateElementClass('processStatus', `Error: ${err.message}`, 'error'));
        }

        function startStatusUpdates() {
            if (statusUpdateInterval) clearInterval(statusUpdateInterval);
            
            statusUpdateInterval = setInterval(() => {
                fetch('/process_status')
                    .then(r => r.json())
                    .then(data => {
                        const isError = data.progress && (data.progress.includes('Error') || data.progress.includes('Failed'));
                        const isSuccess = data.progress && data.progress.includes('Completed!');
                        
                        let className = '';
                        if (isError) className = 'error';
                        else if (isSuccess) className = 'success';
                        
                        updateElementClass('processStatus', data.progress, className);
                        
                        // Update stats
                        document.getElementById('currentStat').textContent = data.current || 0;
                        document.getElementById('totalStat').textContent = data.total_videos || 0;
                        document.getElementById('completedStat').textContent = data.completed || 0;
                        
                        // Update progress
                        if (data.total_videos > 0) {
                            document.getElementById('processProgress').textContent = 
                                `Progress: ${data.current || 0}/${data.total_videos} (${data.completed || 0} completed)`;
                        }
                        
                        // Re-enable button when done
                        if (!data.running) {
                            document.getElementById('processBtn').disabled = false;
                            document.getElementById('processBtn').textContent = 'Start Processing';
                            clearInterval(statusUpdateInterval);
                            loadUploadedFiles(); // Refresh file list
                        }
                    })
                    .catch(err => {
                        updateElementClass('processStatus', `Status update error: ${err.message}`, 'error');
                    });
            }, 3000); // Update every 3 seconds
        }

        function startMonitoring() {
            const interval = parseInt(document.getElementById('intervalInput').value) || 30;
            
            fetch('/api/start-monitoring', { 
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ interval: interval })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'started') {
                        document.getElementById('startMonitoringBtn').disabled = true;
                        document.getElementById('stopMonitoringBtn').disabled = false;
                        updateElementClass('monitoringStatus', `Monitoring started - checking every ${interval} minutes`, 'success');
                        startMonitoringUpdates();
                    } else if (data.status === 'error') {
                        updateElementClass('monitoringStatus', `Error: ${data.message}`, 'error');
                    }
                })
                .catch(err => updateElementClass('monitoringStatus', `Error: ${err.message}`, 'error'));
        }

        function stopMonitoring() {
            fetch('/api/stop-monitoring', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    document.getElementById('startMonitoringBtn').disabled = false;
                    document.getElementById('stopMonitoringBtn').disabled = true;
                    updateElementClass('monitoringStatus', 'Monitoring stopped');
                    if (monitoringUpdateInterval) {
                        clearInterval(monitoringUpdateInterval);
                    }
                })
                .catch(err => updateElementClass('monitoringStatus', `Error: ${err.message}`, 'error'));
        }

        function startMonitoringUpdates() {
            if (monitoringUpdateInterval) clearInterval(monitoringUpdateInterval);
            
            monitoringUpdateInterval = setInterval(() => {
                fetch('/api/status')
                    .then(r => r.json())
                    .then(data => {
                        if (!data.monitoring.running) {
                            stopMonitoring();
                            return;
                        }
                        
                        const lastRun = data.monitoring.last_run ? 
                            new Date(data.monitoring.last_run).toLocaleString() : 'Never';
                        updateElementClass('monitoringStatus', 
                            `Monitoring active - Interval: ${data.monitoring.interval}min, Last run: ${lastRun}`, 
                            'success');
                    })
                    .catch(err => console.error('Monitoring status error:', err));
            }, 10000); // Update every 10 seconds
        }

        function loadUploadedFiles() {
            fetch('/uploaded-files')
                .then(r => r.json())
                .then(files => {
                    if (files.error) {
                        document.getElementById('fileList').innerHTML = `<div class="error" style="padding: 20px;">Error: ${files.error}</div>`;
                        return;
                    }
                    
                    if (files.length === 0) {
                        document.getElementById('fileList').innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">No files uploaded yet</div>';
                        return;
                    }
                    
                    const fileList = document.getElementById('fileList');
                    fileList.innerHTML = files.map(file => 
                        `<div class="file-item">
                            <div class="file-name">${file.name}</div>
                            <div class="file-meta">
                                ${file.size} • ${new Date(file.uploaded_at).toLocaleString()}
                                <br><span class="uploaded">✓ Uploaded to Drive</span>
                            </div>
                        </div>`
                    ).join('');
                })
                .catch(err => {
                    document.getElementById('fileList').innerHTML = `<div class="error" style="padding: 20px;">Error loading files: ${err.message}</div>`;
                });
        }

        // Initialize page
        document.addEventListener('DOMContentLoaded', function() {
            loadUploadedFiles();
            
            // Check if anything is currently running
            fetch('/process_status')
                .then(r => r.json())
                .then(data => {
                    if (data.running) {
                        document.getElementById('processBtn').disabled = true;
                        document.getElementById('processBtn').textContent = 'Processing...';
                        startStatusUpdates();
                    }
                })
                .catch(err => console.error('Initial status check failed:', err));
                
            // Check monitoring status
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    if (data.monitoring && data.monitoring.running) {
                        document.getElementById('startMonitoringBtn').disabled = true;
                        document.getElementById('stopMonitoringBtn').disabled = false;
                        startMonitoringUpdates();
                    }
                })
                .catch(err => console.error('Initial monitoring check failed:', err));
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    # Get port from environment variable (required for Render)
    port = int(os.environ.get('PORT', 5000))
    
    # Print access information
    print("🚀 Telegram to Google Drive - Direct Upload")
    print("=" * 50)
    print(f"✅ Server starting on port: {port}")
    print(f"🌐 Local access: http://localhost:{port}")
    print(f"🔗 Network access: http://0.0.0.0:{port}")
    print("=" * 50)
    print("📱 Frontend Interface:")
    print(f"   • Web UI: http://localhost:{port}/")
    print(f"   • API Status: http://localhost:{port}/api/status")
    print(f"   • Health Check: http://localhost:{port}/api/health")
    print("=" * 50)
    print("🎯 For deployment (Render/Heroku):")
    print("   • Your app will be available at your deployment URL")
    print("   • Make sure to set environment variables!")
    print("=" * 50)
    
    # Run with production settings for deployment
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_ENV') == 'development'
    )
