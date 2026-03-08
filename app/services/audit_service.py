from flask_login import current_user
from flask import has_request_context
from datetime import datetime, date
from ..extensions import db
from ..models import AuditLog
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from ..models import (
    AuditLog, Client, User, PoType, Product, 
    ProductCategory, ExpenseCategory, PurchaseOrder, Invoice, Vendor,
    PaymentType, AdjustmentCategory, OrderRegistry 
)

class AuditLogService:
    # Fields to ignore globally
    BLACKLIST = {'csrf_token', 'updated_at', 'created_at', 'password_hash', 'old_image'}

    # Maps foreign key fields to their Model and identifying Label
    RELATION_MAP = {
        'order_id': (OrderRegistry, 'order_number'),
        'client_id': (Client, 'company_name'),
        'vendor_id': (Vendor, 'company_name'), # Use Client or Vendor model accordingly
        'po_type_id': (PoType, 'type'),
        'category_id': (ProductCategory, 'type'), # Note: We need logic to distinguish between Prod/Exp/Adj categories
        'product_id': (Product, 'name'),
        'po_id': (PurchaseOrder, 'po_number'),
        'invoice_id': (Invoice, 'invoice_number'),
        'user_id': (User, 'username'),
        'bill_to_id': (Client, 'company_name'),
        'paid_from_id': (Client, 'company_name'),
        'payment_type_id': (PaymentType, 'type'),
    }

    @classmethod
    def _resolve_label(cls, field: str, val, target_type: str):
        """Brain: Converts an ID into a human string (e.g., 2 -> 'Standard')."""
        if val is None or val == "" or val == "None":
            return "None"
        
        # 1. Explicit Branching for 'category_id'
        if field == 'category_id':
            label_attr = 'type'
            if target_type == 'Product':
                model_class = ProductCategory
            elif target_type == 'Expense':
                model_class = ExpenseCategory
            elif target_type == 'Adjustment':
                model_class = AdjustmentCategory
            else:
                # If a category_id appears on an unexpected model, return the raw ID
                return val 
        else:
            # 2. Standard Lookup
            map_entry = cls.RELATION_MAP.get(field)
            if not map_entry:
                return val # No map? Return raw ID
            model_class, label_attr = map_entry

        # 3. Database Fetch
        obj = db.session.get(model_class, int(val))
        return getattr(obj, label_attr) if obj else f"Unknown ({val})"

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

        # 1. Forensic Comparison Loop
        for key, new_val in new_data.items():
            if key in cls.BLACKLIST:
                continue

            old_val = old_data.get(key)

            # 2. ID-to-Label Resolution
            if key.endswith('_id') or key in ['client_id', 'vendor_id']:
                norm_old = cls._resolve_label(key, old_val, target_type)
                norm_new = cls._resolve_label(key, new_val, target_type)
            else:
                # Standard JSON Normalization (Dates/Times)
                norm_old = old_val.isoformat() if isinstance(old_val, (date, datetime)) else old_val
                norm_new = new_val.isoformat() if isinstance(new_val, (date, datetime)) else new_val

            # 3. Detect Delta
            if norm_old != norm_new:
                changes[key] = [norm_old, norm_new]

        # 4. Save entry if there's a delta or it's a lifecycle event
        if changes or action in ['CREATE', 'ARCHIVE']:
            user_id = int(current_user.get_id()) if (has_request_context() and current_user.is_authenticated) else None
            

            # Forensic Print for Debugging
            print(f"--- AUDIT LOG: {action} on {target_type} ID {target_id} by User ID {user_id} ---")
            print(f"Changes: {changes}")


            log = AuditLog()
            log.user_id = user_id
            log.action = action
            log.target_type = target_type
            log.target_id = target_id
            log.changes = changes if changes else None
            db.session.add(log)
            # We do NOT commit here. The calling service handles the transaction.

    @classmethod
    def get_for_entity(cls, target_type: str, target_id: int):
        """Brain: Fetches all forensic records for a specific document."""
        stmt = (
            select(AuditLog)
            .options(joinedload(AuditLog.user)) # Eager load the actor
            .where(
                AuditLog.target_type == target_type,
                AuditLog.target_id == target_id
            )
            .order_by(AuditLog.timestamp.desc())
        )
        return db.session.execute(stmt).scalars().all()