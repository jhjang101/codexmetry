from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user
from urllib.parse import urlparse
from ..services.auth_service import AuthService

bp = Blueprint('auth', __name__)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handles login requests and session creation."""
    # 1. Guard: If already logged in, go to dashboard
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        # 2. Brain Call: Authenticate via Service
        user = AuthService.authenticate(username, password)

        if user:
            # 3. Success: Create the session
            login_user(user, remember=remember)
            flash(f"Welcome back, {user.username}!", "success")
            
            # Handle the 'next' page redirect (where the user was trying to go)
            next_page = request.args.get('next')
            if not next_page or urlparse(next_page).netloc != '':
                next_page = url_for('dashboard.index')
            
            return redirect(next_page)
        
        # 4. Failure: UI feedback
        flash("Invalid username or password.", "error")

    return render_template('auth/login.html')

@bp.route('/logout')
def logout():
    """Messenger: Destroys the user session."""
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for('auth.login'))