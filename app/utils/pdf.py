import os
from flask import current_app, render_template
from weasyprint import HTML, CSS

def save_pdf_from_html(template_path: str, context: dict, filename: str, subfolder: str):
    """
    Brain: Converts HTML to a PDF file on disk.
    Uses direct CSS injection by manually pointing to tailwind.css on disk.
    """
    app_path = current_app.root_path
    
    # 1. Inject Environment Flags into the data package
    context_data = context.copy()
    context_data['physical_root'] = app_path
    context_data['is_pdf_mode'] = True
    
    # 2. Render the HTML string
    html_string = render_template(template_path, **context_data)
    
    # 3. Pathing for CSS and Output
    css_path = os.path.join(app_path, 'static', 'css', 'tailwind.css')
    target_dir = os.path.join(app_path, 'static', 'uploads', subfolder)
    os.makedirs(target_dir, exist_ok=True)
    output_path = os.path.join(target_dir, filename)

    # 4. Generate
    # base_url=app_path allows WeasyPrint to resolve /static/ as a local folder
    HTML(string=html_string, base_url=app_path).write_pdf(
        target=output_path,
        zoom=1,
        stylesheets=[CSS(css_path)],
        pdf_forms=True
    )

    return filename