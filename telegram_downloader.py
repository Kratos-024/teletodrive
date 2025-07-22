import asyncio
import os
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo

# API credentials from https://my.telegram.org
API_ID = 27395677
API_HASH = 'b7ee4d7b5b578e5a2ebba4dd0ff84838'
PHONE_NUMBER = '+918512094758'

# Target channel and download directory
TARGET_CHAT = 'campusxdsmp1_0'
DOWNLOAD_DIR = 'telegram_videos'

client = TelegramClient('session', API_ID, API_HASH)

def progress_callback(current, total):
    percent = (current / total) * 100
    current_mb = current / 1024 / 1024
    total_mb = total / 1024 / 1024
    print(f'\rProgress: {percent:.1f}% {current_mb:.1f}/{total_mb:.1f} MB', end='', flush=True)

async def main():
    await client.start(PHONE_NUMBER)
    
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
    
    print(f"Fetching messages from {TARGET_CHAT}...")
    
    # Get video messages
    video_messages = []
    async for message in client.iter_messages(TARGET_CHAT):
        if (message.media and 
            isinstance(message.media, MessageMediaDocument) and 
            message.media.document and 
            message.media.document.attributes):
            
            for attr in message.media.document.attributes:
                if isinstance(attr, DocumentAttributeVideo):
                    video_messages.append(message)
                    break
    
    print(f"Found {len(video_messages)} videos")
    
    # Download videos
    for i, message in enumerate(video_messages, 1):
        filename = f"video_{message.id}.mp4"
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        
        if os.path.exists(filepath):
            print(f"Skipping {filename} (already exists)")
            continue
        
        print(f"\n[{i}/{len(video_messages)}] Downloading: {filename}")
        
        try:
            await client.download_media(message, file=filepath, progress_callback=progress_callback)
            print(f"\n✓ Downloaded: {filename}")
        except Exception as e:
            print(f"\n✗ Failed to download {filename}: {e}")
    
    await client.disconnect()

asyncio.run(main())
