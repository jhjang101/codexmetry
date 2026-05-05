import logging
import json
from flask_login import current_user
from flask import has_request_context
from datetime import datetime, date
from ..extensions import db
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
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
        # 'category_id' is shared with ProductCategory, ExpenseCategory, and AdjustmentCategory. It is revolved in _resolve_label
        'order_id': OrderRegistry,
        'client_id': Client,
        'vendor_id': Vendor,
        'po_type_id': PoType,
        'product_id': Product,
        'quote_id': Quote,
        'po_id': PurchaseOrder,
        'invoice_id': Invoice,
        'user_id': User,
        'bill_to_id': Client,
        'paid_from_id': Client,
        'payment_type_id': PaymentType,
        'carrier_id': Carrier,
        'created_by_id': User,
        'updated_by_id': User
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
        'SettingsMetadata': SettingsMetadata,
        'PoType': PoType,
        'ProductCategory': ProductCategory,
        'ExpenseCategory': ExpenseCategory,
        'PaymentType': PaymentType,
        'AdjustmentCategory': AdjustmentCategory,
        'Carrier': Carrier
    }

    @classmethod
    def _resolve_label(cls, field: str, val, target_type: str, cache: dict):
        """
        Brain: Converts an ID into a human string (e.g., 2 -> 'Standard').
        Performance: Uses identity_cache to prevent N+1 queries during bulk saves.
        """
        if val is None or val == "" or val == "None":
            return "None"
        
        # If 'val' is already a string (like 'CDX-123'), don't try to look it up.
        # Just return it as is.
        if isinstance(val, str) and not val.isdigit():
            return val
        
        # 1. Determine Model Class 
        # Explicit Branching for 'category_id'
        if field == 'category_id':
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
            # Standard Lookup
            model_class = cls.RELATION_MAP.get(field)
            if not model_class:
                return val # No map? Return raw ID
        
        # 2. Check Scoped Cache (lives for one record() call)
        cache_key = (model_class, int(val))
        if cache_key in cache:
            return cache[cache_key]

        # 3. Database Fetch
        try:
            obj = db.session.get(model_class, int(val))
            if obj:
                # Use the new __identity_attr__ metadata from models.py
                label_attr = getattr(model_class, '__identity_attr__', 'id')
                label = str(getattr(obj, label_attr))

                # Special Case: PO Fallback (Use CDX if PO Number is blank)
                if field == 'po_id' and not label:
                    label = obj.order.order_number if obj.order else f"#{val}" # type: ignore
            else:
                label = f"Unknown ({val})"
            
            # Store in cache and return
            cache[cache_key] = label
            return label
        
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
        
        # Initialize Scoped Identity Cache for this recording event
        identity_cache = {}

        # 1. Forensic Comparison Loop
        for key, new_val in new_data.items():
            if key in cls.BLACKLIST:
                continue

            old_val = old_data.get(key)

            # 2. ID-to-Label Resolution (Cached)
            if key.endswith('_id') or key in ['client_id', 'vendor_id']:
                norm_old = cls._resolve_label(key, old_val, target_type, identity_cache)
                norm_new = cls._resolve_label(key, new_val, target_type, identity_cache)
            else:
                # Standard JSON Normalization (Dates/Times)
                norm_old = old_val.isoformat() if isinstance(old_val, (date, datetime)) else old_val
                norm_new = new_val.isoformat() if isinstance(new_val, (date, datetime)) else new_val

            # 3. Detect Delta
            if norm_old != norm_new:
                changes[key] = [norm_old, norm_new]

        # 4. Save entry if there's a delta or it's a lifecycle event
        if changes or action in ['CREATE', 'ISSUE', 'ARCHIVE', 'DELETE']:
            user_id = int(current_user.get_id()) if (has_request_context() and current_user.is_authenticated) else None

            # Fetch class for metadata retrieval
            model_class = cls.MODEL_MAP.get(target_type)
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
            if obj and model_class:
                label_attr = getattr(model_class, '__identity_attr__', None)
                if label_attr:
                    val = getattr(obj, label_attr, None)
                    
                # SPECIAL CASE: PO Number Fallback
                # If client PO ref is blank, use the CDX number for historical clarity
                if target_type == 'PurchaseOrder' and not val:
                    val = obj.order.order_number if obj.order else f"#{target_id}"
                
                if val:
                    target_label = str(val)
            

            # # 3. Forensic Print for Debugging
            # import pprint
            # user_name = current_user.username if (has_request_context() and current_user.is_authenticated) else 'Anonymous'
            # print(f"--- AUDIT LOG: {action} on {target_type} [{target_label}] by User {user_name} ---")
            # if changes: pprint.pprint(changes, indent=4)
            # print("----------------")

            # 3. Forensic File Logging (The Black Box)
            user_name = current_user.username if (has_request_context() and current_user.is_authenticated) else 'Anonymous'
            
            # Prepare a single-line structured string for easy parsing/searching
            # Format: USER | ACTION | TARGET [LABEL] | ID | CHANGES
            log_payload = {
                "user": user_name,
                "action": action,
                "type": target_type,
                "label": target_label,
                "id": target_id,
                "changes": changes if changes else None
            }
            
            # Write to the rotating file
            logger = logging.getLogger('audit_engine')
            logger.info(json.dumps(log_payload))

            # 4. Database Recording
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
            .options(joinedload(AuditLog.user))
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
        Brain: Fetches 'Root' log entries (User Actions) and 
        pre-loads their system ripples (Children).
        """
        stmt = (
            select(AuditLog)
            .options(
                joinedload(AuditLog.user),
                # Efficiently pre-load the next level of the tree
                selectinload(AuditLog.children).joinedload(AuditLog.user)
            )
            .where(
                AuditLog.order_id == order_id,
                AuditLog.parent_id == None # Get only the starting actions
            )
            .order_by(AuditLog.timestamp.desc())
        )
        return db.session.execute(stmt).scalars().all()