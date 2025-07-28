import os
import json
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
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
<<<<<<< HEAD
        """Authenticate with Google Drive API"""
        print("🔐 Starting Google Drive authentication...")
        creds = None
        
=======
        """Authenticate with Google Drive API, handling credentials.json and token.json for OAuth."""
        print("🔐 Starting Google Drive authentication...")
        creds = None
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        if os.path.exists('token.json'):
            try:
                creds = Credentials.from_authorized_user_file('token.json', SCOPES)
            except Exception as e:
                print(f"❌ Error loading token: {e}")
<<<<<<< HEAD
                if os.path.exists('token.json'):
                    os.remove('token.json')
                creds = None
        
=======
                os.remove('token.json')
                creds = None
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"❌ Error refreshing token: {e}")
                    creds = None
            if not creds:
                if not os.path.exists('credentials.json'):
                    raise FileNotFoundError("❌ credentials.json not found")
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
<<<<<<< HEAD
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
=======
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        self.service = build('drive', 'v3', credentials=creds)
        print("✅ Google Drive authenticated!")

    def create_folder(self):
        """Create or find the target folder in Google Drive"""
        print(f"📁 Checking for Google Drive folder: {GDRIVE_FOLDER_NAME}")
        results = self.service.files().list(
            q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        ).execute()
<<<<<<< HEAD
        
=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        folders = results.get('files', [])
        if folders:
            self.folder_id = folders[0]['id']
            print(f"✅ Using existing folder: {GDRIVE_FOLDER_NAME}")
        else:
            folder = self.service.files().create(body={
                'name': GDRIVE_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }).execute()
            self.folder_id = folder.get('id')
            print(f"✅ Created new folder: {GDRIVE_FOLDER_NAME}")

    def load_tracker(self):
<<<<<<< HEAD
        """Load dict of already uploaded files"""
=======
        """Load dict of already uploaded files (to avoid duplicates)."""
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        if os.path.exists(UPLOADED_TRACKER):
            try:
                with open(UPLOADED_TRACKER, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_tracker(self):
<<<<<<< HEAD
        """Save upload record to disk"""
=======
        """Save upload record to disk."""
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        try:
            with open(UPLOADED_TRACKER, 'w') as f:
                json.dump(self.uploaded, f, indent=2)
        except Exception as e:
            print(f"⚠️ Error saving tracker file: {e}")

    def is_uploaded(self, filename):
<<<<<<< HEAD
        """Check if file was already uploaded"""
        return filename in self.uploaded

    def upload_file(self, file_path, filename):
        """
        Memory-safe upload using MediaFileUpload (streams directly from disk)
        This NEVER loads the full file into memory
        """
        try:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            file_size = os.path.getsize(file_path)
            final_filename = self._get_unique_filename(filename)
            
            print(f"📤 Uploading: {final_filename} ({file_size / 1024 / 1024:.1f} MB)")
            
            # Use MediaFileUpload - this streams directly from disk without loading into RAM
            media = MediaFileUpload(
                file_path,
                mimetype='video/mp4',
                resumable=True,
                chunksize=1024*1024  # 1MB chunks - keeps memory usage minimal
            )
            
=======
        return filename in self.uploaded

    def upload_file(self, file_path, filename):
        """Upload file from local filesystem (recommended for temp file approach)."""
        try:
            file_size = os.path.getsize(file_path)
            final_filename = self._get_unique_filename(filename)
            print(f"📤 Uploading: {final_filename} ({file_size / 1024 / 1024:.1f} MB)")
            with open(file_path, 'rb') as file:
                media = MediaIoBaseUpload(
                    io.BytesIO(file.read()),
                    mimetype='video/mp4',
                    resumable=True
                )
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
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
                    elapsed = max(1e-6, time.time() - start_time)
                    speed = (status.resumable_progress / elapsed) / 1024 / 1024  # MB/s
<<<<<<< HEAD
                    
                    print(f"\rUpload Progress: {progress}% ({speed:.1f} MB/s)", end='', flush=True)
                    
                    if self.progress_callback:
                        self.progress_callback('uploading', final_filename, progress, file_size, status.resumable_progress, speed)
            
            # Save to tracker
=======
                    print(f"\rUpload Progress: {progress}% ({speed:.1f} MB/s)", end='', flush=True)
                    if self.progress_callback:
                        self.progress_callback('uploading', final_filename, progress, file_size, status.resumable_progress, speed)
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
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

<<<<<<< HEAD
    def _get_unique_filename(self, filename):
        """Generate unique filename if file exists"""
        try:
            query = f"name='{filename}' and parents in '{self.folder_id}' and trashed=false"
            results = self.service.files().list(q=query).execute()
            
=======
    def upload_file_stream(self, file_stream, filename, file_size):
        """Upload from any file-like stream (not generally used with tempfiles, but for BytesIO compat)."""
        try:
            final_filename = self._get_unique_filename(filename)
            print(f"📤 Uploading: {final_filename} ({file_size / 1024 / 1024:.1f} MB)")
            media = MediaIoBaseUpload(
                file_stream,
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
                    elapsed = max(1e-6, time.time() - start_time)
                    speed = (status.resumable_progress / elapsed) / 1024 / 1024
                    print(f"\rUpload Progress: {progress}% ({speed:.1f} MB/s)", end='', flush=True)
                    if self.progress_callback:
                        self.progress_callback('uploading', final_filename, progress, file_size, status.resumable_progress, speed)
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
        """Avoid overwriting duplicate files in Drive by appending (x) to name."""
        try:
            query = f"name='{filename}' and parents in '{self.folder_id}' and trashed=false"
            results = self.service.files().list(q=query).execute()
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
            if not results.get('files'):
                return filename
            name, ext = os.path.splitext(filename)
            counter = 1
            while True:
                new_filename = f"{name} ({counter}){ext}"
                query = f"name='{new_filename}' and parents in '{self.folder_id}' and trashed=false"
                results = self.service.files().list(q=query).execute()
<<<<<<< HEAD
                
=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
                if not results.get('files'):
                    return new_filename
                counter += 1
        except Exception as e:
            print(f"⚠️ Could not check for duplicates: {e}")
            return filename

    def get_uploaded_count(self):
        return len(self.uploaded)
<<<<<<< HEAD

=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
    def list_uploaded_files(self):
        return list(self.uploaded.keys())
<<<<<<< HEAD

=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
    def get_upload_stats(self):
        total_size = sum(file_info.get('file_size', 0) for file_info in self.uploaded.values())
        return {
            'total_files': len(self.uploaded),
            'total_size_mb': total_size / 1024 / 1024,
            'files': self.uploaded
        }
