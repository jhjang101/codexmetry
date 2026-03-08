from flask_login import current_user
from flask import has_request_context
from datetime import datetime, date
from ..extensions import db
from ..models import AuditLog

class AuditLogService:
    # Fields to ignore globally
    BLACKLIST = {'csrf_token', 'updated_at', 'created_at', 'password_hash', 'old_image'}

    @classmethod
    def record(cls, 
               target_id: int, 
               target_type: str, 
               action: str, 
               old_data: dict | None = None, 
               new_data: dict | None = None):
        """
        Brain: Compares old vs new data and records a deep audit log.
        """
        changes = {}
        old_data = old_data or {}
        new_data = new_data or {}

        # 1. Forensic Comparison
        for key, new_val in new_data.items():
            if key in cls.BLACKLIST:
                continue

            old_val = old_data.get(key)

            # 2. JSON Normalization (Dates/Times to ISO strings)
            norm_old = old_val.isoformat() if isinstance(old_val, (date, datetime)) else old_val
            norm_new = new_val.isoformat() if isinstance(new_val, (date, datetime)) else new_val

            # 3. Detect Delta
            if norm_old != norm_new:
                changes[key] = [norm_old, norm_new]

        # 4. Save entry if there's a delta or it's a lifecycle event
        if changes or action in ['CREATE', 'ARCHIVE']:
            user_id = int(current_user.get_id()) if (has_request_context() and current_user.is_authenticated) else None
            

            # Forensic Print for Debugging
            print(f"--- AUDIT LOG: {action} on {target_type} ID {target_id} by User {user_id} ---")
            print(f"Changes: {changes}")



            log = AuditLog()
            log.user_id=user_id
            log.action=action
            log.target_type=target_type
            log.target_id=target_id
            log.changes=changes if changes else None

            db.session.add(log)
            # We do NOT commit here. The calling service handles the transaction.