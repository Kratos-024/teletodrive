#!/usr/bin/env python3
"""
Telegram Video Manager Launcher
This script sets up and runs the complete Telegram Video Manager system.
"""

import os
import sys
import subprocess
import webbrowser
import time
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    required_packages = [
        'flask', 'flask_cors', 'telethon',
        'googleapiclient', 'google_auth_oauthlib'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    return missing_packages

def install_dependencies():
    """Install missing dependencies"""
    print("📦 Installing required packages...")
    
    packages = [
        'flask==2.3.3',
        'flask-cors==4.0.0',
        'telethon==1.29.3',
        'google-api-python-client==2.103.0',
        'google-auth-httplib2==0.1.1',
        'google-auth-oauthlib==1.2.2',  # fixed version
        'google-auth==2.23.3'
    ]
    
    try:
        for package in packages:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
        print("✅ All packages installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error installing packages: {e}")
        return False

def check_file_structure():
    """Check if all required files exist"""
    required_files = {
        'app.py': 'Flask server file',
        'telegram_downloader.py': 'Telegram downloader script',
        'drive_uploader.py': 'Google Drive uploader script',
        'templates/index.html': 'Web interface template'
    }
    
    missing_files = []
    
    for file_path, description in required_files.items():
        if not os.path.exists(file_path):
            missing_files.append((file_path, description))
    
    return missing_files

def create_directories():
    """Create necessary directories"""
    directories = ['templates', 'telegram_videos']
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"📁 Created directory: {directory}")

def check_credentials():
    """Check if Google Drive credentials exist"""
    if not os.path.exists('credentials.json'):
        print("\n⚠️  Google Drive API credentials not found!")
        print("\n📋 To set up Google Drive API:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a new project or select existing one")
        print("3. Enable Google Drive API")
        print("4. Go to Credentials > Create Credentials > OAuth 2.0 Client IDs")
        print("5. Choose 'Desktop application'")
        print("6. Download the JSON file and save as 'credentials.json'")
        print("\n⏸️  Continuing without Google Drive integration...")
        return False
    return True

def display_banner():
    """Display startup banner"""
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║    🎬 TELEGRAM VIDEO MANAGER                                ║
║                                                              ║
║    📥 Download videos from Telegram                         ║
║    ☁️  Upload automatically to Google Drive                 ║
║    🔄 Monitor for new videos continuously                   ║
║    🌐 Control everything from web interface                 ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """
    print(banner)

def main():
    """Main launcher function"""
    display_banner()
    
    print("🚀 Starting Telegram Video Manager...")
    print("=" * 60)
    
    # Check dependencies
    print("\n1️⃣  Checking dependencies...")
    missing_deps = check_dependencies()
    
    if missing_deps:
        print(f"❌ Missing packages: {', '.join(missing_deps)}")
        if not install_dependencies():
            print("❌ Failed to install dependencies. Please install manually.")
            return
    else:
        print("✅ All dependencies are installed!")
    
    # Check file structurbe
    print("\n2️⃣  Checking file structure...")
    missing_files = check_file_structure()
    
    if missing_files:
        print("❌ Missing required files:")
        for file_path, description in missing_files:
            print(f"   - {file_path}: {description}")
        
        print("\n📋 Please ensure you have:")
        print("   - Renamed your scripts to 'telegram_downloader.py' and 'drive_uploader.py'")
        print("   - Created the web interface template in 'templates/index.html'")
        print("   - Created the Flask server file 'app.py'")
        return
    else:
        print("✅ All required files found!")
    
    # Create directories
    print("\n3️⃣  Setting up directories...")
    create_directories()
    print("✅ Directory structure ready!")
    
    # Check credentials
    print("\n4️⃣  Checking Google Drive credentials...")
    has_credentials = check_credentials()
    if has_credentials:
        print("✅ Google Drive credentials found!")
    
    # Start the application
    print("\n5️⃣  Starting web server...")
    print("\n🌐 Web interface will be available at: http://localhost:5000")
    print("📱 Your browser should open automatically...")
    print("\n🔥 Server starting in 3 seconds...")
    
    time.sleep(3)
    
    try:
        webbrowser.open('https://teletodrive-y9jp.onrender.com')
        print("\n🎉 Starting Telegram Video Manager!")
        print("🔧 Press Ctrl+C to stop the server")
        print("=" * 60)
        os.system('python app.py')
    except KeyboardInterrupt:
        print("\n\n👋 Telegram Video Manager stopped by user")
    except FileNotFoundError:
        print("\n❌ Error: app.py not found!")
        print("Please make sure the Flask server file exists.")
    except Exception as e:
        print(f"\n❌ Error starting application: {e}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Setup cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
