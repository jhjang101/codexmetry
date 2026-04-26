from sqlalchemy import desc, asc, select
from .audit_service import AuditLogService
from ..extensions import db
from ..utils.money import format_usd

class BaseService:
    model: type = db.Model

    @classmethod
    def get_all(cls):
        stmt = db.select(cls.model).filter_by(is_active=True)
        return db.session.execute(stmt).scalars().all()
    
    @classmethod
    def get_by_id(cls, id):
        return db.get_or_404(cls.model, id)
    
    @classmethod
    def add(cls, **kwargs):
        """Generic add with automated 'CREATE' audit."""
        row = cls.model(**kwargs)
        db.session.add(row)
        db.session.flush() # Secure the ID for the log
        
        # Snapshot of the newborn record
        new_snapshot = cls._get_snapshot(row)
        
        AuditLogService.record(
            target_id=row.id, 
            target_type=cls.model.__name__, 
            action='CREATE', 
            new_data=new_snapshot
        )
        
        db.session.commit()
        return row
    
    @classmethod
    def update(cls, id, **kwargs):
        row = cls.get_by_id(id)
        
        # Capture snapshot for the Audit Messenger
        old_snapshot = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        
        for key, value in kwargs.items():
            if hasattr(row, key):
                setattr(row, key, value)
            
        # Hand off to the Audit Brain
        AuditLogService.record(
            target_id=id, 
            target_type=cls.model.__name__, 
            action='UPDATE', 
            old_data=old_snapshot, 
            new_data=kwargs
        )
        
        db.session.commit()
        return row

    
    @classmethod
    def archive(cls, id):
        """Generic archive with automated 'ARCHIVE' audit."""
        row = cls.get_by_id(id)
        
        # Log the specific lifecycle change
        AuditLogService.record(
            target_id=id, 
            target_type=cls.model.__name__, 
            action='ARCHIVE', 
            old_data={'is_active': True}, 
            new_data={'is_active': False}
        )
        
        row.is_active = False
        db.session.commit()
        return row
    
    @classmethod
    def delete(cls, id):
        row = cls.get_by_id(id)
        db.session.delete(row)
        db.session.commit()
        return row
    
    @classmethod
    def paginate(cls, stmt, page: int = 1, per_page: int = 10, sort_by: str | None = None, direction: str | None = None):
        """
        Generic pagination helper.
        stmt: The SQLAlchemy Select statement
        page: Current page number
        per_page: Number of items per page
        Updated to attach sorting state to the pagination object.
        """
        pagination = db.paginate(stmt, page=page, per_page=per_page, error_out=False)
        # Attach the state so the macro can see it
        pagination.sort_by = sort_by # type: ignore
        pagination.direction = direction # type: ignore
        return pagination
    
    @classmethod
    def apply_sorting(cls, stmt, sort_by: str | None, direction: str | None, whitelist: dict, default_col):
        """
        Securely applies ORDER BY to an SQLAlchemy statement.
        - whitelist: Dictionary mapping URL keys to Model attributes.
          e.g., {'client': Client.company_name, 'total': Invoice.total_amount}
        - default_col: The attribute to sort by if sort_by is invalid/missing.
        """
        # 1. Standardize Direction
        # Default to 'desc' (newest/highest first) if not specified or invalid
        sort_dir = desc if direction == 'desc' else asc

        # 2. Lookup the actual column from the whitelist
        # This acts as our security gate against SQL injection
        target_col = whitelist.get(sort_by)

        # 3. Apply sorting logic
        if target_col is not None:
            # Sort by requested column
            stmt = stmt.order_by(sort_dir(target_col), desc(default_col))
        else:
            # Fallback to default (usually Date or ID descending)
            stmt = stmt.order_by(desc(default_col))

        return stmt

    @classmethod
    def _get_snapshot(cls, model_instance):
        """
        Brain: Generates a dictionary of all current columns for an object.
        Used for audit_logs.
        """
        return {c.name: getattr(model_instance, c.name) for c in model_instance.__table__.columns}
    
    @classmethod
    def _get_items_fingerprint(cls, items_collection, qty_attr, price_attr):
        """
        Brain: Converts a collection of line items into a comparable list.
        Example: [{'product_id': 5, 'quantity': 10, 'unit_price': 500}, ...]
        """
        data = []

        for item in items_collection:
            qty = getattr(item, qty_attr)
            price = getattr(item, price_attr)
            data.append({
                'product': item.product.name if item.product else "Unknown",
                'quantity': qty,
                'unit_price': format_usd(price),
                'line_total': format_usd(qty * price),
                'description': item.description,
                'sort_order': item.sort_order,
            })

        return sorted(data, key=lambda x: x['sort_order'])
    
    @classmethod
    def _get_contacts_fingerprint(cls, contacts_collection):
        """Brain: Converts a collection of contacts into a comparable list."""
        data = []
        for c in contacts_collection:
            data.append({
                'name': f"{c.first_name or ''} {c.last_name or ''}".strip() or "Unnamed Contact",
                'email': c.email or 'No Email',
                'phone': c.phone_number or 'No Phone'
            })
        
        # Sort by name for a predictable, human-readable order in the JSON delta
        return sorted(data, key=lambda x: x['name'])