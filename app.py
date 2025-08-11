from flask import Flask, request, render_template_string, send_file, flash, redirect, url_for, jsonify
import os
import subprocess
import tempfile
import uuid
from werkzeug.utils import secure_filename
import xml.etree.ElementTree as ET
import logging

# Configure logging for Railway
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Use /tmp for cloud platforms, local uploads for development
UPLOAD_FOLDER = '/tmp/uploads' if os.path.exists('/tmp') else 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def find_openscad():
    """Try to find OpenSCAD executable"""
    possible_paths = [
        'openscad',
        '/usr/bin/openscad',
        '/usr/local/bin/openscad',
        '/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD',
        r'C:\Program Files\OpenSCAD\openscad.exe',
        r'C:\Program Files (x86)\OpenSCAD\openscad.exe',
    ]
    
    for path in possible_paths:
        try:
            result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"Found OpenSCAD at: {path}")
                return path
        except Exception as e:
            logger.debug(f"Failed to find OpenSCAD at {path}: {e}")
            continue
    
    logger.error("OpenSCAD not found in any standard location")
    return None

def validate_svg(svg_path):
    """Basic SVG validation"""
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
        # Check if it's actually an SVG
        if 'svg' not in root.tag.lower():
            return False, "File is not a valid SVG"
        return True, "Valid SVG"
    except Exception as e:
        return False, f"Invalid SVG file: {str(e)}"

def create_openscad_file(svg_path, extrude_height=5):
    """Create OpenSCAD file for SVG extrusion"""
    scad_content = f"""
// Generated OpenSCAD file for SVG extrusion
// Extrude height: {extrude_height}mm

linear_extrude(height = {extrude_height}, center = false, convexity = 10)
    import("{os.path.basename(svg_path)}", center = true);
"""
    return scad_content

def convert_svg_to_stl(svg_path, output_path, extrude_height=5):
    """Convert SVG to STL using OpenSCAD"""
    openscad_path = find_openscad()
    
    if not openscad_path:
        return False, "OpenSCAD not found. Please install OpenSCAD."
    
    # Validate SVG first
    is_valid, message = validate_svg(svg_path)
    if not is_valid:
        return False, message
    
    try:
        # Create temporary SCAD file
        temp_dir = os.path.dirname(svg_path)
        scad_filename = f"temp_{uuid.uuid4()}.scad"
        scad_path = os.path.join(temp_dir, scad_filename)
        
        # Generate SCAD content
        scad_content = create_openscad_file(svg_path, extrude_height)
        
        # Write SCAD file
        with open(scad_path, 'w', encoding='utf-8') as f:
            f.write(scad_content)
        
        # Run OpenSCAD to generate STL with memory limits
        cmd = [
            openscad_path,
            '-o', output_path,
            '--render',  # Force render for better compatibility
            scad_path
        ]
        
        logger.info(f"Running OpenSCAD command: {' '.join(cmd)}")
        
        # Change to the directory containing the SVG file so OpenSCAD can find it
        # Reduced timeout for Railway's constraints
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=60,  # Reduced timeout for Railway
            cwd=temp_dir
        )
        
        # Clean up temporary SCAD file
        if os.path.exists(scad_path):
            os.remove(scad_path)
        
        if result.returncode == 0 and os.path.exists(output_path):
            logger.info("STL conversion successful")
            return True, "Success"
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            logger.error(f"OpenSCAD error: {error_msg}")
            return False, f"OpenSCAD error: {error_msg}"
            
    except subprocess.TimeoutExpired:
        logger.error("OpenSCAD conversion timed out")
        return False, "Conversion timed out. File may be too complex."
    except Exception as e:
        logger.error(f"Conversion error: {str(e)}")
        return False, f"Conversion error: {str(e)}"

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/health')
def health():
    """Health check endpoint for hosting platforms"""
    openscad_available = find_openscad() is not None
    return jsonify({
        'status': 'healthy',
        'message': 'SVG to STL Tool by 3DTV is running',
        'openscad_available': openscad_available,
        'upload_folder': UPLOAD_FOLDER,
        'port': os.environ.get('PORT', 'Not set')
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(url_for('index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(url_for('index'))
    
    # Check file extension
    allowed_extensions = {'svg'}
    if not ('.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
        flash('Invalid file type. Please upload an SVG file.')
        return redirect(url_for('index'))
    
    # Use default extrude height
    extrude_height = 5.0
    
    try:
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        upload_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        file.save(upload_path)
        
        logger.info(f"File uploaded: {upload_path}")
        
        stl_filename = f"{os.path.splitext(unique_filename)[0]}.stl"
        stl_path = os.path.join(UPLOAD_FOLDER, stl_filename)
        
        success, message = convert_svg_to_stl(upload_path, stl_path, extrude_height)
        
        # Clean up uploaded file
        if os.path.exists(upload_path):
            os.remove(upload_path)
        
        if success and os.path.exists(stl_path):
            import threading
            # Cleanup STL file after download
            threading.Timer(30.0, lambda: os.remove(stl_path) if os.path.exists(stl_path) else None).start()
            
            return send_file(
                stl_path, 
                as_attachment=True, 
                download_name=f"{os.path.splitext(filename)[0]}.stl",
                mimetype='application/sla'
            )
        else:
            flash(f'Conversion failed: {message}')
            return redirect(url_for('index'))
            
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}")
        flash(f'Upload failed: {str(e)}')
        return redirect(url_for('index'))

# [Your existing TEMPLATE variable remains the same]
TEMPLATE = '''
[... your existing HTML template ...]
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    # Check OpenSCAD availability on startup
    openscad_path = find_openscad()
    if not openscad_path:
        logger.error("⚠️  WARNING: OpenSCAD not found! Please install OpenSCAD.")
        logger.error("   Download from: https://openscad.org/downloads.html")
    else:
        logger.info(f"✅ OpenSCAD found at: {openscad_path}")
    
    logger.info(f"🚀 SVG to STL Tool by 3DTV starting on port {port}...")
    logger.info(f"🌐 Upload folder: {UPLOAD_FOLDER}")
    
    # Bind to all interfaces for Railway
    app.run(host='0.0.0.0', port=port, debug=debug)
