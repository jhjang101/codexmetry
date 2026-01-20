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
        for key, value in kwargs.items():
            setattr(row, key, value)
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
    def paginate(cls, stmt, page: int = 1, per_page: int = 10):
        """
        Generic pagination helper.
        stmt: The SQLAlchemy Select statement
        page: Current page number
        per_page: Number of items per page
        """
        # db.paginate is a Flask-SQLAlchemy helper that handles the math
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)
