import os
from flask import Flask, render_template
from .extensions import db, csrf, login_manager
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from zoneinfo import ZoneInfo

def create_app():
    app = Flask(__name__)

    # 1. Configuration
    UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
    INSTANCE_FOLDER = os.path.join(app.root_path, 'instance')
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(INSTANCE_FOLDER, exist_ok=True)
    app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{INSTANCE_FOLDER}/codexmetry.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

    # 2. Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    from . import models

    # 3. Register Blueprints
    from .routes import (dashboard, quotes, purchase_orders, invoices, 
                         payments, expenses, clients, products, vendors, 
                         transactions, reports, settings)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(quotes.bp, url_prefix='/quotes')
    app.register_blueprint(purchase_orders.bp, url_prefix='/purchase_orders')
    app.register_blueprint(invoices.bp, url_prefix='/invoices')
    app.register_blueprint(payments.bp, url_prefix='/payments')
    app.register_blueprint(expenses.bp, url_prefix='/expenses')
    app.register_blueprint(clients.bp, url_prefix='/clients')
    app.register_blueprint(products.bp, url_prefix='/products')
    app.register_blueprint(vendors.bp, url_prefix='/vendors')
    app.register_blueprint(transactions.bp, url_prefix='/transactions')
    app.register_blueprint(reports.bp, url_prefix='/reports')
    app.register_blueprint(settings.bp, url_prefix='/settings')

    # 4. Error Handling
    @app.errorhandler(SQLAlchemyError)
    def handle_db_error(error):
        db.session.rollback()
        # In the future, we can return an HTMX-specific error snippet
        return render_template('error.html', error="A database error occurred."), 500
    
    # 5. Global Context Processors (For now, and Metadata)
    @app.context_processor
    def inject_metadata():
        from .services.settings_service import MetadataService as Metadata
        metadata = Metadata.get_by_id(1)
        tz = metadata.timezone if metadata else 'America/Chicago'
        now = datetime.now(ZoneInfo(tz))
        return dict(metadata=metadata, now=now)

    return app