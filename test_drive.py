# test_drive.py
from drive_uploader import DriveUploader

try:
    print("🧪 Testing Google Drive authentication...")
    uploader = DriveUploader()
    uploader.authenticate()
    uploader.create_folder()
    print("✅ All tests passed! Ready to upload.")
except Exception as e:
    print(f"❌ Test failed: {e}")
