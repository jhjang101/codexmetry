from sqlalchemy import desc, asc, select
from .audit_service import AuditLogService
from ..extensions import db

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
        row = cls.model(**kwargs)
        db.session.add(row)
        db.session.commit()
        return row  
    
    @classmethod
    def update(cls, id, **kwargs):
        row = cls.get_by_id(id)
        
        # Capture snapshot for the Audit Messenger
        old_snapshot = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        
        for key, value in kwargs.items():
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
        row = cls.get_by_id(id)
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
            stmt = stmt.order_by(sort_dir(target_col))
        else:
            # Fallback to default (usually Date or ID descending)
            stmt = stmt.order_by(desc(default_col))

        return stmt
