import asyncio
import sys
from telegram_downloader import main as telegram_main
from drive_uploader import DriveUploader


def check_credentials():
    """Check if required credential files exist"""
    import os
    
    required_files = ['credentials.json']
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print("❌ Missing required files:")
        for file in missing_files:
            print(f"   - {file}")
        print("\nPlease ensure you have:")
        print("   - credentials.json (Google Drive API credentials)")
        print("   - Setup instructions: https://developers.google.com/drive/api/quickstart/python")
        return False
    
    return True


def show_stats():
    """Show upload statistics"""
    uploader = DriveUploader()
    if uploader.load_tracker():
        print(f"\n📊 Statistics:")
        print(f"   Total uploaded videos: {uploader.get_uploaded_count()}")
    else:
        print("\n📊 No videos uploaded yet")


async def main():
    """Main function to run the telegram downloader"""
    print("🚀 Starting Telegram to Google Drive Video Uploader")
    print("=" * 50)
    
    # Check credentials
    if not check_credentials():
        return
    
    try:
        # Show current stats
        show_stats()
        
        print("\n🔄 Starting download and upload process...")
        
        # Run the telegram downloader (which includes drive upload)
        await telegram_main()
        
        # Show final stats
        print("\n" + "=" * 50)
        show_stats()
        print("✅ Process completed successfully!")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Process interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
