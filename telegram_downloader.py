import asyncio
import os
import re
import tempfile
import time
<<<<<<< HEAD
import gc  # For garbage collection
=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo
from drive_uploader import DriveUploader

API_ID = 27395677
API_HASH = 'b7ee4d7b5b578e5a2ebba4dd0ff84838'
PHONE_NUMBER = '+918512094758'
TARGET_CHAT = 'campusxdsmp1_0'
client = TelegramClient('session', API_ID, API_HASH)

<<<<<<< HEAD
# Simplified global progress tracking
=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
current_progress = {
    'operation': None,
    'file_name': None,
    'progress': 0,
    'file_size': 0,
    'downloaded_size': 0,
    'speed': 0
}

def update_global_progress(operation, file_name=None, progress=0, file_size=0, downloaded_size=0, speed=0):
<<<<<<< HEAD
    """Memory-safe progress tracking"""
=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
    global current_progress
    # Clear previous data to prevent memory accumulation
    current_progress.clear()
    current_progress.update({
        'operation': operation,
        'file_name': file_name,
        'progress': progress,
        'file_size': file_size,
        'downloaded_size': downloaded_size,
        'speed': speed
    })
<<<<<<< HEAD

def sanitize_filename(filename):
    """Clean filename for filesystem"""
=======
    print(f"[{operation}] {file_name} {progress:.1f}% {downloaded_size}/{file_size} bytes {speed:.2f}MB/s")

def sanitize_filename(filename):
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
    filename = re.sub(r'[<>:"/\\|?*]', '', filename)
    filename = re.sub(r'\s+', ' ', filename).strip()
    return filename[:200] if len(filename) > 200 else filename

def get_video_title(message):
<<<<<<< HEAD
    """Extract video title from message"""
=======
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
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
<<<<<<< HEAD
    
    return sanitize_filename(title) if title else f"video_{message.id}"
=======
    if not title:
        title = f"video_{message.id}"
    return sanitize_filename(title)
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63

def get_file_size(message):
    if (hasattr(message.media, 'document') and 
        message.media.document and 
        hasattr(message.media.document, 'size')):
        return message.media.document.size
    return 0

<<<<<<< HEAD
async def process_single_video(message, filename, drive_uploader, file_size):
    """Process one video with memory-safe approach"""
    print(f"🔄 Processing: {filename} ({file_size / 1024 / 1024:.1f} MB)")
    
    # Create temp file in /tmp (Render's ephemeral storage)
    with tempfile.NamedTemporaryFile(suffix='.mp4', dir='/tmp', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        # Download with progress tracking
        start_time = time.time()
        
        def progress_callback_dl(current, total):
            elapsed = max(1e-6, time.time() - start_time)
            percent = (current / total) * 100 if total else 0
            speed = (current / elapsed) / 1024 / 1024  # MB/s
            update_global_progress('downloading', filename, percent, total, current, speed)
            
            # Print progress occasionally to avoid spam
            if int(percent) % 5 == 0:  # Every 5%
                print(f"\rDownload: {percent:.1f}% ({speed:.1f} MB/s)", end='', flush=True)
        
        print("⬇️ Downloading from Telegram...")
        await client.download_media(
            message,
            file=tmp_path,
            progress_callback=progress_callback_dl
        )
        print(f"\n✅ Downloaded: {filename}")
        
        # Force garbage collection after download
        gc.collect()
        
        # Upload using memory-safe method
        print("⬆️ Uploading to Google Drive...")
        update_global_progress('uploading', filename, 0, file_size)
        drive_uploader.upload_file(tmp_path, filename)
        
        print(f"✅ Successfully processed: {filename}")
        return True
        
    except Exception as e:
        print(f"❌ Error processing {filename}: {e}")
        return False
        
    finally:
        # Always clean up temp file
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except:
            pass
        
        # Force garbage collection after each file
        gc.collect()

async def main():
    """Main processing function with memory management"""
    print("🚀 Starting Memory-Safe Telegram → Google Drive Transfer")
    
    try:
        # Initialize services
        drive_uploader = DriveUploader(progress_callback=update_global_progress)
        drive_uploader.authenticate()
        drive_uploader.create_folder()
        
        await client.start(PHONE_NUMBER)
        print("✅ Services initialized")
        
        # Get video messages
        print("📥 Scanning for video messages...")
        video_messages = []
        
=======
async def main():
    print("🚀 Telegram → Google Drive Chunk-safe Transfer Started")
    try:
        drive_uploader = DriveUploader(progress_callback=update_global_progress)
        drive_uploader.authenticate()
        drive_uploader.create_folder()
        await client.start(PHONE_NUMBER)
        print("✅ Telegram client started")

        video_messages = []
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        async for message in client.iter_messages(TARGET_CHAT):
            if (message.media and
                isinstance(message.media, MessageMediaDocument) and
                message.media.document and
                message.media.document.attributes):
                for attr in message.media.document.attributes:
                    if isinstance(attr, DocumentAttributeVideo):
                        video_messages.append(message)
                        break
<<<<<<< HEAD
        
        print(f"✅ Found {len(video_messages)} videos")
        if not video_messages:
            return
        
        # Process videos one by one (never parallel to avoid memory issues)
        success_count = 0
=======

        print(f"✅ Found {len(video_messages)} videos")
        if not video_messages:
            return

>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63
        for i, message in enumerate(video_messages, 1):
            title = get_video_title(message)
            filename = f"{title}.mp4"
            file_size = get_file_size(message)
<<<<<<< HEAD
            
            print(f"\n📹 [{i}/{len(video_messages)}] {filename}")
            
            # Skip if already uploaded
            if drive_uploader.is_uploaded(filename):
                print("⏭️ Already uploaded, skipping")
                continue
            
            # Skip very large files on limited memory instances
            if file_size > 800 * 1024 * 1024:  # 800MB limit for safety
                print(f"⚠️ Skipping large file ({file_size / 1024 / 1024:.1f} MB) to prevent memory issues")
                continue
            
            # Process the video
            success = await process_single_video(message, filename, drive_uploader, file_size)
            if success:
                success_count += 1
        
        print(f"\n🎉 Processing complete! {success_count} videos uploaded.")
        
    except Exception as e:
        print(f"❌ Main error: {e}")
        raise
    finally:
        await client.disconnect()
        # Final cleanup
        gc.collect()
=======
            print(f"\n📹 [{i}/{len(video_messages)}] {filename} | Size: {file_size / 1024 / 1024:.1f} MB")
            if drive_uploader.is_uploaded(filename):
                print(f"⏩ Already uploaded, skipping.")
                continue

            with tempfile.NamedTemporaryFile(suffix='.mp4', dir='/tmp', delete=False) as tmp_file:
                tmp_path = tmp_file.name
            try:
                print("⬇️ Downloading from Telegram to temp file...")
                def progress_callback_dl(current, total):
                    elapsed = max(1e-6, time.time() - start_time)
                    percent = (current / total) * 100 if total else 0
                    speed = (current / elapsed) / 1024 / 1024  # MB/s
                    update_global_progress('downloading', filename, percent, total, current, speed)
                start_time = time.time()
                await client.download_media(
                    message,
                    file=tmp_path,
                    progress_callback=progress_callback_dl
                )
                print("\n⬆️ Uploading to Google Drive from temp file...")
                update_global_progress('uploading', filename, 0, file_size)
                drive_uploader.upload_file(tmp_path, filename)
                print(f"✅ Uploaded and cleaned up: {filename}")

            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        await client.disconnect()
        print("\n🎉 All videos processed!")

    except Exception as e:
        print(f"❌ Error: {e}")
        update_global_progress('error', None, 0, 0, 0, 0)
        raise
>>>>>>> 063ff79229055c0463a88f66f01feb946a08eb63

if __name__ == "__main__":
    asyncio.run(main())
