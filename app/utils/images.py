import os
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import current_app, request

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(file, subfolder: str, old_filename: str | None = None) -> str | None:
    """
    Handles securing, saving, and cleaning up images.
    Returns: New filename string or None if failed.
    """
    if not file or file.filename == '':
        return None

    if not allowed_file(file.filename):
        return None
    
    # 1. Generate unique filename
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"{timestamp}_{secure_filename(file.filename)}"

    # 2. Ensure directory exists (e.g., static/uploads/logos)
    target_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], subfolder)
    os.makedirs(target_dir, exist_ok=True)

    # 3. Save new file
    file.save(os.path.join(target_dir, filename))

    # 4. Cleanup old file if it exists (PRD 4.5)
    if old_filename:
        old_path = os.path.join(target_dir, old_filename)
        if os.path.exists(old_path) and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass # Log this in production, but don't crash the app

    return filename

    

    

if __name__ == '__main__':
    print(allowed_file('Test image.file.PNG'))