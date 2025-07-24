from flask import Flask, jsonify, request
from flask_cors import CORS
import asyncio
import threading
import os
import time
from datetime import datetime
from telegram_downloader import main as telegram_main, current_progress
from drive_uploader import DriveUploader
import json

app = Flask(__name__)

# Simple CORS configuration
CORS(app, origins=["http://localhost:3000","https://teletodrivefronend.vercel.app/", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"])

# Enhanced global variables to track process status
process_status = {
    'running': False,
    'last_error': None,
    'stats': {},
    'start_time': None,
    'end_time': None,
    'current_operation': None,
    'current_file': None,
    'download_progress': 0,
    'upload_progress': 0,
    'total_files': 0,
    'processed_files': 0,
    'downloaded_files': 0,
    'uploaded_files': 0,
    'current_file_size': 0,
    'downloaded_size': 0,
    'upload_speed': 0,
    'download_speed': 0,
    'eta': None
}

def check_credentials():
    """Check if required credential files exist"""
    required_files = ['credentials.json']
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        return False, missing_files
    return True, []

def get_stats():
    """Get upload statistics"""
    try:
        uploader = DriveUploader()
        uploaded_count = uploader.get_uploaded_count()
        uploaded_files = uploader.list_uploaded_files()
        return {
            'total_uploaded': uploaded_count,
            'recently_uploaded': uploaded_files[-5:] if uploaded_files else [],
            'total_files_tracked': len(uploaded_files)
        }
    except Exception as e:
        return {
            'error': f'Could not get stats: {str(e)}',
            'total_uploaded': 0,
            'recently_uploaded': [],
            'total_files_tracked': 0
        }

def sync_progress_from_telegram():
    """Sync progress from telegram_downloader module"""
    global process_status
    try:
        # Import current_progress from telegram_downloader
        from telegram_downloader import current_progress
        
        if current_progress['operation']:
            process_status['current_operation'] = current_progress['operation']
        if current_progress['file_name']:
            process_status['current_file'] = current_progress['file_name']
        if current_progress['progress']:
            if current_progress['operation'] == 'downloading':
                process_status['download_progress'] = current_progress['progress']
            elif current_progress['operation'] == 'uploading':
                process_status['upload_progress'] = current_progress['progress']
        
        process_status['current_file_size'] = current_progress.get('file_size', 0)
        process_status['downloaded_size'] = current_progress.get('downloaded_size', 0)
        process_status['download_speed'] = current_progress.get('speed', 0)
        
    except Exception as e:
        print(f"Error syncing progress: {e}")

async def run_telegram_process():
    """Run the telegram download and upload process"""
    global process_status
    
    try:
        print("🚀 Setting process_status to running...")
        process_status['running'] = True
        process_status['last_error'] = None
        process_status['start_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'initializing'
        
        print("🚀 Starting Telegram to Google Drive Video Uploader")
        print("=" * 50)
        
        # Run the telegram downloader (which includes drive upload)
        print("📞 Calling telegram_main()...")
        await telegram_main()
        
        print("\n" + "=" * 50)
        print("✅ Process completed successfully!")
        
        # Update stats
        process_status['stats'] = get_stats()
        process_status['end_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'completed'
        
    except Exception as e:
        error_msg = f"Error occurred: {str(e)}"
        print(f"\n❌ {error_msg}")
        process_status['last_error'] = error_msg
        process_status['end_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'error'
        raise e
    finally:
        print("🏁 Setting process_status to not running...")
        process_status['running'] = False

def run_async_function():
    """Wrapper to run async function in thread"""
    print("🧵 Starting async function in thread...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_telegram_process())
    except Exception as e:
        print(f"❌ Thread error: {e}")
        process_status['last_error'] = str(e)
        process_status['running'] = False
    finally:
        loop.close()
        print("🧵 Thread completed")

# ROUTE: Home endpoint
@app.route('/', methods=['GET'])
def home():
    """Home endpoint with API information"""
    return jsonify({
        'message': 'Telegram to Google Drive Video Uploader API',
        'version': '2.0',
        'endpoints': {
            '/': 'GET - API information',
            '/status': 'GET - Check process status and stats',
            '/start-upload': 'POST - Start video download and upload process',
            '/stats': 'GET - Get upload statistics',
            '/health': 'GET - Health check',
            '/progress': 'GET - Get detailed progress information'
        },
        'timestamp': datetime.now().isoformat()
    })

# ROUTE: Health check
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    credentials_ok, missing_files = check_credentials()
    
    return jsonify({
        'status': 'success',
        'data': {
            'server_status': 'healthy' if credentials_ok else 'warning',
            'credentials': 'ok' if credentials_ok else f'missing: {missing_files}',
            'process_running': process_status['running'],
            'server_uptime': time.time()
        },
        'timestamp': datetime.now().isoformat()
    })

# ROUTE: Process status
@app.route('/status', methods=['GET'])
def get_status():
    """Get current process status"""
    return jsonify({
        'status': 'success',
        'data': {
            'process_running': process_status['running'],
            'last_error': process_status['last_error'],
            'start_time': process_status.get('start_time'),
            'end_time': process_status.get('end_time'),
            'current_operation': process_status.get('current_operation'),
            'stats': process_status.get('stats', get_stats())
        },
        'timestamp': datetime.now().isoformat()
    })

# ROUTE: Detailed progress
@app.route('/progress', methods=['GET'])
def get_progress():
    """Get detailed progress information"""
    # Sync progress from telegram module
    sync_progress_from_telegram()
    
    return jsonify({
        'status': 'success',
        'data': {
            'running': process_status['running'],
            'current_operation': process_status.get('current_operation'),
            'current_file': process_status.get('current_file'),
            'download_progress': process_status.get('download_progress', 0),
            'upload_progress': process_status.get('upload_progress', 0),
            'total_files': process_status.get('total_files', 0),
            'processed_files': process_status.get('processed_files', 0),
            'downloaded_files': process_status.get('downloaded_files', 0),
            'uploaded_files': process_status.get('uploaded_files', 0),
            'current_file_size': process_status.get('current_file_size', 0),
            'downloaded_size': process_status.get('downloaded_size', 0),
            'download_speed': process_status.get('download_speed', 0),
            'upload_speed': process_status.get('upload_speed', 0),
            'eta': process_status.get('eta'),
            'start_time': process_status.get('start_time'),
            'last_error': process_status.get('last_error')
        },
        'timestamp': datetime.now().isoformat()
    })

# ROUTE: Upload statistics
@app.route('/stats', methods=['GET'])
def get_statistics():
    """Get detailed upload statistics"""
    stats = get_stats()
    return jsonify({
        'status': 'success',
        'data': stats,
        'timestamp': datetime.now().isoformat()
    })

# ROUTE: Start upload process
@app.route('/start-upload', methods=['POST', 'OPTIONS'])
def start_upload():
    """Start the video download and upload process"""
    
    # Handle OPTIONS request
    if request.method == 'OPTIONS':
        print("🔄 Handling OPTIONS request for /start-upload")
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response
    
    print("🎯 POST /start-upload endpoint hit!")
    print(f"📊 Current process_status['running']: {process_status['running']}")
    
    if process_status['running']:
        print("⚠️ Process already running")
        return jsonify({
            'status': 'warning',
            'message': 'Process is already running',
            'current_stats': get_stats(),
            'started_at': process_status.get('start_time')
        }), 409
    
    credentials_ok, missing_files = check_credentials()
    if not credentials_ok:
        print("❌ Missing credentials")
        return jsonify({
            'status': 'error',
            'message': 'Missing required credential files',
            'missing_files': missing_files,
            'help': 'Please ensure you have credentials.json in the project directory'
        }), 400
    
    try:
        print("✅ Starting upload process...")
        initial_stats = get_stats()
        
        # Reset process status
        process_status.update({
            'last_error': None,
            'start_time': None,
            'end_time': None,
            'current_operation': 'starting',
            'current_file': None,
            'download_progress': 0,
            'upload_progress': 0,
            'total_files': 0,
            'processed_files': 0,
            'downloaded_files': 0,
            'uploaded_files': 0,
            'current_file_size': 0,
            'downloaded_size': 0,
            'upload_speed': 0,
            'download_speed': 0,
            'eta': None
        })
        
        print("🧵 Creating and starting background thread...")
        # Start the process in background thread
        thread = threading.Thread(target=run_async_function, daemon=True)
        thread.start()
        print("🧵 Background thread started!")
        
        # Give the thread a moment to start
        time.sleep(0.1)
        
        return jsonify({
            'status': 'success',
            'message': 'Video download and upload process started in background',
            'initial_stats': initial_stats,
            'note': 'Use /progress endpoint to check detailed progress',
            'timestamp': datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        print(f"❌ Error starting process: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Failed to start process: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 500

# ERROR HANDLERS
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'status': 'error',
        'message': 'Endpoint not found',
        'available_endpoints': [
            '/',
            '/health',
            '/status', 
            '/stats',
            '/start-upload',
            '/progress'
        ],
        'timestamp': datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({
        'status': 'error',
        'message': 'Internal server error',
        'error': str(error),
        'timestamp': datetime.now().isoformat()
    }), 500

@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors"""
    return jsonify({
        'status': 'error',
        'message': 'Method not allowed',
        'timestamp': datetime.now().isoformat()
    }), 405

# SERVER STARTUP
if __name__ == '__main__':
    print("🚀 Starting Telegram to Google Drive API Server")
    print("📡 Server will be available at: http://localhost:5000")
    print("📖 API Documentation at: http://localhost:5000/")
    
    credentials_ok, missing_files = check_credentials()
    if not credentials_ok:
        print(f"⚠️  Warning: Missing credential files: {missing_files}")
        print("   Please add credentials.json before starting uploads")
    else:
        print("✅ Credentials found")
    
    try:
        initial_stats = get_stats()
        print(f"📊 Current stats: {initial_stats['total_uploaded']} videos uploaded")
    except Exception as e:
        print(f"⚠️  Could not load initial stats: {e}")
    
    # Print available endpoints
    print("\n📋 Available API Endpoints:")
    print("   GET  /          - API information")
    print("   GET  /health    - Health check")
    print("   GET  /status    - Process status")
    print("   GET  /progress  - Detailed progress")
    print("   GET  /stats     - Upload statistics")
    print("   POST /start-upload - Start upload process")
    
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
