import os
from flask import current_app
from weasyprint import HTML, CSS

def save_pdf_from_html(html_string: str, filename: str, subfolder: str):
    """
    Brain: Converts HTML to a PDF file on disk.
    Uses direct CSS injection by manually pointing to tailwind.css on disk.
    """
    # 1. Define physical paths on your hard drive
    # app_path is the root (where 'static' lives)
    app_path = current_app.root_path
    
    # css_path points directly to your built tailwind.css
    css_path = os.path.join(app_path, 'static', 'css', 'tailwind.css')
    
    # target_dir is the final storage spot
    target_dir = os.path.join(app_path, 'static', 'uploads', subfolder)
    os.makedirs(target_dir, exist_ok=True)
    
    output_path = os.path.join(target_dir, filename)

    # 2. Execution with direct Stylesheet injection
    # - base_url=app_path allows images to resolve as /static/uploads/...
    # - stylesheets=[CSS(css_path)] forces the engine to use your tailwind.css
    HTML(string=html_string, base_url=app_path).write_pdf(
        target=output_path,
        stylesheets=[CSS(css_path)]
    )

    return filename