from ..models import User
from sqlalchemy import select
from ..extensions import db

class AuthService:
    @classmethod
    def authenticate(cls, username, password) -> User | None:
        """
        Validates credentials and account status.
        Returns the User object if successful, otherwise None.
        """
        if not username or not password:
            return None

        # 1. Identity Lookup: Fetch user by username using SA 2.0 syntax
        stmt = select(User).where(User.username == username)
        user = db.session.execute(stmt).scalar_one_or_none()

        # 2. Security Guard: Check if user exists and account is enabled
        if not user or not user.is_active:
            return None

        # 3. Cryptographic Guard: Verify the provided password against the hash
        # This uses the check_password method defined in models.py
        if not user.check_password(password):
            return None

        return user
    
    @classmethod
    def authenticate_by_email(cls, email: str) -> User | None:
        """
        SSO Bridge: Looks up a user by verified email from a trusted proxy.
        """
        if not email:
            return None

        # Standard identity lookup (SA 2.0 syntax)
        stmt = select(User).where(User.email == email, User.is_active == True)
        user = db.session.execute(stmt).scalar_one_or_none()
        return user