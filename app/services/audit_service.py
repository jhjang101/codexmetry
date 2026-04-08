from flask_login import current_user
from flask import has_request_context
from datetime import datetime, date
from ..extensions import db
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from ..models import (
    AuditLog, User, PoType, ProductCategory, ExpenseCategory, 
    Quote, PurchaseOrder, Invoice, Payment, Product, Vendor, Client,
    PaymentType, AdjustmentCategory, OrderRegistry , Carrier,
    Expense, Adjustment, SettingsMetadata
)

class AuditLogService:
    # Fields to ignore globally
    BLACKLIST = {
        'csrf_token', 'updated_at', 'created_at', 'password_hash', 'old_image',
        'id',               # Hide primary keys
        'created_by_id',    # Hide metadata link
        'updated_by_id',    # Hide metadata link
        'is_active',        # Handled by ARCHIVE action
        'is_system'         # Internal logic flag
    }

    # Maps foreign key fields to their Model and identifying Label
    RELATION_MAP = {
        'order_id': (OrderRegistry, 'order_number'),
        'client_id': (Client, 'company_name'),
        'vendor_id': (Vendor, 'company_name'), # Use Client or Vendor model accordingly
        'po_type_id': (PoType, 'type'),
        # 'category_id': (ProductCategory, 'type'), # Note: We need logic to distinguish between Prod/Exp/Adj categories
        'product_id': (Product, 'name'),
        'quote_id': (Quote, 'quote_number'),
        'po_id': (PurchaseOrder, 'po_number'),
        'invoice_id': (Invoice, 'invoice_number'),
        'user_id': (User, 'username'),
        'bill_to_id': (Client, 'company_name'),
        'paid_from_id': (Client, 'company_name'),
        'payment_type_id': (PaymentType, 'type'),
        'adjustment_category_id': (AdjustmentCategory, 'type'),
        'carrier_id': (Carrier, 'type'),
        'created_by_id': (User, 'username'),
        'updated_by_id': (User, 'username')
    }

    # Maps target_type string to the imported Model Class
    MODEL_MAP = {
        'Quote': Quote, 
        'PurchaseOrder': PurchaseOrder, 
        'Invoice': Invoice,
        'Payment': Payment, 
        'Expense': Expense, 
        'Adjustment': Adjustment,
        'OrderRegistry': OrderRegistry, 
        'Client': Client, 
        'Vendor': Vendor,
        'Product': Product, 
        'User': User, 
        'SettingsMetadata': SettingsMetadata
    }


    # Maps target_type to the column we use for the human label
    TARGET_MAP = {
        'Quote': 'quote_number',
        'PurchaseOrder': 'po_number', # or we can logic-fallback to order.order_number
        'Invoice': 'invoice_number',
        'Payment': 'payment_number',
        'Expense': 'expense_number',
        'Adjustment': 'adjustment_number',
        'OrderRegistry': 'order_number',
        'Client': 'company_name',
        'Vendor': 'company_name',
        'Product': 'name',
        'User': 'username',
        'SettingsMetadata': 'company_name'
    }    

    @classmethod
    def _resolve_label(cls, field: str, val, target_type: str):
        """Brain: Converts an ID into a human string (e.g., 2 -> 'Standard')."""
        if val is None or val == "" or val == "None":
            return "None"
        
        # If 'val' is already a string (like 'CDX-123'), don't try to look it up.
        # Just return it as is.
        if isinstance(val, str) and not val.isdigit():
            return val
        
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
        try:
            obj = db.session.get(model_class, int(val))
            return getattr(obj, label_attr) if obj else f"Unknown ({val})"
        except (ValueError, TypeError):
            return str(val) # Final fallback: return it as a string

    @classmethod
    def record(cls, 
               target_id: int, 
               target_type: str, 
               action: str, 
               old_data: dict | None = None, 
               new_data: dict | None = None,
               parent_id: int | None = None):
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
        if changes or action in ['CREATE', 'ARCHIVE', 'DELETE']:
            user_id = int(current_user.get_id()) if (has_request_context() and current_user.is_authenticated) else None

            # Fetch the object to get the Label and the Order ID
            model_class = cls.MODEL_MAP.get(target_type)
            label_attr = cls.TARGET_MAP.get(target_type)
            obj = db.session.get(model_class, target_id) if model_class else None

            # 1. RESOLVE ORDER ID (The Order Anchor)
            # If the target is the OrderRegistry itself, its own ID is the anchor.
            # Otherwise, check for the order_id attribute.
            found_order_id = None
            if obj:
                if target_type == 'OrderRegistry':
                    found_order_id = obj.id
                else:
                    found_order_id = getattr(obj, 'order_id', None)

            # 2. GENERATE THE TARGET LABEL
            target_label = f"{target_type} #{target_id}" # Default fallback

            if obj and label_attr:
                val = getattr(obj, label_attr, None)
                    
                # SPECIAL CASE: PO Number Fallback
                # If client PO ref is blank, use the CDX number for historical clarity
                if target_type == 'PurchaseOrder' and not val:
                    val = obj.order.order_number if obj.order else f"#{target_id}"
                
                if val:
                    target_label = str(val)
            

            # 3. Forensic Print for Debugging
            import pprint
            user_name = current_user.username if (has_request_context() and current_user.is_authenticated) else 'Anonymous'
            print(f"--- AUDIT LOG: {action} on {target_type} [{target_label}] by User {user_name} ---")
            if changes: pprint.pprint(changes, indent=4)
            print("----------------")

            log = AuditLog()
            log.user_id = user_id
            log.parent_id = parent_id # Assign the parent link
            log.action = action
            log.target_type = target_type
            log.target_id = target_id
            log.target_label = target_label
            log.changes = changes if changes else None
            log.order_id = found_order_id

            db.session.add(log) # We do NOT commit here. The calling service handles the transaction.

            # Secure the ID for return without ending the transaction
            db.session.flush() 
            return log.id
        
        return None # Return None if no log was created


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
    
    @classmethod
    def get_for_order(cls, order_id: int):
        """
        Brain: Fetches every log entry tagged with this order_id.
        Used for order-tree
        """
        stmt = (
            select(AuditLog)
            .options(joinedload(AuditLog.user))
            .where(AuditLog.order_id == order_id)
            .order_by(AuditLog.timestamp.desc())
        )
        return db.session.execute(stmt).scalars().all()