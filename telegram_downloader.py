import asyncio
import os
import re
import time
import io
import tempfile
from threading import Thread
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

CHUNK_SIZE = 1024 * 1024  # 1MB chunks

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

class StreamingBuffer:
    """A streaming buffer that acts like a file object for Google Drive upload"""
    def __init__(self, data_bytes):
        self.data = data_bytes
        self.position = 0
        self.size = len(data_bytes)
    
    def read(self, size=-1):
        """Read data from the buffer"""
        if size == -1:
            # Read all remaining data
            result = self.data[self.position:]
            self.position = self.size
            return result
        else:
            # Read specific amount of data
            result = self.data[self.position:self.position + size]
            self.position += len(result)
            return result
    
    def seek(self, position, whence=0):
        """Seek to position with proper whence support"""        
        if whence == 0:  # os.SEEK_SET
            self.position = max(0, min(position, self.size))
        elif whence == 1:  # os.SEEK_CUR
            self.position = max(0, min(self.position + position, self.size))
        elif whence == 2:  # os.SEEK_END
            self.position = max(0, self.size + position)
        
        return self.position
    
    def tell(self):
        """Get current position"""
        return self.position
    
    def close(self):
        """Close the stream"""
        pass
    
    def flush(self):
        """Flush method for file-like interface"""
        pass
    
    def seekable(self):
        """Return whether object supports seeking"""
        return True
    
    def readable(self):
        """Return whether object supports reading"""
        return True
    
    def writable(self):
        """Return whether object supports writing"""
        return False

async def chunked_download_and_upload(message, filename, drive_uploader, file_size):
    """Download file and upload to drive using in-memory approach"""
    print(f"🔄 Starting download and upload for: {filename}")
    
    download_result = {'success': False, 'error': None, 'data': None}
    upload_result = {'success': False, 'error': None}
    
    async def download_file():
        """Download file to memory using BytesIO"""
        try:
            print("⬇️ Starting download from Telegram...")
            
            # Use BytesIO for in-memory storage
            memory_buffer = io.BytesIO()
            
            download_progress = {'bytes_downloaded': 0, 'start_time': time.time()}
            
            async def progress_callback_download(current, total):
                download_progress['bytes_downloaded'] = current
                percent = (current / total) * 100
                elapsed_time = time.time() - download_progress['start_time']
                if elapsed_time > 0:
                    speed = (current / elapsed_time) / 1024 / 1024  # MB/s
                else:
                    speed = 0
                
                print(f'\rDownload Progress: {percent:.1f}% {current/1024/1024:.1f}/{total/1024/1024:.1f} MB ({speed:.1f} MB/s)', end='', flush=True)
                update_global_progress('downloading', filename, percent, total, current, speed)
            
            # Download to BytesIO buffer
            await client.download_media(
                message, 
                file=memory_buffer,
                progress_callback=progress_callback_download
            )
            
            print(f"\n✅ Download completed for: {filename}")
            download_result['success'] = True
            download_result['data'] = memory_buffer.getvalue()  # Get bytes from BytesIO
            memory_buffer.close()  # Clean up
            
        except Exception as e:
            print(f"\n❌ Download error: {e}")
            download_result['error'] = str(e)
            raise
    
    def upload_file(data_bytes):
        """Upload the downloaded data to Google Drive"""
        try:
            print("⬆️ Starting upload to Google Drive...")
            update_global_progress('uploading', filename)
            
            # Create streaming buffer from downloaded data
            stream_buffer = StreamingBuffer(data_bytes)
            
            result = drive_uploader.upload_file_stream(stream_buffer, filename, len(data_bytes))
            upload_result['success'] = True
            return result
        except Exception as e:
            print(f"❌ Upload error: {e}")
            upload_result['error'] = str(e)
            raise
    
    try:
        # First, download the file completely
        await download_file()
        
        if download_result['success'] and download_result['data']:
            # Then upload the downloaded data
            upload_thread = Thread(target=lambda: upload_file(download_result['data']))
            upload_thread.start()
            upload_thread.join()
            
            if upload_result['success']:
                print(f"✅ Successfully processed: {filename}")
                return True
            else:
                error_msg = upload_result.get('error', 'Upload failed')
                print(f"❌ Upload failed for {filename}: {error_msg}")
                return False
        else:
            error_msg = download_result.get('error', 'Download failed')
            print(f"❌ Download failed for {filename}: {error_msg}")
            return False
            
    except Exception as e:
        print(f"❌ Error processing {filename}: {e}")
        return False

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

def get_file_size(message):
    """Get file size from message"""
    if (hasattr(message.media, 'document') and 
        message.media.document and 
        hasattr(message.media.document, 'size')):
        return message.media.document.size
    return 0

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
        
        # Process videos with download then upload approach
        for i, message in enumerate(video_messages, 1):
            title = get_video_title(message)
            filename = f"{title}.mp4"
            file_size = get_file_size(message)
            
            print(f"\n📹 [{i}/{len(video_messages)}] Checking: {filename}")
            print(f"📏 File size: {file_size / 1024 / 1024:.1f} MB")
            
            if drive_uploader.is_uploaded(filename):
                print(f"⏭️ Skipping: {filename} (already uploaded)")
                continue
            
            print(f"🔄 Processing: {filename}")
            print(f"📝 Title: {title}")
            
            try:
                # Process with download then upload
                success = await chunked_download_and_upload(message, filename, drive_uploader, file_size)
                
                if success:
                    print(f"✅ Successfully processed: {filename}")
                else:
                    print(f"❌ Failed to process: {filename}")
                    
            except Exception as e:
                error_msg = f"Failed to process {filename}: {e}"
                print(f"\n❌ {error_msg}")
                update_global_progress('error', filename, 0, 0, 0, 0)
        
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
