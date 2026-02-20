from functools import wraps
from flask import request, redirect, url_for, flash, render_template
from flask_login import current_user

def role_required(allowed_roles: list[str]):
    """
    Messenger: Decorator to restrict route access based on User.role.
    Handles both standard redirects and HTMX OOB error responses.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. Authorization Logic
            # Check if user is logged in and has one of the required roles
            if not current_user.is_authenticated or current_user.role not in allowed_roles:
                
                message = "Permission Denied: You do not have the required role."

                # 2. Contextual HTMX Response
                if request.headers.get('HX-Request'):
                    # HTMX Case: Return the OOB error partial we created for the Global Error Handler
                    # We Return 200 instead of 403 for HTMX requests
                    # This allows HTMX to read the response and perform the OOB swap
                    return render_template('partials/error_notification.html', message=message), 200
                
                # Standard Case: Flash error and send to dashboard
                flash(message, "error")
                return redirect(url_for('dashboard.index'))
            
            # 3. Success: Proceed to the original route function
            return f(*args, **kwargs)
            
        return decorated_function
    return decorator