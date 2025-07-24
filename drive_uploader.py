import os
import json
import io
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/drive.file']
GDRIVE_FOLDER_NAME = 'Telegram Videos'
UPLOADED_TRACKER = 'uploaded_videos.json'

class DriveUploader:
    def __init__(self, progress_callback=None):
        self.service = None
        self.folder_id = None
        self.uploaded = self.load_tracker()
        self.progress_callback = progress_callback
    
    def authenticate(self):
        """Authenticate with Google Drive API with better error handling"""
        print("🔐 Starting Google Drive authentication...")
        
        creds = None
        
        # Check if we have a valid token
        if os.path.exists('token.json'):
            print("📁 Found existing token.json, loading...")
            try:
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
                print("✅ Token loaded successfully")
            except Exception as e:
                print(f"❌ Error loading token: {e}")
                print("🗑️ Removing invalid token.json")
                os.remove('token.json')
                creds = None
        
        # If there are no valid credentials available, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("🔄 Token expired, attempting to refresh...")
                try:
                    creds.refresh(Request())
                    print("✅ Token refreshed successfully")
                except Exception as e:
                    print(f"❌ Error refreshing token: {e}")
                    print("🔄 Need to re-authenticate...")
                    creds = None
            
            if not creds:
                print("🆕 No valid credentials, starting OAuth flow...")
                if not os.path.exists('credentials.json'):
                    raise FileNotFoundError(
                        "❌ credentials.json not found!\n"
                        "Please follow these steps:\n"
                        "1. Go to https://console.cloud.google.com/\n"
                        "2. Create a new project\n"
                        "3. Enable Google Drive API\n"
                        "4. Configure OAuth consent screen\n"
                        "5. Create OAuth 2.0 credentials (Desktop application)\n"
                        "6. Download and save as 'credentials.json'"
                    )
                
                try:
                    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                    print("🌐 Starting local server for authentication...")
                    creds = flow.run_local_server(port=0)
                    print("✅ Authentication completed successfully")
                except Exception as e:
                    raise Exception(f"❌ Authentication failed: {e}")
            
            # Save the credentials for the next run
            print("💾 Saving credentials to token.json")
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
        # Build the service
        try:
            print("🔨 Building Google Drive service...")
            self.service = build('drive', 'v3', credentials=creds)
            
            # Test the service by getting user info
            about = self.service.about().get(fields="user").execute()
            user_email = about.get('user', {}).get('emailAddress', 'Unknown')
            print(f"✅ Google Drive authentication successful for: {user_email}")
            
        except HttpError as e:
            if e.resp.status == 403:
                raise Exception(
                    "❌ Access denied. Please check:\n"
                    "1. Google Drive API is enabled\n"
                    "2. OAuth consent screen is configured\n"
                    "3. Your email is added to test users"
                )
            else:
                raise Exception(f"❌ Google API error: {e}")
        except Exception as e:
            raise Exception(f"❌ Failed to build Drive service: {e}")
    
    def create_folder(self):
        """Create or find the target folder in Google Drive"""
        try:
            print(f"📁 Looking for folder: {GDRIVE_FOLDER_NAME}")
            results = self.service.files().list(
                q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            ).execute()
            
            if results.get('files'):
                self.folder_id = results['files'][0]['id']
                print(f"✅ Found existing folder: {GDRIVE_FOLDER_NAME}")
            else:
                print(f"📁 Creating new folder: {GDRIVE_FOLDER_NAME}")
                folder = self.service.files().create(body={
                    'name': GDRIVE_FOLDER_NAME,
                    'mimeType': 'application/vnd.google-apps.folder'
                }).execute()
                self.folder_id = folder.get('id')
                print(f"✅ Created new folder: {GDRIVE_FOLDER_NAME}")
                
        except Exception as e:
            print(f"❌ Error creating/finding folder: {e}")
            raise
    
    def load_tracker(self):
        """Load the list of already uploaded files"""
        if os.path.exists(UPLOADED_TRACKER):
            try:
                with open(UPLOADED_TRACKER, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Error loading tracker file: {e}")
                return {}
        return {}
    
    def save_tracker(self):
        """Save the list of uploaded files"""
        try:
            with open(UPLOADED_TRACKER, 'w') as f:
                json.dump(self.uploaded, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving tracker file: {e}")
    
    def is_uploaded(self, filename):
        """Check if a file has already been uploaded"""
        return filename in self.uploaded
    
    def upload_file(self, file_path, filename):
        """Upload a single file to Google Drive with progress tracking"""
        try:
            final_filename = self._get_unique_filename(filename)
            file_size = os.path.getsize(file_path)
            
            print(f"📤 Uploading: {final_filename} ({file_size / 1024 / 1024:.1f} MB)")
            
            with open(file_path, 'rb') as file:
                file_content = file.read()
            
            media = MediaIoBaseUpload(
                io.BytesIO(file_content),
                mimetype='video/mp4',
                resumable=True
            )
            
            file_metadata = {
                'name': final_filename,
                'parents': [self.folder_id]
            }
            
            request = self.service.files().create(
                body=file_metadata,
                media_body=media
            )
            
            response = None
            start_time = time.time()
            
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    elapsed_time = time.time() - start_time
                    
                    if elapsed_time > 0:
                        upload_speed = (status.resumable_progress / elapsed_time) / 1024 / 1024  # MB/s
                    else:
                        upload_speed = 0
                    
                    print(f"\rUpload Progress: {progress}% ({upload_speed:.1f} MB/s)", end='', flush=True)
                    
                    # Call progress callback if provided
                    if self.progress_callback:
                        self.progress_callback('uploading', final_filename, progress, file_size, status.resumable_progress, upload_speed)
            
            # Save to tracker
            self.uploaded[filename] = {
                'drive_id': response.get('id'),
                'drive_name': final_filename,
                'upload_date': time.time(),
                'file_size': file_size
            }
            self.save_tracker()
            
            print(f"\n✅ Upload completed: {final_filename}")
            return response.get('id')
            
        except Exception as e:
            print(f"\n❌ Upload failed: {e}")
            raise
    
    def _get_unique_filename(self, filename):
        """Generate unique filename if file already exists in Drive"""
        try:
            results = self.service.files().list(
                q=f"name='{filename}' and parents in '{self.folder_id}' and trashed=false"
            ).execute()
            
            if not results.get('files'):
                return filename
            
            name, ext = os.path.splitext(filename)
            counter = 1
            
            while True:
                new_filename = f"{name} ({counter}){ext}"
                results = self.service.files().list(
                    q=f"name='{new_filename}' and parents in '{self.folder_id}' and trashed=false"
                ).execute()
                
                if not results.get('files'):
                    return new_filename
                counter += 1
                
        except Exception as e:
            print(f"⚠️ Could not check for duplicates: {e}")
            return filename
    
    def get_uploaded_count(self):
        """Get count of uploaded videos"""
        return len(self.uploaded)
    
    def list_uploaded_files(self):
        """List all uploaded files"""
        return list(self.uploaded.keys())
    
    def get_upload_stats(self):
        """Get detailed upload statistics"""
        total_size = sum(file_info.get('file_size', 0) for file_info in self.uploaded.values())
        return {
            'total_files': len(self.uploaded),
            'total_size_mb': total_size / 1024 / 1024,
            'files': self.uploaded
        }
