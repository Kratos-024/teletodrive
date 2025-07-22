from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_cors import CORS
import os
import json
import asyncio
import threading
import time
import re
import tempfile
import logging
import traceback
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
import io


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log') if not os.environ.get('RENDER') else logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Enable CORS
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Additional CORS headers
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response


# Configuration - Use environment variables for production
SCOPES = ['https://www.googleapis.com/auth/drive.file']
GDRIVE_FOLDER_NAME = 'Telegram Videos'
UPLOADED_TRACKER = 'uploaded_videos.json'

# Environment variable validation
def validate_environment():
    """Validate required environment variables"""
    required_vars = ['API_ID', 'API_HASH', 'PHONE_NUMBER', 'TARGET_CHAT']
    missing_vars = []
    
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return False, missing_vars
    
    return True, []

# Telegram API credentials - Use environment variables
try:
    API_ID = int(os.environ.get('API_ID', '0'))
    API_HASH = os.environ.get('API_HASH', '')
    PHONE_NUMBER = os.environ.get('PHONE_NUMBER', '')
    TARGET_CHAT = os.environ.get('TARGET_CHAT', '')
    
    if API_ID == 0 or not API_HASH or not PHONE_NUMBER or not TARGET_CHAT:
        logger.warning("Some environment variables are not set properly")
        
except ValueError as e:
    logger.error(f"Invalid API_ID format: {e}")
    API_ID = 0

# Global status variables
download_status = {
    "running": False, 
    "progress": "", 
    "total_videos": 0, 
    "current": 0, 
    "completed": 0,
    "errors": [],
    "last_error": None,
    "start_time": None,
    "end_time": None
}

monitoring_status = {
    "running": False, 
    "interval": 30, 
    "last_run": None,
    "next_run": None,
    "runs_completed": 0,
    "errors": []
}

def safe_execute(func, *args, **kwargs):
    """Safely execute a function with error handling"""
    try:
        return func(*args, **kwargs), None
    except Exception as e:
        error_msg = f"Error in {func.__name__}: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return None, error_msg

def sanitize_filename(text, max_length=100):
    """Convert message text to a safe filename with enhanced error handling"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error sanitizing filename '{text}': {e}")
        return None

def get_video_filename(message):
    """Generate filename from message text or fallback to message ID with error handling"""
    try:
        clean_name = None
        
        # Try to get filename from message text
        if hasattr(message, 'text') and message.text:
            clean_name = sanitize_filename(message.text)
        
        # If no clean name, use message ID as fallback
        if not clean_name:
            clean_name = f"video_{message.id}"
        
        # Ensure it ends with .mp4
        if not clean_name.lower().endswith('.mp4'):
            clean_name += '.mp4'
        
        return clean_name
        
    except Exception as e:
        logger.error(f"Error generating filename for message {getattr(message, 'id', 'unknown')}: {e}")
        return f"video_{int(time.time())}.mp4"

class DriveUploader:
    def __init__(self):
        self.service = None
        self.folder_id = None
        self.uploaded = self.load_tracker()
        self.authenticated = False
    
    def authenticate(self):
        """Enhanced authentication with multiple methods and better error handling"""
        try:
            # Method 1: Try service account first (recommended for production)
            if os.path.exists('service-account-key.json'):
                logger.info("Attempting service account authentication...")
                credentials = service_account.Credentials.from_service_account_file(
                    'service-account-key.json', 
                    scopes=SCOPES
                )
                self.service = build('drive', 'v3', credentials=credentials)
                self.authenticated = True
                logger.info("Service account authentication successful")
                return True
            
            # Method 2: Try existing token
            creds = None
            if os.path.exists('token.json'):
                logger.info("Loading existing token...")
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            
            # Method 3: Refresh or create new credentials
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        logger.info("Refreshing expired token...")
                        creds.refresh(Request())
                        logger.info("Token refresh successful")
                    except Exception as e:
                        logger.warning(f"Token refresh failed: {e}")
                        creds = None
                
                # Method 4: OAuth flow (for local development)
                if not creds:
                    if not os.path.exists('credentials.json'):
                        logger.error("No authentication method available - missing credentials.json and service-account-key.json")
                        return False
                    
                    logger.info("Starting OAuth flow...")
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    try:
                        # Try different ports for OAuth callback
                        for port in [8080, 8081, 8082, 0]:
                            try:
                                creds = flow.run_local_server(port=port, open_browser=False)
                                break
                            except Exception as port_error:
                                logger.warning(f"OAuth failed on port {port}: {port_error}")
                                continue
                        else:
                            logger.error("OAuth flow failed on all ports")
                            return False
                            
                    except Exception as e:
                        logger.error(f"OAuth flow failed: {e}")
                        return False
                
                # Save credentials for next time
                try:
                    with open('token.json', 'w') as token:
                        token.write(creds.to_json())
                    logger.info("Token saved successfully")
                except Exception as e:
                    logger.warning(f"Failed to save token: {e}")
            
            self.service = build('drive', 'v3', credentials=creds)
            self.authenticated = True
            logger.info("Google Drive authentication successful")
            return True
            
        except Exception as e:
            logger.error(f"Google Drive authentication failed: {e}\n{traceback.format_exc()}")
            self.authenticated = False
            return False
    
    def create_folder(self):
        """Create or find Google Drive folder with enhanced error handling"""
        try:
            if not self.service:
                logger.error("Google Drive service not initialized")
                return False
            
            # Search for existing folder
            logger.info(f"Searching for folder: {GDRIVE_FOLDER_NAME}")
            results = self.service.files().list(
                q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="files(id, name)"
            ).execute()
            
            files = results.get('files', [])
            
            if files:
                self.folder_id = files[0]['id']
                logger.info(f"Found existing folder: {GDRIVE_FOLDER_NAME} (ID: {self.folder_id})")
            else:
                # Create new folder
                logger.info(f"Creating new folder: {GDRIVE_FOLDER_NAME}")
                folder_metadata = {
                    'name': GDRIVE_FOLDER_NAME,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                folder = self.service.files().create(
                    body=folder_metadata,
                    fields='id, name'
                ).execute()
                self.folder_id = folder.get('id')
                logger.info(f"Created new folder: {GDRIVE_FOLDER_NAME} (ID: {self.folder_id})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to create/find Google Drive folder: {e}\n{traceback.format_exc()}")
            return False
    
    def load_tracker(self):
        """Load upload tracker with error handling"""
        try:
            if os.path.exists(UPLOADED_TRACKER):
                with open(UPLOADED_TRACKER, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} entries from upload tracker")
                    return data
        except Exception as e:
            logger.error(f"Failed to load upload tracker: {e}")
        
        logger.info("Starting with empty upload tracker")
        return {}
    
    def save_tracker(self):
        """Save upload tracker with error handling"""
        try:
            with open(UPLOADED_TRACKER, 'w', encoding='utf-8') as f:
                json.dump(self.uploaded, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved upload tracker with {len(self.uploaded)} entries")
        except Exception as e:
            logger.error(f"Failed to save upload tracker: {e}")
    
    def upload_stream(self, file_stream, filename, file_size=None):
        """Upload file stream directly to Google Drive with enhanced error handling"""
        try:
            if not self.service or not self.folder_id:
                logger.error("Google Drive service or folder not initialized")
                return None
            
            logger.info(f"Starting upload: {filename} ({file_size} bytes)")
            
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
            
            # Upload file with retry logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    result = self.service.files().create(
                        body=file_metadata,
                        media_body=media,
                        fields='id,name,size,createdTime'
                    ).execute()
                    
                    # Track uploaded file
                    self.uploaded[filename] = {
                        'drive_id': result.get('id'),
                        'uploaded_at': datetime.now().isoformat(),
                        'size': file_size or result.get('size', 0),
                        'drive_created': result.get('createdTime'),
                        'attempt': attempt + 1
                    }
                    self.save_tracker()
                    
                    logger.info(f"Upload successful: {filename} (ID: {result.get('id')})")
                    return result.get('id')
                    
                except Exception as upload_error:
                    logger.warning(f"Upload attempt {attempt + 1} failed for {filename}: {upload_error}")
                    if attempt == max_retries - 1:
                        raise upload_error
                    time.sleep(2 ** attempt)  # Exponential backoff
            
        except Exception as e:
            logger.error(f"Upload failed for {filename}: {e}\n{traceback.format_exc()}")
            return None
    
    def get_health_status(self):
        """Get health status of the Drive uploader"""
        return {
            "authenticated": self.authenticated,
            "service_available": self.service is not None,
            "folder_id": self.folder_id,
            "uploaded_count": len(self.uploaded)
        }

async def download_and_upload_directly():
    """Download videos and upload directly to Google Drive without local storage - Enhanced version"""
    global download_status
    
    download_status.update({
        "running": True,
        "progress": "Initializing...",
        "completed": 0,
        "errors": [],
        "last_error": None,
        "start_time": datetime.now().isoformat()
    })
    
    client = None
    try:
        logger.info("Starting direct download and upload process")
        
        # Validate environment
        env_valid, missing_vars = validate_environment()
        if not env_valid:
            error_msg = f"Missing environment variables: {missing_vars}"
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            logger.error(error_msg)
            return
        
        # Initialize Telegram client with enhanced error handling
        download_status["progress"] = "Connecting to Telegram..."
        logger.info("Initializing Telegram client")
        
        try:
            client = TelegramClient('session', API_ID, API_HASH)
            await client.start(PHONE_NUMBER)
            download_status["progress"] = "Connected to Telegram ✓"
            logger.info("Telegram client connected successfully")
        except SessionPasswordNeededError:
            error_msg = "Two-factor authentication required. Please run locally first to authenticate."
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            logger.error(error_msg)
            return
        except PhoneCodeInvalidError:
            error_msg = "Invalid phone code. Please check your phone number."
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            logger.error(error_msg)
            return
        except Exception as e:
            error_msg = f"Telegram connection failed: {str(e)}"
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return
        
        # Initialize Google Drive with enhanced error handling
        download_status["progress"] = "Connecting to Google Drive..."
        logger.info("Initializing Google Drive uploader")
        
        uploader = DriveUploader()
        if not uploader.authenticate():
            error_msg = "Failed to authenticate with Google Drive"
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            return
        
        if not uploader.create_folder():
            error_msg = "Failed to create/access Google Drive folder"
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            return
        
        download_status["progress"] = "Connected to Google Drive ✓"
        logger.info("Google Drive setup completed")
        
        # Get video messages with enhanced scanning
        download_status["progress"] = f"Scanning {TARGET_CHAT} for videos..."
        logger.info(f"Scanning messages in {TARGET_CHAT}")
        
        video_messages = []
        scan_count = 0
        
        try:
            async for message in client.iter_messages(TARGET_CHAT, limit=1000):  # Limit for safety
                scan_count += 1
                
                if scan_count % 100 == 0:
                    download_status["progress"] = f"Scanned {scan_count} messages..."
                    logger.debug(f"Scanned {scan_count} messages")
                
                if (message.media and 
                    isinstance(message.media, MessageMediaDocument) and 
                    message.media.document and 
                    hasattr(message.media.document, 'attributes') and
                    message.media.document.attributes):
                    
                    for attr in message.media.document.attributes:
                        if isinstance(attr, DocumentAttributeVideo):
                            video_messages.append(message)
                            logger.debug(f"Found video: Message ID {message.id}")
                            break
                            
        except Exception as e:
            error_msg = f"Error scanning messages: {str(e)}"
            download_status["progress"] = error_msg
            download_status["last_error"] = error_msg
            download_status["errors"].append(error_msg)
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            return
        
        download_status["total_videos"] = len(video_messages)
        progress_msg = f"Found {len(video_messages)} videos (scanned {scan_count} messages)"
        download_status["progress"] = progress_msg
        logger.info(progress_msg)
        
        if not video_messages:
            download_status["progress"] = "No videos found in the channel"
            logger.warning("No videos found")
            return
        
        # Process videos - download and upload directly
        logger.info(f"Processing {len(video_messages)} videos")
        
        for i, message in enumerate(video_messages, 1):
            download_status["current"] = i
            
            try:
                filename = get_video_filename(message)
                
                # Skip if already uploaded
                if filename in uploader.uploaded:
                    skip_msg = f"Skipping {filename} (already uploaded)"
                    download_status["progress"] = skip_msg
                    download_status["completed"] += 1
                    logger.info(skip_msg)
                    continue
                
                download_status["progress"] = f"Processing {filename}... ({i}/{len(video_messages)})"
                logger.info(f"Processing video {i}/{len(video_messages)}: {filename}")
                
                # Get file size for progress tracking
                file_size = getattr(message.media.document, 'size', 0)
                
                # Download to memory buffer
                download_status["progress"] = f"Downloading {filename}... ({file_size/1024/1024:.1f} MB)"
                logger.info(f"Downloading {filename} ({file_size} bytes)")
                
                file_buffer = io.BytesIO()
                
                # Download with timeout and error handling
                try:
                    await asyncio.wait_for(
                        client.download_media(message, file=file_buffer), 
                        timeout=300  # 5 minute timeout
                    )
                    file_buffer.seek(0)  # Reset buffer position
                    logger.info(f"Download completed: {filename}")
                except asyncio.TimeoutError:
                    error_msg = f"Download timeout for {filename}"
                    download_status["errors"].append(error_msg)
                    logger.error(error_msg)
                    continue
                except Exception as download_error:
                    error_msg = f"Download error for {filename}: {str(download_error)}"
                    download_status["errors"].append(error_msg)
                    logger.error(error_msg)
                    continue
                
                # Upload directly from buffer
                download_status["progress"] = f"Uploading {filename} to Google Drive..."
                logger.info(f"Uploading {filename}")
                
                drive_id = uploader.upload_stream(file_buffer, filename, file_size)
                
                if drive_id:
                    success_msg = f"✓ Completed: {filename}"
                    download_status["progress"] = success_msg
                    download_status["completed"] += 1
                    logger.info(f"Upload successful: {filename} (Drive ID: {drive_id})")
                else:
                    error_msg = f"✗ Upload failed: {filename}"
                    download_status["progress"] = error_msg
                    download_status["errors"].append(error_msg)
                    logger.error(f"Upload failed: {filename}")
                
                # Clear buffer from memory
                file_buffer.close()
                
                # Small delay to prevent overwhelming the APIs
                await asyncio.sleep(2)
                
            except Exception as e:
                error_msg = f"✗ Error processing {filename if 'filename' in locals() else f'video {i}'}: {str(e)}"
                download_status["progress"] = error_msg
                download_status["errors"].append(error_msg)
                download_status["last_error"] = error_msg
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                continue
        
        # Final status
        final_msg = f"Completed! Processed {download_status['completed']}/{download_status['total_videos']} videos"
        if download_status['errors']:
            final_msg += f" ({len(download_status['errors'])} errors)"
        
        download_status["progress"] = final_msg
        logger.info(final_msg)
    
    except Exception as e:
        error_msg = f"Process error: {str(e)}"
        download_status["progress"] = error_msg
        download_status["last_error"] = error_msg
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
    
    finally:
        download_status["end_time"] = datetime.now().isoformat()
        if client and client.is_connected():
            await client.disconnect()
            logger.info("Telegram client disconnected")
        download_status["running"] = False
        logger.info("Process completed")

def run_direct_process():
    """Run the direct download and upload process with error handling"""
    try:
        logger.info("Starting direct process runner")
        asyncio.run(download_and_upload_directly())
    except Exception as e:
        error_msg = f"Process runner error: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        download_status["running"] = False
        download_status["progress"] = error_msg
        download_status["last_error"] = error_msg

def monitoring_loop(interval_minutes):
    """Enhanced monitoring loop for automatic processing"""
    global monitoring_status
    
    logger.info(f"Starting monitoring loop with {interval_minutes} minute interval")
    
    while monitoring_status["running"]:
        try:
            run_start = datetime.now()
            logger.info(f"[{run_start}] Monitoring: Running auto process...")
            
            monitoring_status["last_run"] = run_start.isoformat()
            
            # Run the process
            run_direct_process()
            
            monitoring_status["runs_completed"] += 1
            run_end = datetime.now()
            
            # Calculate next run time
            next_run = run_end + timedelta(minutes=interval_minutes)
            monitoring_status["next_run"] = next_run.isoformat()
            
            logger.info(f"Monitoring run completed. Next run at {next_run}")
            
            # Wait for the interval
            if monitoring_status["running"]:
                logger.info(f"Monitoring: Sleeping for {interval_minutes} minutes...")
                time.sleep(interval_minutes * 60)
                
        except Exception as e:
            error_msg = f"Monitoring loop error: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            monitoring_status["errors"].append({
                "timestamp": datetime.now().isoformat(),
                "error": error_msg
            })
            # Continue running but wait a bit before retrying
            time.sleep(60)
    
    logger.info("Monitoring loop stopped")

# Enhanced API Endpoints with better error handling

@app.route('/api/status', methods=['GET'])
def api_status():
    """Get comprehensive status information"""
    try:
        return jsonify({
            "download": download_status,
            "monitoring": monitoring_status,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Status API error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def api_health():
    """Enhanced health check endpoint"""
    try:
        # Check environment variables
        env_valid, missing_vars = validate_environment()
        
        # Check file existence
        files_status = {
            "credentials_json": os.path.exists('credentials.json'),
            "service_account_key": os.path.exists('service-account-key.json'),
            "token_json": os.path.exists('token.json'),
            "uploaded_tracker": os.path.exists(UPLOADED_TRACKER)
        }
        
        # Check Google Drive connection
        drive_status = {"connected": False, "folder_exists": False}
        try:
            uploader = DriveUploader()
            if uploader.authenticate():
                drive_status["connected"] = True
                if uploader.create_folder():
                    drive_status["folder_exists"] = True
        except Exception as e:
            logger.warning(f"Drive health check failed: {e}")
        
        return jsonify({
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "environment": {
                "valid": env_valid,
                "missing_vars": missing_vars,
                "api_id_set": bool(API_ID and API_ID != 0),
                "api_hash_set": bool(API_HASH),
                "phone_number_set": bool(PHONE_NUMBER),
                "target_chat_set": bool(TARGET_CHAT)
            },
            "files": files_status,
            "google_drive": drive_status,
            "mode": "direct_upload_enhanced",
            "version": "2.0"
        })
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/api/debug', methods=['GET'])
def api_debug():
    """Debug information endpoint"""
    try:
        uploader = DriveUploader()
        drive_health = uploader.get_health_status()
        
        return jsonify({
            "environment": {
                "API_ID": bool(API_ID and API_ID != 0),
                "API_HASH": bool(API_HASH),
                "PHONE_NUMBER": bool(PHONE_NUMBER),
                "TARGET_CHAT": TARGET_CHAT,
                "PORT": os.environ.get('PORT', 'Not set'),
                "RENDER": bool(os.environ.get('RENDER'))
            },
            "files": {
                "credentials_json": os.path.exists('credentials.json'),
                "service_account_key": os.path.exists('service-account-key.json'),
                "token_json": os.path.exists('token.json'),
                "uploaded_tracker": os.path.exists(UPLOADED_TRACKER)
            },
            "status": {
                "download_running": download_status["running"],
                "monitoring_running": monitoring_status["running"],
                "errors_count": len(download_status["errors"]),
                "last_error": download_status.get("last_error")
            },
            "google_drive": drive_health,
            "stats": {
                "total_uploaded": len(uploader.uploaded),
                "monitoring_runs": monitoring_status.get("runs_completed", 0)
            }
        })
    except Exception as e:
        logger.error(f"Debug API error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/start-process', methods=['POST'])
def api_start_process():
    """Start processing with enhanced error handling"""
    try:
        if download_status["running"]:
            return jsonify({"status": "already_running"})
        
        # Validate environment before starting
        env_valid, missing_vars = validate_environment()
        if not env_valid:
            return jsonify({
                "status": "error", 
                "message": f"Missing environment variables: {missing_vars}"
            }), 400
        
        # Reset status
        download_status.update({
            "errors": [],
            "last_error": None,
            "completed": 0,
            "current": 0,
            "total_videos": 0
        })
        
        thread = threading.Thread(target=run_direct_process)
        thread.daemon = True
        thread.start()
        
        logger.info("Process started via API")
        return jsonify({"status": "started"})
        
    except Exception as e:
        error_msg = f"Failed to start process: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({"status": "error", "message": error_msg}), 500

@app.route('/api/start-monitoring', methods=['POST'])
def api_start_monitoring():
    """Start monitoring with enhanced error handling"""
    try:
        if monitoring_status["running"]:
            return jsonify({"status": "already_running"})
        
        # Validate environment
        env_valid, missing_vars = validate_environment()
        if not env_valid:
            return jsonify({
                "status": "error", 
                "message": f"Missing environment variables: {missing_vars}"
            }), 400
        
        data = request.json or {}
        interval = max(5, min(1440, data.get('interval', 30)))  # Between 5 minutes and 24 hours
        
        monitoring_status.update({
            "interval": interval,
            "running": True,
            "errors": [],
            "runs_completed": 0,
            "last_run": None,
            "next_run": None
        })
        
        thread = threading.Thread(target=monitoring_loop, args=(interval,))
        thread.daemon = True
        thread.start()
        
        logger.info(f"Monitoring started with {interval} minute interval")
        return jsonify({"status": "started", "interval": interval})
        
    except Exception as e:
        error_msg = f"Failed to start monitoring: {str(e)}"
        logger.error(f"{error_msg}\n{traceback.format_exc()}")
        monitoring_status["running"] = False
        return jsonify({"status": "error", "message": error_msg}), 500

@app.route('/api/stop-monitoring', methods=['POST'])
def api_stop_monitoring():
    """Stop monitoring with proper cleanup"""
    try:
        if not monitoring_status["running"]:
            return jsonify({"status": "not_running"})
        
        monitoring_status["running"] = False
        logger.info("Monitoring stopped via API")
        return jsonify({"status": "stopped"})
        
    except Exception as e:
        logger.error(f"Stop monitoring error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/list-uploaded', methods=['GET'])
def api_list_uploaded():
    """List uploaded files with enhanced information"""
    try:
        uploader = DriveUploader()
        uploaded_files = uploader.load_tracker()
        
        # Add summary statistics
        total_size = sum(info.get('size', 0) for info in uploaded_files.values())
        
        return jsonify({
            "files": uploaded_files,
            "summary": {
                "total_files": len(uploaded_files),
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / 1024 / 1024, 2),
                "last_updated": datetime.now().isoformat()
            }
        })
    except Exception as e:
        logger.error(f"List uploaded API error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/clear-errors', methods=['POST'])
def api_clear_errors():
    """Clear error logs"""
    try:
        download_status["errors"] = []
        download_status["last_error"] = None
        monitoring_status["errors"] = []
        logger.info("Error logs cleared")
        return jsonify({"status": "cleared"})
    except Exception as e:
        logger.error(f"Clear errors API error: {e}")
        return jsonify({"error": str(e)}), 500

# Web Interface Endpoints (with error handling)

@app.route('/')
def index():
    """Main web interface"""
    try:
        return HTML_TEMPLATE
    except Exception as e:
        logger.error(f"Index route error: {e}")
        return f"Error loading page: {str(e)}", 500

@app.route('/start-process', methods=['POST'])
def start_process():
    """Legacy endpoint for backward compatibility"""
    return api_start_process()

@app.route('/process_status')
def get_process_status():
    """Legacy endpoint for backward compatibility"""
    return jsonify(download_status)

@app.route('/uploaded-files')
def list_uploaded_files():
    """List uploaded files for web interface"""
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
                'drive_id': info.get('drive_id', ''),
                'attempt': info.get('attempt', 1)
            })
        
        # Sort by upload date (newest first)
        file_list.sort(key=lambda x: x['uploaded_at'], reverse=True)
        
        return jsonify(file_list)
    except Exception as e:
        logger.error(f"List uploaded files error: {e}")
        return jsonify({"error": str(e)}), 500

# Enhanced Error handlers
@app.errorhandler(400)
def bad_request(error):
    logger.warning(f"Bad request: {error}")
    return jsonify({"error": "Bad request", "message": str(error)}), 400

@app.errorhandler(401)
def unauthorized(error):
    logger.warning(f"Unauthorized: {error}")
    return jsonify({"error": "Unauthorized"}), 401

@app.errorhandler(403)
def forbidden(error):
    logger.warning(f"Forbidden: {error}")
    return jsonify({"error": "Forbidden"}), 403

@app.errorhandler(404)
def not_found(error):
    logger.info(f"Not found: {request.url}")
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}\n{traceback.format_exc()}")
    return jsonify({"error": "Internal server error"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}\n{traceback.format_exc()}")
    return jsonify({"error": "An unexpected error occurred"}), 500

# Enhanced HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram to Google Drive - Enhanced</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            max-width: 1200px; margin: 0 auto; padding: 20px; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh; color: #333;
        }
        .container { background: white; border-radius: 15px; padding: 30px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); }
        .header { text-align: center; margin-bottom: 40px; }
        .header h1 { color: #4a5568; margin-bottom: 10px; font-size: 2.5em; }
        .badge { 
            background: linear-gradient(45deg, #28a745, #20c997); 
            color: white; padding: 8px 16px; border-radius: 20px; 
            font-size: 14px; font-weight: 600; 
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.3);
        }
        .section { 
            margin: 30px 0; padding: 25px; border: 2px solid #e2e8f0; 
            border-radius: 12px; background: #f8fafc; 
            transition: all 0.3s ease;
        }
        .section:hover { border-color: #667eea; box-shadow: 0 5px 15px rgba(102, 126, 234, 0.1); }
        .section h2 { color: #2d3748; margin-bottom: 20px; }
        .button { 
            padding: 12px 24px; margin: 8px; background: linear-gradient(45deg, #667eea, #764ba2);
            color: white; border: none; border-radius: 8px; cursor: pointer; 
            font-size: 14px; font-weight: 600; transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
        }
        .button:disabled { 
            background: #cbd5e0; cursor: not-allowed; box-shadow: none;
        }
        .button:hover:not(:disabled) { 
            transform: translateY(-2px); box-shadow: 0 6px 20px rgba(102, 126, 234, 0.4);
        }
        .button.success { background: linear-gradient(45deg, #28a745, #20c997); }
        .button.danger { background: linear-gradient(45deg, #dc3545, #c82333); }
        .button.warning { background: linear-gradient(45deg, #ffc107, #e0a800); color: #333; }
        .status { 
            margin: 15px 0; padding: 18px; background: #fff; 
            border-radius: 8px; border-left: 4px solid #667eea; 
            word-wrap: break-word; box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .progress { margin: 10px 0; font-weight: 600; color: #4a5568; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }
        .stat { 
            text-align: center; padding: 20px; background: white; 
            border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }
        .stat:hover { transform: translateY(-3px); }
        .stat-value { font-size: 2em; font-weight: 700; color: #667eea; }
        .stat-label { color: #718096; font-size: 0.9em; margin-top: 5px; }
        .file-list { 
            max-height: 500px; overflow-y: auto; border: 2px solid #e2e8f0; 
            border-radius: 10px; background: white;
        }
        .file-item { 
            padding: 15px; border-bottom: 1px solid #f0f0f0; 
            display: flex; justify-content: space-between; align-items: center;
            transition: background 0.2s ease;
        }
        .file-item:hover { background: #f8fafc; }
        .file-item:last-child { border-bottom: none; }
        .file-name { font-weight: 600; flex: 1; margin-right: 15px; word-break: break-word; }
        .file-meta { font-size: 12px; color: #718096; text-align: right; }
        .uploaded { color: #28a745; font-weight: 600; }
        .error { color: #e53e3e; background: #fed7d7; border-left-color: #e53e3e; }
        .success { color: #2f855a; background: #c6f6d5; border-left-color: #2f855a; }
        .warning { color: #d69e2e; background: #fefcbf; border-left-color: #d69e2e; }
        .monitoring-controls { 
            display: flex; gap: 15px; align-items: center; flex-wrap: wrap; 
            margin-bottom: 20px;
        }
        .interval-input { 
            padding: 10px; border: 2px solid #e2e8f0; border-radius: 6px; 
            width: 120px; font-size: 14px; transition: border-color 0.3s ease;
        }
        .interval-input:focus { border-color: #667eea; outline: none; }
        .error-section { margin-top: 20px; }
        .error-list { 
            max-height: 200px; overflow-y: auto; background: #fed7d7; 
            border-radius: 8px; padding: 15px;
        }
        .error-item { margin: 8px 0; padding: 8px; background: white; border-radius: 4px; font-size: 13px; }
        .health-indicators { display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }
        .health-indicator { 
            padding: 10px 15px; border-radius: 20px; font-size: 12px; 
            font-weight: 600; text-transform: uppercase;
        }
        .health-ok { background: #c6f6d5; color: #2f855a; }
        .health-error { background: #fed7d7; color: #e53e3e; }
        .health-warning { background: #fefcbf; color: #d69e2e; }
        @media (max-width: 768px) {
            .container { padding: 20px; }
            .stats { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
            .monitoring-controls { flex-direction: column; align-items: stretch; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Telegram to Google Drive</h1>
            <span class="badge">Enhanced Direct Upload v2.0</span>
            <p style="margin-top: 15px; color: #718096;">
                Advanced video processing with CORS support, comprehensive error handling, and monitoring
            </p>
        </div>
        
        <!-- Health Status -->
        <div class="section">
            <h2>System Health</h2>
            <div id="healthIndicators" class="health-indicators">
                <div class="health-indicator health-warning">Checking...</div>
            </div>
            <button class="button warning" onclick="checkHealth()">Refresh Health Check</button>
        </div>
        
        <!-- Process Control -->
        <div class="section">
            <h2>Process Control</h2>
            <button id="processBtn" class="button" onclick="startProcess()">Start Processing</button>
            <div id="processStatus" class="status">Ready to start processing videos</div>
            <div id="processProgress" class="progress"></div>
            
            <div class="stats">
                <div class="stat">
                    <div class="stat-value" id="currentStat">0</div>
                    <div class="stat-label">Current</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="totalStat">0</div>
                    <div class="stat-label">Total Found</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="completedStat">0</div>
                    <div class="stat-label">Completed</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="errorsStat">0</div>
                    <div class="stat-label">Errors</div>
                </div>
            </div>
            
            <!-- Error Section -->
            <div id="errorSection" class="error-section" style="display: none;">
                <h3>Recent Errors</h3>
                <div id="errorList" class="error-list"></div>
                <button class="button warning" onclick="clearErrors()">Clear Errors</button>
            </div>
        </div>
        
        <!-- Auto Monitoring -->
        <div class="section">
            <h2>Auto Monitoring</h2>
            <div class="monitoring-controls">
                <label for="intervalInput">Interval (minutes):</label>
                <input type="number" id="intervalInput" class="interval-input" value="30" min="5" max="1440" placeholder="Minutes">
                <button id="startMonitoringBtn" class="button success" onclick="startMonitoring()">Start Monitoring</button>
                <button id="stopMonitoringBtn" class="button danger" onclick="stopMonitoring()" disabled>Stop Monitoring</button>
            </div>
            <div id="monitoringStatus" class="status">Monitoring is stopped</div>
            <div id="monitoringStats" class="stats" style="display: none;">
                <div class="stat">
                    <div class="stat-value" id="runsStat">0</div>
                    <div class="stat-label">Completed Runs</div>
                </div>
                <div class="stat">
                    <div class="stat-value" id="nextRunStat">-</div>
                    <div class="stat-label">Next Run</div>
                </div>
            </div>
        </div>
        
        <!-- Uploaded Files -->
        <div class="section">
            <h2>Uploaded Files</h2>
            <button class="button" onclick="loadUploadedFiles()">Refresh List</button>
            <button class="button warning" onclick="downloadReport()">Download Report</button>
            <div id="fileList" class="file-list">
                <div style="padding: 20px; text-align: center; color: #718096;">
                    Click "Refresh List" to load uploaded files
                </div>
            </div>
        </div>
    </div>

    <script>
        let statusUpdateInterval = null;
        let monitoringUpdateInterval = null;
        let healthCheckInterval = null;

        function updateElementClass(elementId, text, className = '') {
            const element = document.getElementById(elementId);
            if (element) {
                element.textContent = text;
                element.className = element.className.replace(/\b(error|success|warning)\b/g, '');
                if (className) {
                    element.classList.add(className);
                }
            }
        }

        function checkHealth() {
            fetch('/api/health')
                .then(r => r.json())
                .then(data => {
                    const indicators = document.getElementById('healthIndicators');
                    indicators.innerHTML = '';
                    
                    // Environment check
                    const envClass = data.environment.valid ? 'health-ok' : 'health-error';
                    const envText = data.environment.valid ? 'Environment OK' : 'Environment Issues';
                    indicators.innerHTML += `<div class="health-indicator ${envClass}">${envText}</div>`;
                    
                    // Google Drive check
                    const driveClass = data.google_drive.connected ? 'health-ok' : 'health-error';
                    const driveText = data.google_drive.connected ? 'Google Drive OK' : 'Google Drive Error';
                    indicators.innerHTML += `<div class="health-indicator ${driveClass}">${driveText}</div>`;
                    
                    // Files check
                    const hasAuth = data.files.credentials_json || data.files.service_account_key;
                    const filesClass = hasAuth ? 'health-ok' : 'health-warning';
                    const filesText = hasAuth ? 'Auth Files OK' : 'Auth Files Missing';
                    indicators.innerHTML += `<div class="health-indicator ${filesClass}">${filesText}</div>`;
                })
                .catch(err => {
                    document.getElementById('healthIndicators').innerHTML = 
                        '<div class="health-indicator health-error">Health Check Failed</div>';
                });
        }

        function startProcess() {
            fetch('/api/start-process', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'started') {
                        document.getElementById('processBtn').disabled = true;
                        document.getElementById('processBtn').textContent = 'Processing...';
                        startStatusUpdates();
                    } else if (data.status === 'error') {
                        updateElementClass('processStatus', `Error: ${data.message}`, 'error');
                    } else if (data.status === 'already_running') {
                        updateElementClass('processStatus', 'Process is already running', 'warning');
                    }
                })
                .catch(err => updateElementClass('processStatus', `Error: ${err.message}`, 'error'));
        }

        function startStatusUpdates() {
            if (statusUpdateInterval) clearInterval(statusUpdateInterval);
            
            statusUpdateInterval = setInterval(() => {
                fetch('/api/status')
                    .then(r => r.json())
                    .then(data => {
                        const download = data.download;
                        
                        // Update status
                        const isError = download.progress && (download.progress.includes('Error') || download.progress.includes('Failed'));
                        const isSuccess = download.progress && download.progress.includes('Completed!');
                        
                        let className = '';
                        if (isError) className = 'error';
                        else if (isSuccess) className = 'success';
                        
                        updateElementClass('processStatus', download.progress, className);
                        
                        // Update stats
                        document.getElementById('currentStat').textContent = download.current || 0;
                        document.getElementById('totalStat').textContent = download.total_videos || 0;
                        document.getElementById('completedStat').textContent = download.completed || 0;
                        document.getElementById('errorsStat').textContent = (download.errors || []).length;
                        
                        // Show errors if any
                        if (download.errors && download.errors.length > 0) {
                            document.getElementById('errorSection').style.display = 'block';
                            const errorList = document.getElementById('errorList');
                            errorList.innerHTML = download.errors.slice(-10).map(error => 
                                `<div class="error-item">${error}</div>`
                            ).join('');
                        }
                        
                        // Update progress
                        if (download.total_videos > 0) {
                            const percentage = Math.round((download.completed / download.total_videos) * 100);
                            document.getElementById('processProgress').textContent = 
                                `Progress: ${download.current || 0}/${download.total_videos} (${download.completed || 0} completed, ${percentage}%)`;
                        }
                        
                        // Re-enable button when done
                        if (!download.running) {
                            document.getElementById('processBtn').disabled = false;
                            document.getElementById('processBtn').textContent = 'Start Processing';
                            clearInterval(statusUpdateInterval);
                            loadUploadedFiles(); // Refresh file list
                        }
                    })
                    .catch(err => {
                        updateElementClass('processStatus', `Status update error: ${err.message}`, 'error');
                    });
            }, 2000); // Update every 2 seconds
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
                        document.getElementById('monitoringStats').style.display = 'grid';
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
                    document.getElementById('monitoringStats').style.display = 'none';
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
                        const monitoring = data.monitoring;
                        
                        if (!monitoring.running) {
                            stopMonitoring();
                            return;
                        }
                        
                        const lastRun = monitoring.last_run ? 
                            new Date(monitoring.last_run).toLocaleString() : 'Never';
                        const nextRun = monitoring.next_run ? 
                            new Date(monitoring.next_run).toLocaleTimeString() : 'Calculating...';
                            
                        updateElementClass('monitoringStatus', 
                            `Monitoring active - Interval: ${monitoring.interval}min, Last run: ${lastRun}`, 
                            'success');
                            
                        document.getElementById('runsStat').textContent = monitoring.runs_completed || 0;
                        document.getElementById('nextRunStat').textContent = nextRun;
                    })
                    .catch(err => console.error('Monitoring status error:', err));
            }, 5000); // Update every 5 seconds
        }

        function loadUploadedFiles() {
            fetch('/uploaded-files')
                .then(r => r.json())
                .then(files => {
                    if (files.error) {
                        document.getElementById('fileList').innerHTML = 
                            `<div class="error" style="padding: 20px;">Error: ${files.error}</div>`;
                        return;
                    }
                    
                    if (files.length === 0) {
                        document.getElementById('fileList').innerHTML = 
                            '<div style="padding: 20px; text-align: center; color: #718096;">No files uploaded yet</div>';
                        return;
                    }
                    
                    const fileList = document.getElementById('fileList');
                    fileList.innerHTML = files.map(file => 
                        `<div class="file-item">
                            <div class="file-name">${file.name}</div>
                            <div class="file-meta">
                                ${file.size} • ${new Date(file.uploaded_at).toLocaleString()}
                                ${file.attempt > 1 ? ` • Attempt ${file.attempt}` : ''}
                                <br><span class="uploaded">✓ Uploaded to Drive</span>
                            </div>
                        </div>`
                    ).join('');
                })
                .catch(err => {
                    document.getElementById('fileList').innerHTML = 
                        `<div class="error" style="padding: 20px;">Error loading files: ${err.message}</div>`;
                });
        }

        function clearErrors() {
            fetch('/api/clear-errors', { method: 'POST' })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'cleared') {
                        document.getElementById('errorSection').style.display = 'none';
                        document.getElementById('errorsStat').textContent = '0';
                    }
                })
                .catch(err => console.error('Clear errors failed:', err));
        }

        function downloadReport() {
            fetch('/api/list-uploaded')
                .then(r => r.json())
                .then(data => {
                    const report = {
                        generated_at: new Date().toISOString(),
                        summary: data.summary,
                        files: data.files
                    };
                    
                    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `telegram_drive_report_${new Date().toISOString().split('T')[0]}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                })
                .catch(err => console.error('Download report failed:', err));
        }

        // Initialize page
        document.addEventListener('DOMContentLoaded', function() {
            // Initial health check
            checkHealth();
            
            // Start periodic health checks
            healthCheckInterval = setInterval(checkHealth, 30000); // Every 30 seconds
            
            // Load initial data
            loadUploadedFiles();
            
            // Check if anything is currently running
            fetch('/api/status')
                .then(r => r.json())
                .then(data => {
                    if (data.download && data.download.running) {
                        document.getElementById('processBtn').disabled = true;
                        document.getElementById('processBtn').textContent = 'Processing...';
                        startStatusUpdates();
                    }
                    
                    if (data.monitoring && data.monitoring.running) {
                        document.getElementById('startMonitoringBtn').disabled = true;
                        document.getElementById('stopMonitoringBtn').disabled = false;
                        document.getElementById('monitoringStats').style.display = 'grid';
                        startMonitoringUpdates();
                    }
                })
                .catch(err => console.error('Initial status check failed:', err));
        });

        // Cleanup intervals when page is unloaded
        window.addEventListener('beforeunload', function() {
            if (statusUpdateInterval) clearInterval(statusUpdateInterval);
            if (monitoringUpdateInterval) clearInterval(monitoringUpdateInterval);
            if (healthCheckInterval) clearInterval(healthCheckInterval);
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    # Get port from environment variable (required for Render)
    port = int(os.environ.get('PORT', 5000))
    
    # Print enhanced startup information
    logger.info("🚀 Telegram to Google Drive - Enhanced Direct Upload v2.0")
    logger.info("=" * 60)
    logger.info(f"✅ Server starting on port: {port}")
    logger.info(f"🌐 Local access: http://localhost:{port}")
    logger.info(f"🔗 Network access: http://0.0.0.0:{port}")
    logger.info("=" * 60)
    
    # Environment validation
    env_valid, missing_vars = validate_environment()
    if not env_valid:
        logger.warning(f"⚠️  Missing environment variables: {missing_vars}")
    else:
        logger.info("✅ Environment variables validated")
    
    logger.info("📱 Enhanced Features:")
    logger.info("   • CORS enabled for all origins")
    logger.info("   • Comprehensive error handling and logging")
    logger.info("   • Real-time health monitoring")
    logger.info("   • Enhanced web interface with better UX")
    logger.info("   • Detailed API endpoints with debugging")
    logger.info("   • Automatic retry logic for failed uploads")
    logger.info("   • Memory-efficient direct streaming")
    
    logger.info("=" * 60)
    logger.info("🌟 API Endpoints:")
    logger.info(f"   • Main Interface: http://localhost:{port}/")
    logger.info(f"   • Health Check: http://localhost:{port}/api/health")
    logger.info(f"   • Debug Info: http://localhost:{port}/api/debug")
    logger.info(f"   • Status: http://localhost:{port}/api/status")
    logger.info(f"   • Start Process: POST http://localhost:{port}/api/start-process")
    logger.info(f"   • Start Monitoring: POST http://localhost:{port}/api/start-monitoring")
    logger.info("=" * 60)
    
    # Run with production settings
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_ENV') == 'development',
        threaded=True
    )
