import os
import secrets
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip', 'csv'}

def allowed_file(filename: str) -> bool:
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_file(file, subfolder: str) -> str | None:
    """
    Saves an uploaded file to the static/uploads/subfolder.
    Returns: The generated filename or None.
    """
    if not file or file.filename == '':
        return None

    if not allowed_file(file.filename):
        return None

    # 1. Generate unique identifiers
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_suffix = secrets.token_hex(3) # Adds something like 'a1b2c3'
    
    # 2. Secure the name (strips non-ASCII)
    secured_name = secure_filename(file.filename)

    # 3. Handle non-ASCII fallbacks
    if not secured_name or secured_name.startswith('.'):
        ext = os.path.splitext(file.filename)[1]
        secured_name = f"attachment{ext}"

    # 4. Final UNIQUE internal path
    # Format: TIMESTAMP_RANDOM_NAME.EXT
    # Example: 20260124_a1b2c3_attachment.txt
    filename = f"{timestamp}_{random_suffix}_{secured_name}"

    # 5. Ensure target directory exists
    target_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(target_dir, exist_ok=True)

    # 6. Save to disk
    file.save(os.path.join(target_dir, filename))

    return filename

def delete_physical_file(filename: str, subfolder: str):
    """Safely removes a file from the disk."""
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder, filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        try:
            os.remove(file_path)
            return True
        except OSError:
            return False
    return False