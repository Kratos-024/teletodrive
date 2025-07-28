import os
os.environ['PYTHONUNBUFFERED'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
from flask import Flask, jsonify, request, make_response
from flask_cors import CORS
import asyncio
import threading
import os
import time
from datetime import datetime
from telegram_downloader import main as telegram_main, current_progress
from drive_uploader import DriveUploader
import json
import traceback


app = Flask(__name__)


# ============================================================================
# COMPREHENSIVE CORS CONFIGURATION
# ============================================================================

CORS(app, 
     # Allow specific origins (adjust based on your deployment)
      origins="*",
     # Allow all common HTTP methods
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH'],
     # Allow all common headers
     allow_headers=[
         'Content-Type',
         'Authorization',
         'Accept',
         'Origin',
         'X-Requested-With',
         'Cache-Control',
         'Access-Control-Request-Method',
         'Access-Control-Request-Headers'
     ],
     # Support credentials if needed (set to False if not needed)
     supports_credentials=False,
     # Cache preflight requests for 1 hour
     max_age=3600
)


# ============================================================================
# GLOBAL PREFLIGHT HANDLER (Fallback for any missed OPTIONS requests)
# ============================================================================
@app.before_request
def handle_preflight():
    """Handle preflight OPTIONS requests globally"""
    if request.method == "OPTIONS":
        print(f"🔄 Global OPTIONS handler for: {request.path}")
        print(f"🌐 Origin: {request.headers.get('Origin', 'No origin')}")
        print(f"📋 Headers: {dict(request.headers)}")
        
        response = make_response()
        
        # Set CORS headers explicitly
        origin = request.headers.get('Origin')
        allowed_origins = [
            "http://localhost:3000",
            "http://localhost:5173", 
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "https://localhost:3000",
            "https://localhost:5173",
            "https://your-frontend-domain.com"
        ]
        
        if origin in allowed_origins:
            response.headers['Access-Control-Allow-Origin'] = origin
            print(f"✅ Allowed origin: {origin}")
        else:
            response.headers['Access-Control-Allow-Origin'] = '*'
            print(f"⚠️ Using wildcard for origin: {origin}")
            
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin, X-Requested-With, Cache-Control'
        response.headers['Access-Control-Max-Age'] = '3600'
        response.headers['Access-Control-Allow-Credentials'] = 'false'
        
        print("✅ Preflight response headers set")
        return response


# ============================================================================
# RESPONSE HEADERS MIDDLEWARE (Ensure CORS headers on all responses)
# ============================================================================
@app.after_request
def after_request(response):
    """Add CORS headers to all responses"""
    origin = request.headers.get('Origin')
    allowed_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000", 
        "http://127.0.0.1:5173",
        "https://localhost:3000",
        "https://localhost:5173",
        "https://your-frontend-domain.com"
    ]
    
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
    elif not response.headers.get('Access-Control-Allow-Origin'):
        response.headers['Access-Control-Allow-Origin'] = '*'
    
    # Ensure other CORS headers are present
    if not response.headers.get('Access-Control-Allow-Methods'):
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH'
    if not response.headers.get('Access-Control-Allow-Headers'):
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin, X-Requested-With, Cache-Control'
    
    # Add security headers
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    
    return response


# ============================================================================
# ENHANCED ERROR HANDLING FUNCTIONS
# ============================================================================
def create_error_response(error_type, message, details, status_code=500, suggestions=None):
    """Create a standardized error response matching frontend expectations"""
    if suggestions is None:
        suggestions = []
    
    error_response = {
        'status': 'error',
        'error': {
            'type': error_type,
            'message': message,
            'details': details,
            'status': status_code,
            'timestamp': datetime.now().isoformat(),
            'suggestions': suggestions
        },
        'timestamp': datetime.now().isoformat()
    }
    
    # Log detailed error information
    print(f"❌ API Error ({error_type.upper()}): {message}")
    print(f"🔍 Details: {details}")
    if suggestions:
        print("💡 Suggestions:")
        for i, suggestion in enumerate(suggestions, 1):
            print(f"   {i}. {suggestion}")
    
    return jsonify(error_response), status_code


def log_request_info():
    """Log detailed request information for debugging"""
    print(f"🌐 Request: {request.method} {request.path}")
    print(f"📡 Origin: {request.headers.get('Origin', 'No origin')}")
    print(f"🔍 User-Agent: {request.headers.get('User-Agent', 'No user agent')}")
    print(f"📋 Content-Type: {request.headers.get('Content-Type', 'No content type')}")
    if request.args:
        print(f"🔗 Query params: {dict(request.args)}")


# Enhanced global variables to track process status with chunked streaming support
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
    'uploaded_size': 0,  # New field for chunked uploads
    'upload_speed': 0,
    'download_speed': 0,
    'eta': None,
    'streaming_active': False,  # New field to track streaming status
    'memory_usage': 0,  # New field to track memory usage
    'chunk_queue_size': 0,  # New field to track chunk queue size
    'simultaneous_operations': False  # New field to track if download/upload are happening simultaneously
}


def check_credentials():
    """Check if required credential files exist"""
    try:
        required_files = ['credentials.json']
        missing_files = [f for f in required_files if not os.path.exists(f)]
        
        if missing_files:
            print(f"⚠️ Missing credential files: {missing_files}")
            return False, missing_files
        
        # Additional validation - check if credentials.json is valid JSON
        try:
            with open('credentials.json', 'r') as f:
                json.load(f)
            print("✅ Credentials file validated")
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in credentials.json: {e}")
            return False, ['credentials.json (invalid JSON)']
            
        return True, []
    except Exception as e:
        print(f"❌ Error checking credentials: {e}")
        return False, [f'Error checking files: {str(e)}']


def get_stats():
    """Get upload statistics with enhanced error handling"""
    try:
        print("📊 Getting upload statistics...")
        uploader = DriveUploader()
        stats_data = uploader.get_upload_stats()
        
        stats = {
            'total_uploaded': stats_data.get('total_files', 0),
            'total_size_mb': stats_data.get('total_size_mb', 0),
            'recently_uploaded': list(stats_data.get('files', {}).keys())[-5:] if stats_data.get('files') else [],
            'total_files_tracked': len(stats_data.get('files', {})),
            'files_detail': stats_data.get('files', {})
        }
        print(f"✅ Stats retrieved: {stats['total_uploaded']} files uploaded ({stats['total_size_mb']:.1f} MB)")
        return stats
        
    except ImportError as e:
        error_msg = f'DriveUploader module not available: {str(e)}'
        print(f"❌ Import error: {error_msg}")
        return {
            'error': error_msg,
            'total_uploaded': 0,
            'total_size_mb': 0,
            'recently_uploaded': [],
            'total_files_tracked': 0,
            'files_detail': {}
        }
    except Exception as e:
        error_msg = f'Could not get stats: {str(e)}'
        print(f"❌ Stats error: {error_msg}")
        print(f"📋 Traceback: {traceback.format_exc()}")
        return {
            'error': error_msg,
            'total_uploaded': 0,
            'total_size_mb': 0,
            'recently_uploaded': [],
            'total_files_tracked': 0,
            'files_detail': {}
        }


def sync_progress_from_telegram():
    """Sync progress from telegram_downloader module with enhanced error handling for chunked operations"""
    global process_status
    try:
        # Import current_progress from telegram_downloader
        from telegram_downloader import current_progress
        
        # Update process status with current progress
        if current_progress.get('operation'):
            process_status['current_operation'] = current_progress['operation']
            
            # Special handling for chunked operations
            if current_progress['operation'] in ['downloading', 'uploading']:
                process_status['streaming_active'] = True
                process_status['simultaneous_operations'] = True
            elif current_progress['operation'] in ['completed', 'error']:
                process_status['streaming_active'] = False
                process_status['simultaneous_operations'] = False
            
        if current_progress.get('file_name'):
            process_status['current_file'] = current_progress['file_name']
            
        if current_progress.get('progress') is not None:
            if current_progress['operation'] == 'downloading':
                process_status['download_progress'] = current_progress['progress']
            elif current_progress['operation'] == 'uploading':
                process_status['upload_progress'] = current_progress['progress']
        
        # Update additional progress fields with chunked streaming support
        process_status['current_file_size'] = current_progress.get('file_size', 0)
        process_status['downloaded_size'] = current_progress.get('downloaded_size', 0)
        process_status['uploaded_size'] = current_progress.get('uploaded_size', 0)
        process_status['download_speed'] = current_progress.get('speed', 0)
        process_status['upload_speed'] = current_progress.get('upload_speed', 0)
        process_status['total_files'] = current_progress.get('total_files', 0)
        process_status['processed_files'] = current_progress.get('processed_files', 0)
        process_status['downloaded_files'] = current_progress.get('downloaded_files', 0)
        process_status['uploaded_files'] = current_progress.get('uploaded_files', 0)
        process_status['eta'] = current_progress.get('eta')
        
        # New fields for chunked operations
        process_status['memory_usage'] = current_progress.get('memory_usage', 0)
        process_status['chunk_queue_size'] = current_progress.get('chunk_queue_size', 0)
        
    except ImportError as e:
        print(f"⚠️ Cannot import telegram_downloader: {e}")
    except Exception as e:
        print(f"❌ Error syncing progress: {e}")
        print(f"📋 Traceback: {traceback.format_exc()}")


async def run_telegram_process():
    """Run the telegram download and upload process with enhanced error handling for chunked operations"""
    global process_status
    
    try:
        print("🚀 Setting process_status to running...")
        process_status['running'] = True
        process_status['last_error'] = None
        process_status['start_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'initializing'
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False
        
        print("🚀 Starting Telegram to Google Drive Video Uploader (Chunked Streaming Mode)")
        print("=" * 60)
        print("📊 Mode: Chunked Download + Simultaneous Upload")
        print("💾 Memory: Optimized streaming (no disk storage)")
        print("=" * 60)
        
        # Validate prerequisites before starting
        credentials_ok, missing_files = check_credentials()
        if not credentials_ok:
            raise ValueError(f"Missing credentials: {missing_files}")
        
        # Run the telegram downloader (which includes drive upload with chunked streaming)
        print("📞 Calling telegram_main() with chunked streaming...")
        await telegram_main()
        
        print("\n" + "=" * 60)
        print("✅ Chunked streaming process completed successfully!")
        print("📊 All files processed without disk storage")
        
        # Update stats
        process_status['stats'] = get_stats()
        process_status['end_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'completed'
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False
        
    except ImportError as e:
        error_msg = f"Missing required module: {str(e)}"
        print(f"\n❌ Import error: {error_msg}")
        process_status['last_error'] = error_msg
        process_status['end_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'error'
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False
        raise e
    except ValueError as e:
        error_msg = f"Configuration error: {str(e)}"
        print(f"\n❌ Configuration error: {error_msg}")
        process_status['last_error'] = error_msg
        process_status['end_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'error'
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False
        raise e
    except Exception as e:
        error_msg = f"Chunked streaming process error: {str(e)}"
        print(f"\n❌ {error_msg}")
        print(f"📋 Traceback: {traceback.format_exc()}")
        process_status['last_error'] = error_msg
        process_status['end_time'] = datetime.now().isoformat()
        process_status['current_operation'] = 'error'
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False
        raise e
    finally:
        print("🏁 Setting process_status to not running...")
        process_status['running'] = False
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False


def run_async_function():
    """Wrapper to run async function in thread with enhanced error handling for chunked operations"""
    print("🧵 Starting async chunked streaming function in thread...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_telegram_process())
        print("✅ Chunked streaming thread completed successfully")
    except Exception as e:
        error_msg = f"Thread error: {str(e)}"
        print(f"❌ {error_msg}")
        print(f"📋 Traceback: {traceback.format_exc()}")
        process_status['last_error'] = error_msg
        process_status['running'] = False
        process_status['streaming_active'] = False
        process_status['simultaneous_operations'] = False
    finally:
        loop.close()
        print("🧵 Thread cleanup completed")


# ============================================================================
# ROUTES WITH ENHANCED ERROR HANDLING AND CORS
# ============================================================================

# ROUTE: Home endpoint
@app.route('/', methods=['GET', 'OPTIONS'])
def home():
    """Home endpoint with API information"""
    if request.method == 'OPTIONS':
        return handle_preflight_response()
    
    log_request_info()
    
    try:
        return jsonify({
            'status': 'success',
            'message': 'Telegram to Google Drive Video Uploader API (Chunked Streaming)',
            'version': '2.1',
            'mode': 'chunked_streaming',
            'features': [
                'Chunked downloading from Telegram',
                'Simultaneous upload to Google Drive',
                'Memory-optimized streaming',
                'No disk storage required',
                'Real-time progress tracking'
            ],
            'data': {
                'endpoints': {
                    '/': 'GET - API information',
                    '/status': 'GET - Check process status and stats',
                    '/start-upload': 'POST - Start chunked video download and upload process',
                    '/stats': 'GET - Get upload statistics',
                    '/health': 'GET - Health check',
                    '/progress': 'GET - Get detailed progress information'
                },
                'server_time': datetime.now().isoformat(),
                'process_running': process_status['running'],
                'streaming_active': process_status.get('streaming_active', False),
                'simultaneous_operations': process_status.get('simultaneous_operations', False)
            },
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return create_error_response(
            'server_error',
            'Failed to get API information',
            str(e),
            500,
            ['Try refreshing the page', 'Check server logs for details']
        )


# ROUTE: Health check
@app.route('/health', methods=['GET', 'OPTIONS'])
def health_check():
    """Health check endpoint with comprehensive system status"""
    if request.method == 'OPTIONS':
        return handle_preflight_response()
    
    log_request_info()
    
    try:
        credentials_ok, missing_files = check_credentials()
        
        # Check system health
        health_status = {
            'server_status': 'healthy' if credentials_ok else 'warning',
            'credentials': 'ok' if credentials_ok else f'missing: {missing_files}',
            'process_running': process_status['running'],
            'streaming_mode': 'enabled',
            'chunked_operations': 'supported',
            'memory_optimization': 'active',
            'disk_usage': 'minimal',
            'server_uptime': time.time(),
            'python_version': f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
            'current_time': datetime.now().isoformat()
        }
        
        # Add additional health checks
        try:
            # Check if we can import required modules
            import telegram_downloader
            health_status['telegram_module'] = 'available'
        except ImportError:
            health_status['telegram_module'] = 'missing'
            
        try:
            import drive_uploader
            health_status['drive_module'] = 'available'
        except ImportError:
            health_status['drive_module'] = 'missing'
        
        return jsonify({
            'status': 'success',
            'data': health_status,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return create_error_response(
            'health_check_error',
            'Health check failed',
            str(e),
            503,
            ['Server may be experiencing issues', 'Try again in a few moments']
        )


# ROUTE: Process status
@app.route('/status', methods=['GET', 'OPTIONS'])
def get_status():
    """Get current process status with enhanced information for chunked operations"""
    if request.method == 'OPTIONS':
        return handle_preflight_response()
    
    log_request_info()
    
    try:
        # Sync latest progress
        sync_progress_from_telegram()
        
        status_data = {
            'process_running': process_status['running'],
            'streaming_active': process_status.get('streaming_active', False),
            'simultaneous_operations': process_status.get('simultaneous_operations', False),
            'last_error': process_status['last_error'],
            'start_time': process_status.get('start_time'),
            'end_time': process_status.get('end_time'),
            'current_operation': process_status.get('current_operation'),
            'memory_usage': process_status.get('memory_usage', 0),
            'chunk_queue_size': process_status.get('chunk_queue_size', 0),
            'stats': process_status.get('stats', get_stats()),
            'uptime_seconds': time.time() - (time.mktime(datetime.fromisoformat(process_status['start_time']).timetuple()) if process_status.get('start_time') else time.time())
        }
        
        return jsonify({
            'status': 'success',
            'data': status_data,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return create_error_response(
            'status_error',
            'Failed to get process status',
            str(e),
            500,
            ['Try refreshing the page', 'Check if the process is still running']
        )


# ROUTE: Detailed progress
@app.route('/progress', methods=['GET', 'OPTIONS'])
def get_progress():
    """Get detailed progress information with real-time updates for chunked operations"""
    if request.method == 'OPTIONS':
        return handle_preflight_response()
    
    log_request_info()
    
    try:
        # Sync progress from telegram module
        sync_progress_from_telegram()
        
        progress_data = {
            'running': process_status['running'],
            'streaming_active': process_status.get('streaming_active', False),
            'simultaneous_operations': process_status.get('simultaneous_operations', False),
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
            'uploaded_size': process_status.get('uploaded_size', 0),
            'download_speed': process_status.get('download_speed', 0),
            'upload_speed': process_status.get('upload_speed', 0),
            'memory_usage': process_status.get('memory_usage', 0),
            'chunk_queue_size': process_status.get('chunk_queue_size', 0),
            'eta': process_status.get('eta'),
            'start_time': process_status.get('start_time'),
            'last_error': process_status.get('last_error'),
            'last_update': datetime.now().isoformat(),
            'efficiency_metrics': {
                'disk_usage': 'minimal (streaming)',
                'memory_optimization': 'active',
                'concurrent_operations': process_status.get('simultaneous_operations', False)
            }
        }
        
        return jsonify({
            'status': 'success',
            'data': progress_data,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return create_error_response(
            'progress_error',
            'Failed to get progress information',
            str(e),
            500,
            ['Try refreshing the page', 'Check if the process is running correctly']
        )


# ROUTE: Upload statistics
@app.route('/stats', methods=['GET', 'OPTIONS'])
def get_statistics():
    """Get detailed upload statistics with error handling"""
    if request.method == 'OPTIONS':
        return handle_preflight_response()
    
    log_request_info()
    
    try:
        stats = get_stats()
        
        # Add additional statistics for chunked operations
        enhanced_stats = {
            **stats,
            'last_updated': datetime.now().isoformat(),
            'process_status': {
                'running': process_status['running'],
                'current_operation': process_status.get('current_operation'),
                'streaming_active': process_status.get('streaming_active', False),
                'mode': 'chunked_streaming'
            },
            'performance_metrics': {
                'disk_usage': 'optimized (no file storage)',
                'memory_efficiency': 'high',
                'streaming_mode': 'enabled',
                'concurrent_operations': 'supported'
            }
        }
        
        return jsonify({
            'status': 'success',
            'data': enhanced_stats,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        return create_error_response(
            'stats_error',
            'Failed to get statistics',
            str(e),
            500,
            ['Check if the drive uploader module is available', 'Verify credentials are configured correctly']
        )


# ROUTE: Start upload process (Enhanced for chunked streaming)
@app.route('/start-upload', methods=['POST', 'OPTIONS'])
def start_upload():
    """Start the chunked video download and upload process with enhanced error handling"""
    
    # Enhanced OPTIONS handling
    if request.method == 'OPTIONS':
        print("🔄 Handling OPTIONS request for /start-upload")
        return handle_preflight_response()
    
    log_request_info()
    print("🎯 POST /start-upload endpoint hit! (Chunked Streaming Mode)")
    print(f"📊 Current process_status['running']: {process_status['running']}")
    
    try:
        # Check if process is already running
        if process_status['running']:
            print("⚠️ Process already running")
            return create_error_response(
                'conflict',
                'Chunked streaming process is already running',
                f'Upload process started at {process_status.get("start_time")}',
                409,
                [
                    'Wait for the current process to complete',
                    'Check progress using /progress endpoint',
                    'Monitor status using /status endpoint',
                    'The chunked streaming process is memory-optimized and faster'
                ]
            )
        
        # Check credentials
        credentials_ok, missing_files = check_credentials()
        if not credentials_ok:
            print("❌ Missing credentials")
            return create_error_response(
                'configuration',
                'Missing required credential files',
                f'Missing files: {missing_files}',
                400,
                [
                    'Ensure credentials.json exists in the project directory',
                    'Verify the credentials file contains valid JSON',
                    'Check file permissions'
                ]
            )
        
        # Validate required modules
        try:
            import telegram_downloader
            import drive_uploader
        except ImportError as e:
            return create_error_response(
                'dependency',
                'Required modules not available',
                str(e),
                500,
                [
                    'Install missing dependencies',
                    'Check if all required modules are in the project directory',
                    'Verify the Python environment is correctly configured'
                ]
            )
        
        print("✅ Starting chunked streaming upload process...")
        initial_stats = get_stats()
        
        # Reset process status for chunked operations
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
            'uploaded_size': 0,
            'upload_speed': 0,
            'download_speed': 0,
            'eta': None,
            'streaming_active': False,
            'memory_usage': 0,
            'chunk_queue_size': 0,
            'simultaneous_operations': False
        })
        
        print("🧵 Creating and starting background thread for chunked streaming...")
        # Start the process in background thread
        thread = threading.Thread(target=run_async_function, daemon=True)
        thread.start()
        print("🧵 Background thread started for chunked streaming!")
        
        # Give the thread a moment to start
        time.sleep(0.1)
        
        response_data = {
            'status': 'success',
            'message': 'Chunked video download and upload process started in background',
            'mode': 'chunked_streaming',
            'features': [
                'Memory-optimized streaming',
                'Simultaneous download and upload',
                'No disk storage required',
                'Real-time progress tracking'
            ],
            'data': {
                'initial_stats': initial_stats,
                'process_id': thread.ident,
                'started_at': datetime.now().isoformat(),
                'optimization': {
                    'memory_usage': 'minimized',
                    'disk_usage': 'none',
                    'streaming_enabled': True,
                    'concurrent_operations': True
                }
            },
            'note': 'Use /progress endpoint to check detailed progress with streaming metrics',
            'timestamp': datetime.now().isoformat()
        }
        
        print(f"✅ Returning success response for chunked streaming")
        return jsonify(response_data), 200
        
    except Exception as e:
        error_msg = f"Failed to start chunked streaming process: {str(e)}"
        print(f"❌ Error starting process: {error_msg}")
        print(f"📋 Traceback: {traceback.format_exc()}")
        
        return create_error_response(
            'startup_error',
            'Failed to start chunked upload process',
            error_msg,
            500,
            [
                'Check server logs for detailed error information',
                'Verify all dependencies are installed',
                'Ensure sufficient system resources are available',
                'Try restarting the server',
                'Check if chunked streaming modules are properly configured'
            ]
        )


# ============================================================================
# HELPER FUNCTION FOR CONSISTENT PREFLIGHT RESPONSES
# ============================================================================
def handle_preflight_response():
    """Create a consistent preflight response"""
    response = make_response()
    origin = request.headers.get('Origin')
    
    allowed_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173", 
        "https://localhost:3000",
        "https://localhost:5173",
        "https://your-frontend-domain.com"
    ]
    
    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
        
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin, X-Requested-With, Cache-Control'
    response.headers['Access-Control-Max-Age'] = '3600'
    response.headers['Access-Control-Allow-Credentials'] = 'false'
    
    return response


# ============================================================================
# ENHANCED ERROR HANDLERS
# ============================================================================
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors with helpful information"""
    return create_error_response(
        'not_found',
        'Endpoint not found',
        f'The requested endpoint {request.path} does not exist',
        404,
        [
            'Check the URL spelling',
            'Verify the API endpoint exists',
            f'Available endpoints: /, /health, /status, /stats, /start-upload, /progress'
        ]
    )


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with detailed information"""
    error_details = str(error) if error else 'Unknown internal server error'
    return create_error_response(
        'server_error',
        'Internal server error',
        error_details,
        500,
        [
            'Try the request again',
            'Check server logs for more details',
            'Contact support if the problem persists'
        ]
    )


@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors with method information"""
    return create_error_response(
        'method_not_allowed',
        'Method not allowed',
        f'The {request.method} method is not allowed for {request.path}',
        405,
        [
            'Check the HTTP method (GET, POST, etc.)',
            'Verify the endpoint supports the method you\'re using',
            'Refer to the API documentation'
        ]
    )


@app.errorhandler(400)
def bad_request(error):
    """Handle 400 errors"""
    return create_error_response(
        'bad_request',
        'Bad request',
        'The request was malformed or invalid',
        400,
        [
            'Check the request format',
            'Verify all required parameters are included',
            'Ensure JSON is properly formatted'
        ]
    )


# ============================================================================
# SERVER STARTUP WITH ENHANCED LOGGING
# ============================================================================
if __name__ == '__main__':
    print("🚀 Starting Telegram to Google Drive API Server (Chunked Streaming)")
    print("=" * 80)
    print("📡 Server will be available at: http://localhost:5000")
    print("📖 API Documentation at: http://localhost:5000/")
    print("🎯 Mode: Chunked Streaming with Memory Optimization")
    print("💾 Disk Usage: Minimal (no file storage)")
    print("⚡ Performance: Simultaneous download/upload")
    
    # System checks
    print("\n🔍 System Checks:")
    credentials_ok, missing_files = check_credentials()
    if not credentials_ok:
        print(f"⚠️  Warning: Missing credential files: {missing_files}")
        print("   Please add credentials.json before starting uploads")
    else:
        print("✅ Credentials found and validated")
    
    # Module checks
    print("\n📦 Module Availability:")
    try:
        import telegram_downloader
        print("✅ telegram_downloader module available (chunked streaming)")
    except ImportError as e:
        print(f"❌ telegram_downloader module missing: {e}")
    
    try:
        import drive_uploader
        print("✅ drive_uploader module available (streaming upload)")
    except ImportError as e:
        print(f"❌ drive_uploader module missing: {e}")
    
    # Initial stats
    try:
        initial_stats = get_stats()
        if 'error' in initial_stats:
            print(f"⚠️  Stats warning: {initial_stats['error']}")
        else:
            print(f"📊 Current stats: {initial_stats['total_uploaded']} videos uploaded ({initial_stats['total_size_mb']:.1f} MB)")
    except Exception as e:
        print(f"⚠️  Could not load initial stats: {e}")
    
    # Print available endpoints
    print("\n📋 Available API Endpoints:")
    print("   GET  /          - API information")
    print("   GET  /health    - Health check")
    print("   GET  /status    - Process status (with streaming metrics)")
    print("   GET  /progress  - Detailed progress (with chunk info)")
    print("   GET  /stats     - Upload statistics")
    print("   POST /start-upload - Start chunked upload process")
    
    print("\n🔒 CORS Configuration:")
    print("   ✅ Comprehensive CORS headers configured")
    print("   ✅ Preflight requests handled globally")
    print("   ✅ Multiple origins supported")
    print("   ✅ Enhanced error handling enabled")
    
    print("\n⚡ Chunked Streaming Features:")
    print("   🔄 Real-time chunk processing")
    print("   💾 Memory-optimized operations")
    print("   📤 Simultaneous download/upload")
    print("   📊 Advanced progress tracking")
    print("   🚫 No disk storage required")
    
    print("\n🚦 Starting Flask server...")
    print("=" * 80)
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
    except KeyboardInterrupt:
        print("\n\n🛑 Server shutdown requested")
        print("✅ Server stopped gracefully")
    except Exception as e:
        print(f"\n❌ Server startup error: {e}")
        print(f"📋 Traceback: {traceback.format_exc()}")
