from flask import Flask, request, render_template_string, send_file, flash, redirect, url_for, jsonify
import os
import subprocess
import tempfile
import uuid
from werkzeug.utils import secure_filename
import xml.etree.ElementTree as ET

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
            result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return path
        except:
            continue
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
        
        # Run OpenSCAD to generate STL
        cmd = [
            openscad_path,
            '-o', output_path,
            scad_path
        ]
        
        # Change to the directory containing the SVG file so OpenSCAD can find it
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=60,
            cwd=temp_dir
        )
        
        # Clean up temporary SCAD file
        if os.path.exists(scad_path):
            os.remove(scad_path)
        
        if result.returncode == 0 and os.path.exists(output_path):
            return True, "Success"
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            return False, f"OpenSCAD error: {error_msg}"
            
    except subprocess.TimeoutExpired:
        return False, "Conversion timed out. File may be too complex."
    except Exception as e:
        return False, f"Conversion error: {str(e)}"

@app.route('/')
def index():
    return render_template_string(TEMPLATE)

@app.route('/health')
def health():
    """Health check endpoint for hosting platforms"""
    return jsonify({
        'status': 'healthy',
        'message': 'SVG to STL Tool by 3DTV is running',
        'openscad_available': find_openscad() is not None
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
        
        stl_filename = f"{os.path.splitext(unique_filename)[0]}.stl"
        stl_path = os.path.join(UPLOAD_FOLDER, stl_filename)
        
        success, message = convert_svg_to_stl(upload_path, stl_path, extrude_height)
        
        # Clean up uploaded file
        if os.path.exists(upload_path):
            os.remove(upload_path)
        
        if success and os.path.exists(stl_path):
            import threading
            threading.Timer(5.0, lambda: os.remove(stl_path) if os.path.exists(stl_path) else None).start()
            
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
        flash(f'Upload failed: {str(e)}')
        return redirect(url_for('index'))

# HTML Template
TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SVG to STL Tool by 3DTV</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(-45deg, #1e3c72, #2a5298, #667eea, #764ba2, #f093fb, #f5576c);
            background-size: 400% 400%;
            animation: gradientFlow 15s ease infinite;
            min-height: 100vh;
            padding: 20px;
        }
        
        @keyframes gradientFlow {
            0% { background-position: 0% 50%; }
            25% { background-position: 100% 50%; }
            50% { background-position: 100% 100%; }
            75% { background-position: 0% 100%; }
            100% { background-position: 0% 50%; }
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            padding-top: 40px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 40px;
            color: white;
        }
        
        .title {
            font-size: 4rem;
            font-weight: 900;
            margin-bottom: 10px;
            text-shadow: 0 4px 20px rgba(0,0,0,0.3);
            background: linear-gradient(45deg, #fff, #f0f9ff, #dbeafe);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .description {
            font-size: 1rem;
            opacity: 0.8;
            max-width: 600px;
            margin: 0 auto;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 30px;
            padding: 50px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.15);
            border: 1px solid rgba(255,255,255,0.3);
        }
        
        .upload-area {
            border: 3px dashed #d1d5db;
            border-radius: 20px;
            padding: 60px 20px;
            text-align: center;
            background: linear-gradient(135deg, #f9fafb, #f3f4f6);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            cursor: pointer;
            overflow: hidden;
        }
        
        .upload-area::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(30, 60, 114, 0.1), transparent);
            transition: left 0.6s;
        }
        
        .upload-area:hover::before {
            left: 100%;
        }
        
        .upload-area:hover {
            border-color: #1e3c72;
            background: linear-gradient(135deg, #f0f4ff, #e0e7ff);
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(30, 60, 114, 0.15);
        }
        
        .upload-area.dragover {
            border-color: #10b981;
            background: linear-gradient(135deg, #ecfdf5, #d1fae5);
            transform: scale(1.02);
        }
        
        .upload-icon {
            font-size: 4rem;
            margin-bottom: 20px;
            animation: float 3s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }
        
        .upload-text {
            font-size: 1.5rem;
            font-weight: 700;
            color: #374151;
            margin-bottom: 8px;
        }
        
        .upload-subtext {
            color: #6b7280;
            font-size: 1rem;
            margin-bottom: 30px;
        }
        
        input[type="file"] {
            position: absolute;
            width: 100%;
            height: 100%;
            opacity: 0;
            cursor: pointer;
        }
        
        .file-preview {
            display: none;
            background: #1e3c72;
            color: white;
            padding: 12px 20px;
            border-radius: 15px;
            font-weight: 600;
            margin-top: 15px;
            animation: slideUp 0.3s ease;
        }
        
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .convert-btn {
            width: 100%;
            background: linear-gradient(135deg, #1e3c72, #2a5298);
            color: white;
            border: none;
            padding: 20px;
            border-radius: 15px;
            font-size: 1.3rem;
            font-weight: 700;
            cursor: pointer;
            margin-top: 20px;
            transition: all 0.3s ease;
            box-shadow: 0 10px 30px rgba(30, 60, 114, 0.3);
            position: relative;
            overflow: hidden;
        }
        
        .convert-btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.6s;
        }
        
        .convert-btn:hover::before {
            left: 100%;
        }
        
        .convert-btn:hover {
            transform: translateY(-3px);
            box-shadow: 0 15px 40px rgba(30, 60, 114, 0.4);
        }
        
        .convert-btn:disabled {
            opacity: 0.7;
            cursor: not-allowed;
            transform: none;
        }
        
        .alert {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #dc2626;
            padding: 15px 20px;
            border-radius: 15px;
            margin-bottom: 30px;
            font-weight: 600;
        }
        
        .spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top-color: white;
            animation: spin 1s ease-in-out infinite;
            margin-right: 10px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        @media (max-width: 640px) {
            .title { font-size: 2.5rem; }
            .card { padding: 30px 20px; }
            .upload-area { padding: 40px 15px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="title">SVG to STL Tool by 3DTV</h1>
            <p class="description">Upload an SVG file and convert it to a 3D printable STL file using linear extrusion</p>
        </div>
        
        <div class="card">
            {% with messages = get_flashed_messages() %}
                {% if messages %}
                    {% for message in messages %}
                        <div class="alert">⚠️ {{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            <form id="uploadForm" action="/upload" method="post" enctype="multipart/form-data">
                <div class="upload-area" id="dropZone" onclick="document.getElementById('fileInput').click()">
                    <div class="upload-icon">🎨</div>
                    <div class="upload-text">Drop your SVG file here</div>
                    <div class="upload-subtext">or click to browse • SVG files only, up to 16MB</div>
                    <input type="file" name="file" id="fileInput" accept=".svg" required>
                    <div class="file-preview" id="filePreview"></div>
                </div>
                
                <button type="submit" class="convert-btn" id="convertBtn">
                    🚀 Generate STL File
                </button>
            </form>
        </div>
    </div>
    
    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const filePreview = document.getElementById('filePreview');
        const convertBtn = document.getElementById('convertBtn');
        const form = document.getElementById('uploadForm');
        
        fileInput.addEventListener('change', (e) => {
            if (e.target.files[0]) {
                const file = e.target.files[0];
                if (file.name.toLowerCase().endsWith('.svg')) {
                    filePreview.innerHTML = `🎨 ${file.name} (${(file.size/1024).toFixed(1)}KB)`;
                    filePreview.style.display = 'block';
                } else {
                    alert('Please select an SVG file');
                    fileInput.value = '';
                }
            }
        });
        
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            
            const files = e.dataTransfer.files;
            if (files[0]) {
                const file = files[0];
                if (file.name.toLowerCase().endsWith('.svg')) {
                    fileInput.files = files;
                    filePreview.innerHTML = `🎨 ${file.name} (${(file.size/1024).toFixed(1)}KB)`;
                    filePreview.style.display = 'block';
                } else {
                    alert('Please drop an SVG file');
                }
            }
        });
        
        form.addEventListener('submit', () => {
            convertBtn.innerHTML = '<div class="spinner"></div>Generating STL...';
            convertBtn.disabled = true;
            
            // Simple reset after 2 seconds - works reliably
            setTimeout(() => {
                convertBtn.innerHTML = '🚀 Generate STL File';
                convertBtn.disabled = false;
                fileInput.value = '';
                filePreview.style.display = 'none';
            }, 2000);
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    if not find_openscad():
        print("⚠️  WARNING: OpenSCAD not found! Please install OpenSCAD.")
        print("   Download from: https://openscad.org/downloads.html")
    else:
        print("✅ OpenSCAD found and ready!")
    
    print(f"🚀 SVG to STL Tool by 3DTV starting on port {port}...")
    print(f"🌐 Local: http://127.0.0.1:{port}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)