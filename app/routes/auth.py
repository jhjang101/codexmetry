from flask import Blueprint, render_template, request, redirect, url_for, flash, make_response
from flask_login import login_user, logout_user, current_user, login_required
from ..services.users_service import UserService
from ..services.auth_service import AuthService
from urllib.parse import urlparse
from ..extensions import db

bp = Blueprint('auth', __name__)

@bp.route('/')
@login_required
def index():
    """Renders the Account Setup page."""
    return render_template('auth/account_setup.html')

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

# --- HTMX change password route ---

@bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Messenger: Strictly handles the POST action for password changes."""
    try:
        current_pw = request.form.get('current_password')
        new_pw = request.form.get('new_password')
        confirm_pw = request.form.get('confirm_password')

        UserService.change_password(
            user_id=int(current_user.get_id()), 
            current_pw=current_pw,  # type: ignore
            new_pw=new_pw,          # type: ignore
            confirm_pw=confirm_pw   # type: ignore
        )

        flash("Your password has been updated successfully.", "success")
        
        # Force a full-page redirect to the dashboard on success
        response = make_response("", 200)
        response.headers['HX-Redirect'] = url_for('dashboard.index')
        return response

    except ValueError as e:
        db.session.rollback()
        # Return the pulse-red banner. The inputs in account_setup.html remain intact.
        resp = make_response(render_template('partials/error_notification.html', message=str(e)), 200)
        resp.headers['HX-Reswap'] = 'none'
        return resp