import os
import logging
from functools import wraps
from flask import request, redirect, url_for, flash, render_template, make_response
from flask_login import current_user
from ..models import User
from ..extensions import db

def role_required(allowed_roles: list[str]):
    """
    Messenger: Decorator to restrict route access based on User.role.
    Handles both standard redirects and HTMX OOB error responses.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if user is logged in and has one of the required roles
            if not current_user.is_authenticated or current_user.role not in allowed_roles:
                message = "Permission Denied: You do not have the required role."

                # 1. Determine where to send them back to
                target = request.referrer
                if not target or target == request.url:
                    target = url_for('dashboard.index')

                flash(message, "error")

                # 2. Contextual HTMX Response
                if request.headers.get('HX-Request'):
                    # 1. Use HX-Redirect instead of render_template
                    # 2. This forces the browser to refresh the page they were just on
                    # 3. The 'flash' message will appear after the refresh
                    response = make_response("", 200)
                    response.headers['HX-Redirect'] = target
                    return response
                
                # Standard Case: send to referrer page
                return redirect(target)
            
            # Success: Proceed to the original route function
            return f(*args, **kwargs)
            
        return decorated_function
    return decorator

def init_auth_loaders(login_manager):
    """
    Identity Hub: Configures how Flask-Login finds users.
    Handles both standard Session cookies and SSO Request headers.
    Login bapass requirs: Email Header + Trusted Proxy + Secret Header.
    """

    # 1. Standard Session Loader (Used for standard login)
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # 2. SSO / Request Loader (Used for Cloudflare Tunnel path)
    @login_manager.request_loader
    def load_user_from_request(request):
        # A. Configuration Guard: Skip if SSO is not set up in .env
        trusted_proxies_raw = os.getenv('TRUSTED_PROXIES')
        sso_secret = os.getenv('SSO_SECRET')
        if not trusted_proxies_raw or not sso_secret:
            return None

        # B. Secret Handshake Guard: Only trust if the Cloudflare Tunnel secret matches.
        # This prevents LAN users from spoofing the email header.
        header_name = os.getenv('SSO_HEADER_NAME', 'X-Codexmetry-Secret')
        incoming_secret = request.headers.get(header_name)
        if not incoming_secret or incoming_secret != sso_secret:
            # This is likely a local LAN request; fallback to standard login.
            return None

        # C. Identity Evidence: Extract the Cloudflare verified email
        user_email = request.headers.get('Cf-Access-Authenticated-User-Email')
        if not user_email:
            return None

        # D. Source Verification Guard: Ensure the request came from your local Nginx/NPM
        trusted_proxies = [ip.strip() for ip in trusted_proxies_raw.split(',')]
        if request.remote_addr not in trusted_proxies:
            logging.warning(f"Unauthorized SSO attempt from {request.remote_addr} for {user_email}")
            return None

        # Database Resolution: Resolve the user from the database
        from ..services.auth_service import AuthService
        return AuthService.authenticate_by_email(user_email)