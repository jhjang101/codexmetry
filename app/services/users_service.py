from ..models import User
from ..extensions import db
from .base_service import BaseService
from sqlalchemy import select, or_, func

class UserService(BaseService):
    model = User

    @classmethod
    def get_all(cls):
        """Returns all users ordered by username (includes inactive)."""
        stmt = select(cls.model).order_by(cls.model.username.asc())
        return db.session.execute(stmt).scalars().all()

    @classmethod
    def add_user(cls, data: dict) -> User:
        """Brain: Creates a new user after validation."""
        # 1. Standardized Transform & Validate
        clean_data = cls._validate_and_transform(data, is_new=True)

        # 2. Extract password (handled separately from header dict because it requires hashing)
        password = data.get('password')
        
        # 3. Initialize and set password
        user = cls.model(**clean_data)
        user.set_password(password) # Using the User model's hash method
        
        db.session.add(user)
        db.session.commit()
        return user

    @classmethod
    def update_user(cls, user_id: int, data: dict) -> User:
        """Brain: Updates user profile and optionally resets password."""
        user = cls.get_by_id(user_id)
        
        # 1. Standardized Transform & Validate
        clean_data = cls._validate_and_transform(data, is_new=False, current_user_id=user_id)

        # 2. Update standard attributes
        for key, value in clean_data.items():
            setattr(user, key, value)
        
        # 3. Conditional Password Update
        new_password = data.get('password')
        if new_password and new_password.strip():
            user.set_password(new_password)

        db.session.commit()
        return user
    
    @classmethod
    def toggle_status(cls, user_id: int):
        """Brain: Enables/Disables account without deleting historical data."""
        user = cls.get_by_id(user_id)
        
        # Safety Guard: Prevent lockout if only one admin exists
        if user.role == 'admin' and user.is_active:
            admin_count = db.session.query(func.count(cls.model.id)).filter_by(role='admin', is_active=True).scalar()
            if admin_count <= 1:
                raise ValueError("Cannot deactivate the only remaining active Administrator.")

        user.is_active = not user.is_active
        db.session.commit()
        return user
    
    @classmethod
    def change_password(cls, user_id: int, current_pw: str, new_pw: str, confirm_pw: str):
        """
        Brain: Verifies the old password and updates to a new one.
        Raises ValueError for any security or matching failures.
        """
        # 1. Verification: Mandatory fields
        if not current_pw or not new_pw or not confirm_pw:
            raise ValueError("All password fields are required.")

        # 2. Verification: New passwords must match
        if new_pw != confirm_pw:
            raise ValueError("New password and confirmation do not match.")
        
        # 3. Identity Check: Fetch the user
        user = cls.get_by_id(user_id)

        # 4. Security Guard: Verify the existing password
        # This prevents someone from changing a password on a left-open session
        if not user.check_password(current_pw):
            raise ValueError("Current password is incorrect.")

        # 5. Update: Hash and save the new password
        user.set_password(new_pw)
        db.session.commit()
        
        return user

    # --- INTERNAL HELPERS ---

    @classmethod
    def _validate_and_transform(cls, data: dict, is_new: bool = True, current_user_id: int | None = None) -> dict:
        """Standardized validation and cleaning logic."""
        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        role = data.get('role', 'viewer').strip()

        # 1. Mandatory Fields
        if is_new and (not username or not email or not data.get('password')):
            raise ValueError("Username, email, and password are required for new accounts.")
        
        if not is_new and not email:
            raise ValueError("Email is required.")

        # 2. Unique Constraints Guard
        # Check if username or email is taken by someone ELSE
        unique_stmt = select(cls.model).where(
            or_(cls.model.username == username, cls.model.email == email)
        )
        if current_user_id:
            unique_stmt = unique_stmt.where(cls.model.id != current_user_id)
        
        if db.session.execute(unique_stmt).first():
            raise ValueError("Username or Email is already registered to another user.")

        # 3. Role Whitelist Guard
        if role not in ['admin', 'user', 'viewer']:
            role = 'viewer'

        # 4. Return clean dictionary
        clean = {
            'full_name': data.get('full_name', '').strip(),
            'email': email,
            'phone_number': data.get('phone_number', '').strip(),
            'role': role
        }
        
        # Username is typically immutable in many ERPs after creation
        if is_new:
            clean['username'] = username
            
        return clean