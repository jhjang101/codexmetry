import logging
from flask import render_template, make_response
from sqlalchemy.exc import SQLAlchemyError
from ..extensions import db

def humanize_error(e):
    """Brain: Categorizes errors and provides clean messages for the UI."""
    raw_msg = str(e)
    if isinstance(e, ValueError):
        category = 'value'
    elif isinstance(e, SQLAlchemyError):
        category = 'db'
    else:
        category = 'system'

    # 1. If the message is concise (under 100 chars), return it directly.
     # Custom ValueErrors usually fall here
    if len(raw_msg) < 100 or category == 'value':
        return raw_msg, category
    
    # 2. If the message is long/ugly, perform surgical humanization.   
    if category == 'db':
        err_msg = raw_msg.lower()
        if 'duplicate key value violates unique constraint' in err_msg:
            return "Collision Detected: This document number is already in use. Please refresh the form to get a new suggestion.", category
        if 'unique constraint failed' in err_msg:
            return "This identifier (Number, Email, Catalog #,...) is already in use.", category
        if 'not null constraint failed' in err_msg:
            return "A required field is missing information.", category
        if 'foreign key constraint failed' in err_msg:
            return "This record is linked to other data and cannot be modified.", category
        
        # Default for unhandled long DB errors
        return "A database storage error occurred.", category
        
    # 3. Fallback for long System Errors (e.g. Tracebacks)
    return f"A system logic error occurred: {type(e).__name__}", category

def handle_post_error(e, endpoint_name="Unknown"):
    """Messenger Helper: The unified 'Safe Save' failure path."""
    # 1. Atomic Safeguard
    db.session.rollback()
    
    # 2. Forensic Logging (Ugly error goes to terminal)
    logging.error(f"POST Error in {endpoint_name}: {str(e)}", exc_info=True)
    
    # 3. UI Preparation (Clean error goes to user)
    message, category = humanize_error(e)
    
    # 4. HTMX Response Construction
    resp = make_response(render_template('partials/error_notification.html', 
                                       message=message, 
                                       category=category), 200)
    resp.headers['HX-Reswap'] = 'none' # Preserve user input
    return resp