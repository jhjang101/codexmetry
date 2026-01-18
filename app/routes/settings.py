from flask import Blueprint, render_template
from app.services.settings_service import MetadataService as Metadata


bp = Blueprint('settings', __name__)

@bp.route('/')
def index():
    return render_template('settings/settings.html')