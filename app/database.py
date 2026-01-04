import sqlite3
import os
from flask import Flask, g

DATABASE = 'instance/codexmetry.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        if not os.path.exists('instance'):
            os.makedirs('instance')
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON;')
    return db

def init_db(app: Flask):
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r') as f:
            cursor = db.cursor()
            cursor.executescript(f.read())

        # Seed Settings Metadata if it doesn't exist
        cursor.execute('''
                INSERT OR IGNORE INTO settings_metadata 
                (id, company_name)
                VALUES (1, 'My Business')
            ''')
        db.commit()

# --- MONEY HELPERS ---

def format_usd(cents: int) -> str:
    """Converts integer cents to string $1,234.56"""
    if cents is None:
        return "$0.00"
    dollars = cents / 100
    return f"${dollars:,.2f}"

def parse_to_cents(usd_string: str) -> int:
    """Converts string 1,234.56 to integer cents"""
    if not usd_string:
        return 0
    try:
        # Remove $ and commas
        clean_str = str(usd_string).replace('$', '').replace(',', '').strip()
        dollars = float(clean_str)
        cents = int(round(dollars * 100))
        return cents
    except (ValueError, TypeError):
        return 0
