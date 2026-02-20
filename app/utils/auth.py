from functools import wraps
from flask import request, redirect, url_for, flash, render_template, make_response
from flask_login import current_user

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