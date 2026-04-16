import os
from dotenv import load_dotenv
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, g
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from zoneinfo import ZoneInfo
from .extensions import db, csrf, login_manager,migrate
from .utils.errors import humanize_error

def create_app():
    load_dotenv()
    app = Flask(__name__)

    # 1. Configuration
    db_user = os.getenv('DB_USER')
    db_pass = os.getenv('DB_PASSWORD')
    db_name = os.getenv('DB_NAME')
    db_host = os.getenv('DB_HOST')
    db_port = os.getenv('DB_PORT', '5432')

    if not all([db_user, db_pass, db_name, db_host]):
        raise RuntimeError(
            "CRITICAL: Missing mandatory Database environment variables. "
            "Ensure DB_USER, DB_PASSWORD, DB_NAME, and DB_HOST are set in .env"
        )
    
    db_url = f"postgresql+psycopg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
    BACKUP_FOLDER = os.path.join(app.root_path, 'backups')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(BACKUP_FOLDER, exist_ok=True)

    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'generate-a-long-random-string-here')
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['BACKUP_FOLDER'] = BACKUP_FOLDER 
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    # 2. Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

     # Configure Login Manager
    login_manager.login_view = 'auth.login' # type: ignore
    login_manager.login_message_category = 'info' # type: ignore

    # The HTMX Login Redirect Fix
    @login_manager.unauthorized_handler
    def unauthorized():
        """Messenger: Catch unauthorized access and handle HTMX vs Standard redirects."""
        if request.headers.get('HX-Request'):
            # If HTMX, send the 'HX-Redirect' header. 
            # This tells HTMX to refresh the whole window to the login page.
            response = make_response("", 200)
            response.headers['HX-Redirect'] = url_for('auth.login')
            return response
        
        # Otherwise, perform standard redirect
        # 1. Define your "Front Door" paths
        landing_paths = ['/', '/dashboard', '/dashboard/']

        # 2. Clean Redirect for the front door
        if request.path in landing_paths:
            return redirect(url_for('auth.login'))
        
        # 3. Contextual Redirect for everything else
        flash("Please log in to access this page.", "info")
        return redirect(url_for('auth.login', next=request.full_path))
    
    # --- GLOBAL CONTEXT HOOK ---
    @app.before_request
    def load_global_context():
        """Brain: Fetches Metadata once per request to serve as the Source of Truth."""
        # Avoid running on static file requests for performance
        if request.endpoint == 'static':
            return

        from .services.settings_service import MetadataService
        # Store in 'g' (Request Global) to prevent redundant DB queries
        g.metadata = MetadataService.get_by_id(1)
        g.office_tz = g.metadata.timezone if g.metadata else 'America/Chicago'
    
    # 3. Register CLI Commands
    from .utils.cli import seed_db_command
    app.cli.add_command(seed_db_command)

    # 4. Register Blueprints
    from . import models
    from .routes import (dashboard, quotes, purchase_orders, invoices, 
                         payments, expenses, clients, products, vendors, 
                         adjustments, reports, settings, maintenance ,auth
    )
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(quotes.bp, url_prefix='/quotes')
    app.register_blueprint(purchase_orders.bp, url_prefix='/purchase_orders')
    app.register_blueprint(invoices.bp, url_prefix='/invoices')
    app.register_blueprint(payments.bp, url_prefix='/payments')
    app.register_blueprint(expenses.bp, url_prefix='/expenses')
    app.register_blueprint(clients.bp, url_prefix='/clients')
    app.register_blueprint(products.bp, url_prefix='/products')
    app.register_blueprint(vendors.bp, url_prefix='/vendors')
    app.register_blueprint(adjustments.bp, url_prefix='/adjustments')
    app.register_blueprint(reports.bp, url_prefix='/reports')
    app.register_blueprint(settings.bp, url_prefix='/settings')
    app.register_blueprint(maintenance.bp, url_prefix='/maintenance')
    app.register_blueprint(auth.bp, url_prefix='/auth')

    # 5. Register Jinja Filter
    from .utils.money import format_usd
    @app.template_filter('usd')
    def usd_filter(cents):
        return format_usd(cents)
    
    @app.template_filter('localize')
    def localize_filter(dt):
        """Converts UTC database datetime to Business Timezone."""
        if not dt:
            return None

        tz_name = g.office_tz
        # Ensure the naive datetime from DB is treated as UTC, then convert
        return dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo(tz_name))

    # 6. Error Handling
    @app.errorhandler(SQLAlchemyError)
    def handle_db_error(error):
        # 1. Atomic Safeguard
        # Ensure any partial changes (like a header saved without items) are reverted
        db.session.rollback()
        
        # 2. Log the full traceback for the developer
        logging.error(f"Database Error: {str(error)}", exc_info=True)

        message = "A database error occurred. Your changes were not saved."

        # 3. Contextual Feedback
        if request.headers.get('HX-Request'):
            # HTMX Response: Return an Out-of-Band (OOB) swap
            # This injects the error at the top of the form without refreshing the page
            return render_template('partials/error_notification.html', message=message, category='db'), 200
        else:
            # Standard Response: Flash and redirect to a safe landing spot
            flash(message, "error")
            return redirect(url_for('dashboard.index'))
        
    @app.errorhandler(Exception)
    def handle_generic_error(error):
        db.session.rollback()
        logging.error(f"System Error: {str(error)}", exc_info=True)

        # Use the humanizer for the global net too
        message, category = humanize_error(error)
        
        if request.headers.get('HX-Request'):
            return render_template('partials/error_notification.html', message=message, category='system'), 200
        
        flash(message, "error")
        return redirect(url_for('dashboard.index'))
    
    # 7. Global Context Processors (For now, and Metadata)
    @app.context_processor
    def inject_global_vars():
        """Injects shared variables into every Jinja template."""
        metadata = g.metadata
        now = datetime.now(ZoneInfo(g.office_tz))
        return dict(metadata=metadata, now=now)

    return app