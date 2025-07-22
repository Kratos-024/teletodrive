from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import threading
import asyncio
import json
import os
import time
import subprocess
import sys
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Global variables to track status
download_status = {"running": False, "message": "", "progress": ""}
upload_status = {"running": False, "message": "", "progress": ""}
monitoring_status = {"running": False, "message": ""}

# Import your existing modules (make sure they're in the same directory)
try:
    # Import your telegram downloader
    import telegram_downloader  # Your first script renamed as telegram_downloader.py
    # Import your google drive uploader  
    import drive_uploader       # Your second script renamed as drive_uploader.py
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure to rename your scripts to 'telegram_downloader.py' and 'drive_uploader.py'")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """Get current status of all operations"""
    return jsonify({
        "download": download_status,
        "upload": upload_status,
        "monitoring": monitoring_status
    })

@app.route('/api/start-download', methods=['POST'])
def start_download():
    """Start telegram video download"""
    global download_status
    
    if download_status["running"]:
        return jsonify({"error": "Download already running"}), 400
    
    def run_download():
        global download_status
        try:
            download_status["running"] = True
            download_status["message"] = "Starting telegram download..."
            download_status["progress"] = "0%"
            
            # Run the telegram downloader
            asyncio.run(telegram_downloader.main())
            
            download_status["message"] = "Download completed successfully!"
            download_status["progress"] = "100%"
        except Exception as e:
            download_status["message"] = f"Download failed: {str(e)}"
        finally:
            download_status["running"] = False
    
    thread = threading.Thread(target=run_download)
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Download started"})

@app.route('/api/start-upload', methods=['POST'])
def start_upload():
    """Start Google Drive upload once"""
    global upload_status
    
    if upload_status["running"]:
        return jsonify({"error": "Upload already running"}), 400
    
    def run_upload():
        global upload_status
        try:
            upload_status["running"] = True
            upload_status["message"] = "Starting Google Drive upload..."
            upload_status["progress"] = "0%"
            
            # Initialize the uploader
            uploader = drive_uploader.GoogleDriveUploader()
            
            # Authenticate
            if not uploader.authenticate():
                upload_status["message"] = "Authentication failed"
                return
            
            # Create folder
            if not uploader.create_drive_folder():
                upload_status["message"] = "Failed to create/find folder"
                return
            
            # Upload videos
            uploader.scan_and_upload()
            
            upload_status["message"] = "Upload completed successfully!"
            upload_status["progress"] = "100%"
        except Exception as e:
            upload_status["message"] = f"Upload failed: {str(e)}"
        finally:
            upload_status["running"] = False
    
    thread = threading.Thread(target=run_upload)
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Upload started"})

@app.route('/api/start-monitoring', methods=['POST'])
def start_monitoring():
    """Start continuous monitoring"""
    global monitoring_status
    
    if monitoring_status["running"]:
        return jsonify({"error": "Monitoring already running"}), 400
    
    interval = request.json.get('interval', 30) if request.is_json else 30
    
    def run_monitoring():
        global monitoring_status
        try:
            monitoring_status["running"] = True
            monitoring_status["message"] = f"Monitoring started (checking every {interval} minutes)"
            
            uploader = drive_uploader.GoogleDriveUploader()
            
            # Authenticate
            if not uploader.authenticate():
                monitoring_status["message"] = "Authentication failed"
                return
            
            # Create folder
            if not uploader.create_drive_folder():
                monitoring_status["message"] = "Failed to create/find folder"
                return
            
            # Start continuous monitoring
            while monitoring_status["running"]:
                try:
                    monitoring_status["message"] = f"Checking for new videos... ({datetime.now().strftime('%H:%M:%S')})"
                    uploader.scan_and_upload()
                    
                    # Wait for the specified interval
                    for i in range(interval * 60):
                        if not monitoring_status["running"]:
                            break
                        time.sleep(1)
                        
                        # Update countdown
                        remaining = (interval * 60) - i
                        monitoring_status["message"] = f"Next check in {remaining // 60}:{remaining % 60:02d}"
                        
                except Exception as e:
                    monitoring_status["message"] = f"Monitoring error: {str(e)}"
                    time.sleep(60)  # Wait a minute before retrying
                    
        except Exception as e:
            monitoring_status["message"] = f"Monitoring failed: {str(e)}"
        finally:
            monitoring_status["running"] = False
    
    thread = threading.Thread(target=run_monitoring)
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Monitoring started"})

@app.route('/api/stop-monitoring', methods=['POST'])
def stop_monitoring():
    """Stop continuous monitoring"""
    global monitoring_status
    monitoring_status["running"] = False
    monitoring_status["message"] = "Monitoring stopped"
    return jsonify({"message": "Monitoring stopped"})

@app.route('/api/list-uploaded', methods=['GET'])
def list_uploaded():
    """List uploaded videos"""
    try:
        uploader = drive_uploader.GoogleDriveUploader()
        uploaded_videos = uploader.load_uploaded_tracker()
        
        # Format the data for display
        videos = []
        for filename, info in uploaded_videos.items():
            videos.append({
                "filename": filename,
                "size_mb": round(info.get('size', 0) / 1024 / 1024, 1),
                "uploaded_at": info.get('uploaded_at', 'Unknown'),
                "drive_id": info.get('drive_id', 'Unknown')
            })
        
        return jsonify({"videos": videos, "count": len(videos)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/auto-mode', methods=['POST'])
def auto_mode():
    """Start both download and upload in sequence, then monitoring"""
    def run_auto():
        global download_status, upload_status, monitoring_status
        
        try:
            # Step 1: Download videos
            download_status["running"] = True
            download_status["message"] = "Auto mode: Starting download..."
            asyncio.run(telegram_downloader.main())
            download_status["message"] = "Auto mode: Download completed"
            download_status["running"] = False
            
            time.sleep(2)  # Brief pause
            
            # Step 2: Upload videos
            upload_status["running"] = True
            upload_status["message"] = "Auto mode: Starting upload..."
            
            uploader = drive_uploader.GoogleDriveUploader()
            if uploader.authenticate() and uploader.create_drive_folder():
                uploader.scan_and_upload()
                upload_status["message"] = "Auto mode: Upload completed"
            else:
                upload_status["message"] = "Auto mode: Upload failed - authentication/folder error"
            
            upload_status["running"] = False
            
            time.sleep(2)  # Brief pause
            
            # Step 3: Start monitoring
            monitoring_status["running"] = True
            monitoring_status["message"] = "Auto mode: Starting continuous monitoring"
            
            # Continue with monitoring loop
            interval = 30  # 30 minutes default
            while monitoring_status["running"]:
                try:
                    monitoring_status["message"] = f"Auto monitoring: Checking for new videos... ({datetime.now().strftime('%H:%M:%S')})"
                    uploader.scan_and_upload()
                    
                    for i in range(interval * 60):
                        if not monitoring_status["running"]:
                            break
                        time.sleep(1)
                        remaining = (interval * 60) - i
                        monitoring_status["message"] = f"Auto monitoring: Next check in {remaining // 60}:{remaining % 60:02d}"
                        
                except Exception as e:
                    monitoring_status["message"] = f"Auto monitoring error: {str(e)}"
                    time.sleep(60)
                    
        except Exception as e:
            download_status["message"] = f"Auto mode failed: {str(e)}"
            upload_status["message"] = f"Auto mode failed: {str(e)}"
            monitoring_status["message"] = f"Auto mode failed: {str(e)}"
        finally:
            download_status["running"] = False
            upload_status["running"] = False
    
    thread = threading.Thread(target=run_auto)
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Auto mode started: Download → Upload → Monitor"})

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    print("Starting Telegram Video Manager Web Interface...")
    print("Open your browser to: http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)