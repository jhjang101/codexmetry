import os
from dotenv import load_dotenv
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, make_response
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from zoneinfo import ZoneInfo
from .extensions import db, csrf, login_manager,migrate

def create_app():
    load_dotenv()
    app = Flask(__name__)

    # 1. Configuration
    UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
    INSTANCE_FOLDER = os.path.join(app.root_path, 'instance')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(INSTANCE_FOLDER, exist_ok=True)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-for-local-only')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{INSTANCE_FOLDER}/codexmetry.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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

    from . import models

    # 3. Register Blueprints
    from .routes import (dashboard, quotes, purchase_orders, invoices, 
                         payments, expenses, clients, products, vendors, 
                         adjustments, reports, settings, auth
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
    app.register_blueprint(auth.bp, url_prefix='/auth')

    # 4. Register Jinja Filter
    from .utils.money import format_usd
    @app.template_filter('usd')
    def usd_filter(cents):
        return format_usd(cents)
    
    @app.template_filter('localize')
    def localize_filter(dt):
        """Converts UTC database datetime to Business Timezone."""
        if not dt:
            return None
        
        from .services.settings_service import MetadataService
        metadata = MetadataService.get_by_id(1)
        tz_name = metadata.timezone if metadata else 'America/Chicago'
        
        # Ensure the naive datetime from DB is treated as UTC, then convert
        return dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(ZoneInfo(tz_name))

    # 5. Error Handling
    @app.errorhandler(SQLAlchemyError)
    def handle_db_error(error):
        # 1. Atomic Safeguard
        # Ensure any partial changes (like a header saved without items) are reverted
        db.session.rollback()
        
        # 2. Log the full traceback for the developer
        logging.error(f"SQLAlchemy Error: {str(error)}", exc_info=True)

        message = "A database error occurred. Your changes were not saved."

        # 3. Contextual Feedback
        if request.headers.get('HX-Request'):
            # HTMX Response: Return an Out-of-Band (OOB) swap
            # This injects the error at the top of the form without refreshing the page
            return render_template('partials/error_notification.html', message=message), 200
        else:
            # Standard Response: Flash and redirect to a safe landing spot
            flash(message, "error")
            return redirect(url_for('dashboard.index'))
    
    # 6. Global Context Processors (For now, and Metadata)
    @app.context_processor
    def inject_metadata():
        from .services.settings_service import MetadataService as Metadata
        metadata = Metadata.get_by_id(1)
        tz = metadata.timezone if metadata else 'America/Chicago'
        now = datetime.now(ZoneInfo(tz))
        return dict(metadata=metadata, now=now)

    return app