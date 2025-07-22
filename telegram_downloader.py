import asyncio
import os
from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo
import time

# Replace with your API credentials from https://my.telegram.org
API_ID = 27395677
API_HASH = 'b7ee4d7b5b578e5a2ebba4dd0ff84838'
PHONE_NUMBER = '+918512094758'

# Target channel/chat username or ID
TARGET_CHAT = 'campusxdsmp1_0'  # e.g., 'telegram' or chat ID like -1001234567890

# Download directory
DOWNLOAD_DIR = 'telegram_videos'

client = TelegramClient('session', API_ID, API_HASH)

def progress_callback(current, total):
    """Fixed progress callback that handles float values properly"""
    try:
        # Ensure we have valid numbers
        current = float(current) if current is not None else 0
        total = float(total) if total is not None else 1
        
        if total <= 0:
            return
            
        percent = (current / total) * 100
        bar_length = 40
        filled_length = int(bar_length * current / total)
        bar = '█' * filled_length + '░' * (bar_length - filled_length)
        
        # Convert to MB for display
        current_mb = current / 1024 / 1024
        total_mb = total / 1024 / 1024
        
        print(f'\r|{bar}| {percent:.1f}% {current_mb:.1f}/{total_mb:.1f} MB', end='', flush=True)
        
    except Exception as e:
        # Fallback to simple display if anything goes wrong
        try:
            percent = (float(current) / float(total)) * 100
            print(f'\rProgress: {percent:.1f}%', end='', flush=True)
        except:
            pass

async def main():
    try:
        print("Starting Telegram video downloader...")
        
        # Start the client
        print("Connecting to Telegram...")
        await client.start(PHONE_NUMBER)
        print("Connected successfully!")
        
        # Create download directory
        if not os.path.exists(DOWNLOAD_DIR):
            os.makedirs(DOWNLOAD_DIR)
            print(f"Created directory: {DOWNLOAD_DIR}")
        
        print(f"Fetching messages from {TARGET_CHAT}...")
        
        # Get all messages from the chat
        messages = []
        try:
            message_count = 0
            async for message in client.iter_messages(TARGET_CHAT):
                messages.append(message)
                message_count += 1
                if message_count % 100 == 0:  # Show progress every 100 messages
                    print(f"Fetched {message_count} messages...", end='\r')
            print(f"Found {len(messages)} total messages")
        except ValueError as e:
            if "No user has" in str(e) or "Cannot find any entity" in str(e):
                print(f"Error: Channel '{TARGET_CHAT}' not found or not accessible.")
                print("Make sure:")
                print("1. The channel username is correct")
                print("2. You have access to the channel (joined it)")
                print("3. The channel is public or you're a member")
                return
            else:
                raise e
        except Exception as e:
            print(f"Error fetching messages: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # Filter video messages
        video_messages = []
        print("Scanning for video files...")
        
        for i, message in enumerate(messages):
            try:
                if message.media and isinstance(message.media, MessageMediaDocument):
                    document = message.media.document
                    
                    # Skip empty documents
                    if not document or not hasattr(document, 'attributes'):
                        continue
                    
                    # Check if document has attributes
                    if document.attributes:
                        # Check if it's a video
                        for attr in document.attributes:
                            if isinstance(attr, DocumentAttributeVideo):
                                video_messages.append(message)
                                break
                
                # Show progress
                if (i + 1) % 100 == 0:
                    print(f"Scanned {i + 1}/{len(messages)} messages, found {len(video_messages)} videos", end='\r')
            
            except Exception as e:
                print(f"Error processing message {i}: {e}")
                continue
        
        print(f"\nFound {len(video_messages)} videos to download")
        
        if not video_messages:
            print("No videos found in the chat.")
            print("This could mean:")
            print("1. The channel doesn't have any video files")
            print("2. All media are photos/documents, not videos")
            print("3. You don't have permission to see the media")
            return
        
        # Download each video
        successful_downloads = 0
        failed_downloads = 0
        
        for i, message in enumerate(video_messages, 1):
            try:
                print(f"\nProcessing video {i}/{len(video_messages)}...")
                
                # Validate message and document
                if not message or not message.media:
                    print(f"Skipping video {i}: No media found")
                    failed_downloads += 1
                    continue
                
                document = message.media.document
                if not document:
                    print(f"Skipping video {i}: No document found")
                    failed_downloads += 1
                    continue
                
                # Get video info safely
                video_attr = None
                try:
                    if hasattr(document, 'attributes') and document.attributes:
                        for attr in document.attributes:
                            if isinstance(attr, DocumentAttributeVideo):
                                video_attr = attr
                                break
                except Exception as e:
                    print(f"Warning: Could not read video attributes: {e}")
                
                # Generate filename more safely
                file_extension = '.mp4'  # Default extension
                try:
                    if hasattr(document, 'mime_type') and document.mime_type:
                        mime_type = str(document.mime_type).lower()
                        if 'mp4' in mime_type:
                            file_extension = '.mp4'
                        elif 'avi' in mime_type:
                            file_extension = '.avi'
                        elif 'mkv' in mime_type:
                            file_extension = '.mkv'
                        elif 'mov' in mime_type:
                            file_extension = '.mov'
                        elif 'webm' in mime_type:
                            file_extension = '.webm'
                except Exception as e:
                    print(f"Warning: Could not determine file extension: {e}")
                
                # Create safe filename
                try:
                    timestamp = int(message.date.timestamp()) if message.date else i
                except Exception:
                    timestamp = i
                
                filename = f"video_{message.id}_{timestamp}{file_extension}"
                # Remove any problematic characters from filename
                filename = "".join(c for c in filename if c.isalnum() or c in "._-")
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                
                # Skip if already downloaded
                if os.path.exists(filepath):
                    print(f"Skipping {filename} (already exists)")
                    successful_downloads += 1  # Count as successful since we have it
                    continue
                
                print(f"Downloading: {filename}")
                
                # Show file info safely
                try:
                    if video_attr and hasattr(video_attr, 'duration') and hasattr(document, 'size'):
                        duration_min = int(video_attr.duration) // 60
                        duration_sec = int(video_attr.duration) % 60
                        file_size_mb = float(document.size) / 1024 / 1024
                        print(f"Duration: {duration_min}:{duration_sec:02d}, Size: {file_size_mb:.1f} MB")
                    elif hasattr(document, 'size'):
                        file_size_mb = float(document.size) / 1024 / 1024
                        print(f"Size: {file_size_mb:.1f} MB")
                except Exception as e:
                    print(f"Warning: Could not display file info: {e}")
                
                # Download with progress callback
                print("Starting download...")
                
                try:
                    await client.download_media(
                        message, 
                        file=filepath, 
                        progress_callback=progress_callback
                    )
                    print(f"\n✓ Downloaded: {filename}")
                    successful_downloads += 1
                    
                except Exception as download_error:
                    print(f"✗ Download failed: {str(download_error)}")
                    
                    # Try to get more specific error information
                    error_str = str(download_error)
                    if "Unknown format code 'd' for object of type 'float'" in error_str:
                        print("  → This appears to be a formatting error in telethon library")
                        print("  → Trying alternative download method...")
                        
                        # Try downloading to a temporary path first
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                            try:
                                await client.download_media(message, file=tmp_file.name)
                                # Move the file to final destination
                                import shutil
                                shutil.move(tmp_file.name, filepath)
                                print(f"✓ Downloaded via alternative method: {filename}")
                                successful_downloads += 1
                            except Exception as alt_error:
                                print(f"  → Alternative method also failed: {alt_error}")
                                failed_downloads += 1
                                # Clean up temp file
                                try:
                                    os.unlink(tmp_file.name)
                                except:
                                    pass
                    else:
                        failed_downloads += 1
                        
                        # Handle other specific errors
                        if "FILE_REFERENCE_EXPIRED" in error_str:
                            print("  → File reference expired, try running the script again")
                        elif "FLOOD_WAIT" in error_str:
                            print("  → Rate limited by Telegram, waiting...")
                            try:
                                wait_time = int(''.join(filter(str.isdigit, error_str)))
                                wait_time = max(wait_time, 30)
                                print(f"  → Waiting {wait_time} seconds...")
                                await asyncio.sleep(wait_time)
                            except:
                                await asyncio.sleep(30)
                        elif "MEDIA_EMPTY" in error_str:
                            print("  → Media file is empty or corrupted")
                
                # Add a small delay between downloads
                await asyncio.sleep(1)
                
            except Exception as e:
                print(f"\n✗ Unexpected error processing video {i}: {str(e)}")
                failed_downloads += 1
                import traceback
                traceback.print_exc()
                continue
        
        # Final summary
        print(f"\n" + "="*50)
        print(f"Download Summary:")
        print(f"Total videos found: {len(video_messages)}")
        print(f"Successfully downloaded: {successful_downloads}")
        print(f"Failed downloads: {failed_downloads}")
        print(f"All videos saved to: {DOWNLOAD_DIR}")
        print(f"="*50)
        
    except Exception as e:
        print(f"Critical error in main function: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Make sure client is properly closed
        try:
            if client.is_connected():
                await client.disconnect()
        except:
            pass

if __name__ == '__main__':
    try:
        print("Telegram Video Downloader")
        print("=" * 30)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\nPress Enter to exit...")