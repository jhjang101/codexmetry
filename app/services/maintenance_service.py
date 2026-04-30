import os
import logging
import subprocess
import csv
import io
from datetime import datetime
from flask import current_app
from sqlalchemy import text
from ..extensions import db
from ..models import Client, Vendor, Product, PurchaseOrder, Invoice, Payment, Expense, Adjustment, SettingsMetadata
from .audit_service import AuditLogService

class MaintenanceService:

    # --- 1. DATABASE MAINTENANCE ---

    @classmethod
    def perform_vacuum(cls):
        """Brain: Reclaims space and updates query statistics for PostgreSQL."""
        try:
            # 1. Use an AUTOCOMMIT connection to bypass transaction locks
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                # 2. Perform VACUUM ANALYZE
                # 'VACUUM' reclaims space; 'ANALYZE' updates the query planner's stats.
                connection.execute(text("VACUUM ANALYZE"))
            
            return True
        except Exception as e:
            # Forensic logging for the developer
            print(f"PostgreSQL Maintenance Error: {str(e)}")
            raise ValueError(f"Database optimization failed: {str(e)}")

    # --- 2. BACKUP & RESTORE ---

    @classmethod
    def get_backup_dir(cls):
        """Ensures the instance/backups directory exists."""
        path = os.path.join(current_app.config['BACKUP_FOLDER'])
        os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def create_backup(cls):
        """Brain: Generates a 'Self-Healing' SQL snapshot using pg_dump."""
        # 1. Pull modular variables directly from environment
        db_user = os.getenv('DB_USER')
        db_password = os.getenv('DB_PASSWORD')
        db_host = os.getenv('DB_HOST')
        db_name = os.getenv('DB_NAME')
        db_port = os.getenv('DB_PORT', '5432')

        if not all([db_user, db_password, db_host, db_name]):
            raise ValueError("Database configuration variables missing for backup.")
        
        # 2. Setup File Identity
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"codexmetry_backup_{timestamp}.sql"
        target_path = os.path.join(cls.get_backup_dir(), filename)

        try:
            # 3. Execute pg_dump
            # PGPASSWORD ensures the process doesn't hang waiting for input
            env = os.environ.copy()
            env['PGPASSWORD'] = db_password or ""
            
            command = [
                'pg_dump',
                '-h', str(db_host),
                '-p', str(db_port),
                '-U', str(db_user),
                '-d', str(db_name),
                '--clean',      # Drops objects before creating
                '--if-exists',  # Prevents errors during drop
                '--no-owner',   # Makes the file portable across different users/PCs
                '-f', target_path
            ]

            result = subprocess.run(command, env=env, capture_output=True, text=True)

            if result.returncode != 0:
                logging.error(f"pg_dump error: {result.stderr}")
                raise ValueError(f"Database dump failed: {result.stderr}")

            return filename

        except Exception as e:
            logging.error(f"Postgres Backup Failure: {str(e)}", exc_info=True)
            raise ValueError(f"Backup failed: {str(e)}")

    @classmethod
    def list_backups(cls):
        """Returns a list of backup files, newest first."""
        directory = cls.get_backup_dir()
        files = []
        for f in os.listdir(directory):
            if f.endswith('.sql'):
                path = os.path.join(directory, f)
                stats = os.stat(path)
                files.append({
                    'filename': f,
                    'size': stats.st_size,
                    'created_at': datetime.fromtimestamp(stats.st_ctime)
                })
        return sorted(files, key=lambda x: x['created_at'], reverse=True)

    @classmethod
    def delete_backup(cls, filename):
        """Safely removes a backup file."""
        target = os.path.join(cls.get_backup_dir(), filename)
        if os.path.exists(target) and os.path.isfile(target):
            os.remove(target)
            return True
        return False

    # --- 3. DATA EXPORT (The Flat Approach) ---

    @classmethod
    def export_to_csv(cls, target_type):
        """
        Brain: Flattens database models into CSV strings.
        Supports Clients, Vendors, Products, and Adjustments.
        """
        output = io.StringIO()
        writer = csv.writer(output)

        if target_type == 'clients':
            writer.writerow(['ID', 'Client Label', 'Address', 'Primary Contact', 'Email', 'Phone'])
            records = db.session.execute(db.select(Client).where(Client.is_active==True)).scalars().all()
            for r in records:
                writer.writerow([r.id, r.company_name, r.address, r.primary_contact_name, r.primary_contact_email, r.primary_contact_phone])

        elif target_type == 'vendors':
            writer.writerow(['ID', 'Vendor Label', 'URL', 'Address', 'Primary Contact', 'Email', 'Phone'])
            records = db.session.execute(db.select(Vendor).where(Vendor.is_active==True)).scalars().all()
            for r in records:
                writer.writerow([r.id, r.company_name, r.url, r.address, r.primary_contact_name, r.primary_contact_email, r.primary_contact_phone])

        elif target_type == 'products':
            writer.writerow(['ID', 'Name', 'Catalog #', 'Category', 'Unit Price', 'Placement'])
            records = db.session.execute(db.select(Product).where(Product.is_active==True)).scalars().all()
            for r in records:
                writer.writerow([r.id, r.name, r.catalog_number, r.category.type if r.category else 'N/A', r.default_unit_price / 100, r.document_placement])

        elif target_type == 'adjustments':
            writer.writerow(['Date', 'Number', 'Category', 'Description', 'Amount'])
            records = db.session.execute(db.select(Adjustment).where(Adjustment.is_active==True)).scalars().all()
            for r in records:
                writer.writerow([r.adjustment_date, r.adjustment_number, r.category.type if r.category else 'N/A', r.description, r.amount / 100])

        return output.getvalue()
    
    # --- 4. MAINTENANCE MODE ---

    @classmethod
    def toggle_maintenance_mode(cls):
        """Brain: Flips the global system lock and records the event."""
        # Fetch the singleton record
        settings = db.session.get(SettingsMetadata, 1)
        if not settings:
            raise ValueError("System settings not initialized. Run seed-db.")

        # Capture old state for the forensic record
        old_mode = settings.is_maintenance_mode
        new_mode = not old_mode

        # Apply change
        settings.is_maintenance_mode = new_mode

        # Record Audit
        AuditLogService.record(
            target_id=1,
            target_type='SettingsMetadata',
            action='UPDATE',
            old_data={'is_maintenance_mode': old_mode},
            new_data={'is_maintenance_mode': new_mode}
        )

        db.session.commit()
        return settings