from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response, Response, send_from_directory
from flask_login import login_required
from ..services.maintenance_service import MaintenanceService
from ..utils.auth import role_required
from ..utils.errors import handle_post_error
from ..extensions import db
import os

bp = Blueprint('maintenance', __name__)

@bp.before_request
@login_required
@role_required(['admin']) # Fortress Guard: Strictly Admin only
def before_request():
    pass

@bp.route('/')
def index():
    """Messenger: Renders the Maintenance Dashboard."""
    backups = MaintenanceService.list_backups()
    return render_template('maintenance/maintenance.html', backups=backups)

# --- DATABASE ACTIONS ---

@bp.route('/vacuum', methods=['POST'])
def vacuum():
    """Messenger: Triggers DB optimization."""
    try:
        MaintenanceService.perform_vacuum()
        flash("Database optimized successfully (VACUUM complete).", "success")
        # Redirect to index to show flash
        return redirect(url_for('maintenance.index'))
    
    except Exception as e:
        return handle_post_error(e, "maintenance.vacuum")

# --- BACKUP MANAGEMENT ---

@bp.route('/backup/create', methods=['POST'])
def create_backup():
    """Messenger: Creates a new backup and triggers a list refresh."""
    try:
        filename = MaintenanceService.create_backup()
        flash(f"Backup created: {filename}", "success")
        
        # SUCCESS: Force a full refresh so the Flash appears and the list updates
        response = make_response("", 200)
        response.headers['HX-Redirect'] = url_for('maintenance.index')
        return response

    except Exception as e:
        # FAILURE: Rollback (if needed), Log, and show OOB error banner
        return handle_post_error(e, "maintenance.create_backup")

@bp.route('/backup/download/<filename>')
def download_backup(filename):
    """Messenger: Securely streams the .sql file to the browser."""
    directory = MaintenanceService.get_backup_dir()
    return send_from_directory(directory, filename, as_attachment=True)

@bp.route('/backup/delete/<filename>', methods=['POST'])
def delete_backup(filename):
    """Messenger: Deletes a backup and updates the UI."""
    MaintenanceService.delete_backup(filename)
    flash(f"Backup {filename} deleted.", "info")
    
    response = make_response("", 200)
    response.headers['HX-Redirect'] = url_for('maintenance.index')
    return response

# --- DATA EXPORTS ---

@bp.route('/export/<target_type>')
def export_data(target_type):
    """Messenger: Streams a CSV file for the requested data type."""
    try:
        csv_content = MaintenanceService.export_to_csv(target_type)
        
        # Build the response with the correct headers for a download
        filename = f"codexmetry_{target_type}_{os.urandom(2).hex()}.csv"
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return handle_post_error(e, "maintenance.export_data")

# --- MAINTENANCE MODE ---

@bp.route('/toggle-lock', methods=['POST'])
def toggle_lock():
    """Messenger: Flips the global maintenance state."""
    try:
        settings = MaintenanceService.toggle_maintenance_mode()
        
        state = "LOCKED (Read-Only)" if settings.is_maintenance_mode else "UNLOCKED (Operational)"
        flash(f"System status updated: {state}", "success" if not settings.is_maintenance_mode else "info")
        
        # Standard Redirect (Maintenance UI is handled by full page refresh for this high-stakes action)
        return redirect(url_for('maintenance.index'))

    except Exception as e:
        return handle_post_error(e, "maintenance.toggle_lock")