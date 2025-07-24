import asyncio
import os
import re
import tempfile
import time
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo
from drive_uploader import DriveUploader

# API credentials from https://my.telegram.org
API_ID = 27395677
API_HASH = 'b7ee4d7b5b578e5a2ebba4dd0ff84838'
PHONE_NUMBER = '+918512094758'

# Target channel
TARGET_CHAT = 'campusxdsmp1_0'

client = TelegramClient('session', API_ID, API_HASH)

# Global progress tracking
current_progress = {
    'operation': None,
    'file_name': None,
    'progress': 0,
    'file_size': 0,
    'downloaded_size': 0,
    'speed': 0
}

def update_global_progress(operation, file_name=None, progress=0, file_size=0, downloaded_size=0, speed=0):
    """Update global progress that can be accessed by Flask"""
    global current_progress
    current_progress.update({
        'operation': operation,
        'file_name': file_name,
        'progress': progress,
        'file_size': file_size,
        'downloaded_size': downloaded_size,
        'speed': speed
    })
    print(f"📊 Progress updated: {operation} - {progress:.1f}%")

def progress_callback(current, total):
    start_time = getattr(progress_callback, 'start_time', time.time())
    if not hasattr(progress_callback, 'start_time'):
        progress_callback.start_time = start_time
    
    percent = (current / total) * 100
    current_mb = current / 1024 / 1024
    total_mb = total / 1024 / 1024
    
    elapsed_time = time.time() - start_time
    if elapsed_time > 0:
        speed = (current / elapsed_time) / 1024 / 1024  # MB/s
    else:
        speed = 0
    
    print(f'\rDownload Progress: {percent:.1f}% {current_mb:.1f}/{total_mb:.1f} MB ({speed:.1f} MB/s)', end='', flush=True)
    
    # Update global progress
    update_global_progress('downloading', None, percent, total, current, speed)

def sanitize_filename(filename):
    """Remove or replace invalid characters for filename"""
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', ' ', filename)
    filename = filename.strip()
    if len(filename) > 200:
        filename = filename[:200]
    return filename

def get_video_title(message):
    """Extract title from message text or use fallback"""
    title = ""
    
    if message.text:
        lines = message.text.strip().split('\n')
        if lines:
            title = lines[0].strip()
    
    if not title or len(title) < 3:
        if (hasattr(message.media, 'document') and 
            message.media.document and 
            hasattr(message.media.document, 'attributes')):
            
            for attr in message.media.document.attributes:
                if hasattr(attr, 'file_name') and attr.file_name:
                    title = os.path.splitext(attr.file_name)[0]
                    break
    
    if not title:
        title = f"video_{message.id}"
    
    return sanitize_filename(title)

async def main():
    print("🚀 telegram_main() called - Starting process...")
    
    try:
        # Initialize Drive uploader with progress callback
        print("📂 Initializing Drive uploader...")
        drive_uploader = DriveUploader(progress_callback=update_global_progress)
        drive_uploader.authenticate()
        drive_uploader.create_folder()
        print("✅ Drive uploader initialized")
        
        print("📱 Starting Telegram client...")
        await client.start(PHONE_NUMBER)
        print("✅ Telegram client started")
        
        print(f"📥 Fetching messages from {TARGET_CHAT}...")
        update_global_progress('fetching_messages', None, 0)
        
        # Get video messages
        video_messages = []
        message_count = 0
        async for message in client.iter_messages(TARGET_CHAT):
            message_count += 1
            if message_count % 100 == 0:
                print(f"📥 Scanned {message_count} messages...")
                
            if (message.media and 
                isinstance(message.media, MessageMediaDocument) and 
                message.media.document and 
                message.media.document.attributes):
                
                for attr in message.media.document.attributes:
                    if isinstance(attr, DocumentAttributeVideo):
                        video_messages.append(message)
                        break
        
        print(f"✅ Found {len(video_messages)} videos from {message_count} total messages")
        
        # Update total files count
        update_global_progress('initializing', None, 0, len(video_messages))
        
        if len(video_messages) == 0:
            print("⚠️ No video messages found!")
            return
        
        # Process videos
        for i, message in enumerate(video_messages, 1):
            title = get_video_title(message)
            filename = f"{title}.mp4"
            
            print(f"\n📹 [{i}/{len(video_messages)}] Checking: {filename}")
            
            if drive_uploader.is_uploaded(filename):
                print(f"⏭️ Skipping: {filename} (already uploaded)")
                continue
            
            print(f"🔄 Processing: {filename}")
            print(f"📝 Title: {title}")
            
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
                temp_filepath = temp_file.name
            
            try:
                # Reset progress callback timer
                if hasattr(progress_callback, 'start_time'):
                    del progress_callback.start_time
                
                # Update current file being processed
                update_global_progress('downloading', filename)
                
                print("⬇️ Downloading from Telegram...")
                await client.download_media(message, file=temp_filepath, progress_callback=progress_callback)
                print(f"\n✅ Downloaded to temporary file")
                
                print("⬆️ Uploading to Google Drive...")
                update_global_progress('uploading', filename)
                drive_uploader.upload_file(temp_filepath, filename)
                print(f"✅ Uploaded to Drive: {filename}")
                
            except Exception as e:
                error_msg = f"Failed to process {filename}: {e}"
                print(f"\n❌ {error_msg}")
                update_global_progress('error', filename, 0, 0, 0, 0)
            finally:
                if os.path.exists(temp_filepath):
                    os.unlink(temp_filepath)
        
        await client.disconnect()
        print("\n🎉 All videos processed!")
        update_global_progress('completed', None, 100)
        
    except Exception as e:
        error_msg = f"Error in telegram_main: {str(e)}"
        print(f"❌ {error_msg}")
        update_global_progress('error', None, 0, 0, 0, 0)
        raise e

if __name__ == "__main__":
    asyncio.run(main())
