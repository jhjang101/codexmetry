from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import MetaData

# 1. Define the Naming Convention (Postgres Requirement)
convention = {
    "ix": 'ix_%(column_0_label)s',  # Index
    "uq": "uq_%(table_name)s_%(column_0_name)s",    # Unique Constraint
    "ck": "ck_%(table_name)s_%(constraint_name)s",  # Check Constraint
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",    # Foreign Key
    "pk": "pk_%(table_name)s"       # Primary Key
}

metadata = MetaData(naming_convention=convention)

# 2. Initialize with metadata
db = SQLAlchemy(metadata=metadata)
csrf = CSRFProtect()
login_manager = LoginManager()
migrate = Migrate()