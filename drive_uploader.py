import os
import json
import time
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import hashlib

# Google Drive API scope
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Configuration
TELEGRAM_VIDEOS_FOLDER = 'telegram_videos'  # Your telegram videos folder
GDRIVE_FOLDER_NAME = 'Telegram Videos'      # Google Drive folder name
UPLOADED_TRACKER = 'uploaded_videos.json'   # File to track uploaded videos
CREDENTIALS_FILE = 'credentials.json'       # Google API credentials file
TOKEN_FILE = 'token.json'                   # OAuth token file

class GoogleDriveUploader:
    def __init__(self):
        self.service = None
        self.gdrive_folder_id = None
        self.uploaded_videos = self.load_uploaded_tracker()
        
    def authenticate(self):
        """Authenticate with Google Drive API"""
        creds = None
        
        # Load existing token
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        
        # If there are no (valid) credentials available, let the user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    print(f"Error refreshing token: {e}")
                    creds = None
            
            if not creds:
                if not os.path.exists(CREDENTIALS_FILE):
                    print(f"\nError: {CREDENTIALS_FILE} not found!")
                    print("\nTo set up Google Drive API:")
                    print("1. Go to https://console.cloud.google.com/")
                    print("2. Create a new project or select existing one")
                    print("3. Enable Google Drive API")
                    print("4. Go to Credentials > Create Credentials > OAuth 2.0 Client IDs")
                    print("5. Choose 'Desktop application'")
                    print("6. Download the JSON file and save as 'credentials.json'")
                    return False
                
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
        
        self.service = build('drive', 'v3', credentials=creds)
        print("✓ Successfully authenticated with Google Drive")
        return True
    
    def get_file_hash(self, filepath):
        """Generate MD5 hash of file for duplicate detection"""
        hash_md5 = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"Error generating hash for {filepath}: {e}")
            return None
    
    def create_drive_folder(self):
        """Create or find the Google Drive folder"""
        try:
            # Search for existing folder
            results = self.service.files().list(
                q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                spaces='drive'
            ).execute()
            
            items = results.get('files', [])
            
            if items:
                self.gdrive_folder_id = items[0]['id']
                print(f"✓ Found existing folder: {GDRIVE_FOLDER_NAME}")
            else:
                # Create new folder
                folder_metadata = {
                    'name': GDRIVE_FOLDER_NAME,
                    'mimeType': 'application/vnd.google-apps.folder'
                }
                
                folder = self.service.files().create(
                    body=folder_metadata,
                    fields='id'
                ).execute()
                
                self.gdrive_folder_id = folder.get('id')
                print(f"✓ Created new folder: {GDRIVE_FOLDER_NAME}")
            
            return True
            
        except Exception as e:
            print(f"Error creating/finding folder: {e}")
            return False
    
    def load_uploaded_tracker(self):
        """Load the list of already uploaded videos"""
        if os.path.exists(UPLOADED_TRACKER):
            try:
                with open(UPLOADED_TRACKER, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading upload tracker: {e}")
        return {}
    
    def save_uploaded_tracker(self):
        """Save the list of uploaded videos"""
        try:
            with open(UPLOADED_TRACKER, 'w') as f:
                json.dump(self.uploaded_videos, f, indent=2)
        except Exception as e:
            print(f"Error saving upload tracker: {e}")
    
    def upload_file(self, filepath, filename):
        """Upload a single file to Google Drive"""
        try:
            print(f"Uploading: {filename}")
            
            # Get file size for progress
            file_size = os.path.getsize(filepath)
            print(f"File size: {file_size / 1024 / 1024:.1f} MB")
            
            # Prepare metadata
            file_metadata = {
                'name': filename,
                'parents': [self.gdrive_folder_id]
            }
            
            # Create media upload object
            media = MediaFileUpload(
                filepath,
                resumable=True,
                chunksize=1024 * 1024  # 1MB chunks
            )
            
            # Upload file
            request = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,size'
            )
            
            response = None
            while response is None:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        print(f"\rUpload progress: {progress}%", end='', flush=True)
                except Exception as e:
                    print(f"\nUpload error: {e}")
                    return False
            
            print(f"\n✓ Successfully uploaded: {filename}")
            print(f"  Google Drive ID: {response.get('id')}")
            
            return response.get('id')
            
        except Exception as e:
            print(f"✗ Upload failed for {filename}: {e}")
            return False
    
    def scan_and_upload(self):
        """Scan for new videos and upload them"""
        if not os.path.exists(TELEGRAM_VIDEOS_FOLDER):
            print(f"Error: Folder '{TELEGRAM_VIDEOS_FOLDER}' not found!")
            return
        
        # Get all video files
        video_extensions = ('.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv')
        video_files = []
        
        for file in os.listdir(TELEGRAM_VIDEOS_FOLDER):
            if file.lower().endswith(video_extensions):
                filepath = os.path.join(TELEGRAM_VIDEOS_FOLDER, file)
                if os.path.isfile(filepath):
                    video_files.append((filepath, file))
        
        if not video_files:
            print("No video files found in telegram_videos folder")
            return
        
        print(f"Found {len(video_files)} video files")
        
        new_videos = []
        updated_videos = []
        
        # Check which videos are new or updated
        for filepath, filename in video_files:
            file_hash = self.get_file_hash(filepath)
            file_size = os.path.getsize(filepath)
            
            # Check if this file has been uploaded before
            if filename in self.uploaded_videos:
                stored_info = self.uploaded_videos[filename]
                
                # Check if file has changed (different hash or size)
                if (stored_info.get('hash') != file_hash or 
                    stored_info.get('size') != file_size):
                    updated_videos.append((filepath, filename, file_hash, file_size))
                else:
                    print(f"Skipping {filename} (already uploaded)")
            else:
                new_videos.append((filepath, filename, file_hash, file_size))
        
        total_to_upload = len(new_videos) + len(updated_videos)
        
        if total_to_upload == 0:
            print("All videos are already uploaded to Google Drive")
            return
        
        print(f"\nFound {len(new_videos)} new videos and {len(updated_videos)} updated videos")
        print(f"Total files to upload: {total_to_upload}")
        
        # Upload new and updated videos
        successful_uploads = 0
        failed_uploads = 0
        
        all_videos_to_upload = new_videos + updated_videos
        
        for i, (filepath, filename, file_hash, file_size) in enumerate(all_videos_to_upload, 1):
            try:
                print(f"\n[{i}/{total_to_upload}] Processing: {filename}")
                
                # Upload the file
                drive_file_id = self.upload_file(filepath, filename)
                
                if drive_file_id:
                    # Update tracking info
                    self.uploaded_videos[filename] = {
                        'drive_id': drive_file_id,
                        'hash': file_hash,
                        'size': file_size,
                        'uploaded_at': datetime.now().isoformat(),
                        'local_path': filepath
                    }
                    
                    successful_uploads += 1
                    
                    # Save progress after each successful upload
                    self.save_uploaded_tracker()
                else:
                    failed_uploads += 1
                
                # Small delay between uploads
                time.sleep(2)
                
            except Exception as e:
                print(f"Error processing {filename}: {e}")
                failed_uploads += 1
                continue
        
        # Final summary
        print(f"\n" + "="*50)
        print(f"Upload Summary:")
        print(f"Total videos processed: {total_to_upload}")
        print(f"Successfully uploaded: {successful_uploads}")
        print(f"Failed uploads: {failed_uploads}")
        print(f"Google Drive folder: {GDRIVE_FOLDER_NAME}")
        print(f"="*50)
    
    def list_uploaded_videos(self):
        """List all uploaded videos"""
        if not self.uploaded_videos:
            print("No videos have been uploaded yet")
            return
        
        print(f"\nUploaded Videos ({len(self.uploaded_videos)} total):")
        print("-" * 60)
        
        for filename, info in self.uploaded_videos.items():
            upload_date = info.get('uploaded_at', 'Unknown')
            size_mb = info.get('size', 0) / 1024 / 1024
            print(f"📹 {filename}")
            print(f"   Size: {size_mb:.1f} MB")
            print(f"   Uploaded: {upload_date}")
            print(f"   Drive ID: {info.get('drive_id', 'Unknown')}")
            print()
    
    def run_continuous_monitor(self, interval_minutes=30):
        """Continuously monitor for new videos"""
        print(f"Starting continuous monitoring (checking every {interval_minutes} minutes)")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new videos...")
                self.scan_and_upload()
                
                print(f"Waiting {interval_minutes} minutes before next check...")
                time.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")

def main():
    print("Google Drive Auto Uploader for Telegram Videos")
    print("=" * 50)
    
    uploader = GoogleDriveUploader()
    
    # Authenticate with Google Drive
    if not uploader.authenticate():
        return
    
    # Create/find the upload folder
    if not uploader.create_drive_folder():
        return
    
    while True:
        print("\nChoose an option:")
        print("1. Upload new videos once")
        print("2. Start continuous monitoring")
        print("3. List uploaded videos")
        print("4. Exit")
        
        try:
            choice = input("\nEnter choice (1-4): ").strip()
            
            if choice == '1':
                uploader.scan_and_upload()
            
            elif choice == '2':
                interval = input("Enter check interval in minutes (default: 30): ").strip()
                try:
                    interval = int(interval) if interval else 30
                except ValueError:
                    interval = 30
                uploader.run_continuous_monitor(interval)
            
            elif choice == '3':
                uploader.list_uploaded_videos()
            
            elif choice == '4':
                print("Goodbye!")
                break
            
            else:
                print("Invalid choice. Please enter 1, 2, 3, or 4.")
                
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    main()