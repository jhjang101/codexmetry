from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
BASE_DIR = app.root_path
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{BASE_DIR}/test.db'
db = SQLAlchemy(app)

class PoType(db.Model):
    __tablename__ = 'po_types'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Integer, nullable=False, default=1)

if __name__ == "__main__":
    with app.app_context():
        # Optional but recommended
        db.create_all()

        # Insert
        new_entry = PoType(name='Internal Order')
        db.session.add(new_entry)
        db.session.commit()

        # Query
        all_types = PoType.query.filter_by(is_active=1).all()

        for t in all_types:
            print(t.name)
