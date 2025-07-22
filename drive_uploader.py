import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/drive.file']
VIDEOS_FOLDER = 'telegram_videos'
GDRIVE_FOLDER_NAME = 'Telegram Videos'
UPLOADED_TRACKER = 'uploaded_videos.json'

class DriveUploader:
    def __init__(self):
        self.service = None
        self.folder_id = None
        self.uploaded = self.load_tracker()
    
    def authenticate(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        
        self.service = build('drive', 'v3', credentials=creds)
    
    def create_folder(self):
        results = self.service.files().list(
            q=f"name='{GDRIVE_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder'"
        ).execute()
        
        if results.get('files'):
            self.folder_id = results['files'][0]['id']
        else:
            folder = self.service.files().create(body={
                'name': GDRIVE_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }).execute()
            self.folder_id = folder.get('id')
    
    def load_tracker(self):
        if os.path.exists(UPLOADED_TRACKER):
            with open(UPLOADED_TRACKER, 'r') as f:
                return json.load(f)
        return {}
    
    def save_tracker(self):
        with open(UPLOADED_TRACKER, 'w') as f:
            json.dump(self.uploaded, f)
    
    def upload_videos(self):
        video_files = [f for f in os.listdir(VIDEOS_FOLDER) 
                      if f.lower().endswith(('.mp4', '.avi', '.mkv', '.mov'))]
        
        new_videos = [f for f in video_files if f not in self.uploaded]
        
        for filename in new_videos:
            filepath = os.path.join(VIDEOS_FOLDER, filename)
            print(f"Uploading: {filename}")
            
            media = MediaFileUpload(filepath, resumable=True)
            file_metadata = {'name': filename, 'parents': [self.folder_id]}
            
            result = self.service.files().create(
                body=file_metadata, 
                media_body=media
            ).execute()
            
            self.uploaded[filename] = result.get('id')
            self.save_tracker()
            print(f"✓ Uploaded: {filename}")

uploader = DriveUploader()
uploader.authenticate()
uploader.create_folder()
uploader.upload_videos()
