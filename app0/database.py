import sqlite3
import os
from flask import Flask, g, current_app

# --- DATABASE HELPERS ---

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db_path = current_app.config['DATABASE']
        db_dir = os.path.dirname(db_path)

        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        db = g._database = sqlite3.connect(db_path)
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

def read_db(table_name, active_only=True, id=None, where_clause=None, args=(), one=False):
    """
    Flexible Read function.
    - id: if provided, fetches by ID.
    - where_clause: e.g. "client_id = ?"
    - active_only: filters by is_active = 1
    """
    db = get_db()
    query = f"SELECT * FROM {table_name}"
    conditions = []
    params = list(args)

    if active_only:
        conditions.append("is_active = 1")
    
    if id:
        conditions.append("id = ?")
        params.append(id)
        one = True

    if where_clause:
        conditions.append(where_clause)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    cur = db.execute(query, params)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv

def insert_db(table_name, data: dict):
    """
    Inserts a dictionary into the database.
    Example: create_db('clients', {'company_name': 'Acme', 'address': '123 St'})
    """
    db = get_db()
    columns = ', '.join(data.keys())
    placeholders = ', '.join(['?' for _ in data])
    sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

    cur = db.execute(sql, list(data.values()))
    db.commit()
    return cur.lastrowid

def update_db(table_name, id: int, data: dict):
    """
    Updates a record by ID using a dictionary.
    Example: update_db('clients', 5, {'address': 'New Address'})
    """
    db = get_db()
    # Build string: "col1 = ?, col2 = ?"
    set_clause = ', '.join([f"{k} = ?" for k in data.keys()])
    sql = f"UPDATE {table_name} SET {set_clause} WHERE id = ?"
    
    params = list(data.values()) + [id]
    db.execute(sql, params)
    db.commit()
    return True

def archive_db(table_name, id: int):
    """Soft delete helper (PRD 4.2)"""
    return update_db(table_name, id, {'is_active': 0})

    
def delete_db(table_name, id=None, where_clause=None, args=()):
    """
    Hard delete helper. 
    Supports deleting by id OR a custom where clause.
    """
    db = get_db()
    query = f'DELETE FROM "{table_name}"'
    params = []

    if id:
        query += " WHERE id = ?"
        params = [id]
    elif where_clause:
        query += f" WHERE {where_clause}"
        params = args

    db.execute(query, params)
    db.commit()
    return True

  

def get_clients_with_contacts():
    """
    Fetches all active clients and joins the first contact found for each.
    Matches the PRD requirements for the Table View.
    """
    db = get_db()
    # This query gets the client and the 'first' contact associated with them
    sql = """
        SELECT 
            c.id, 
            c.company_name, 
            c.address,
            cc.first_name, 
            cc.last_name, 
            cc.email
        FROM clients c
        LEFT JOIN client_contacts cc ON cc.id = (
            SELECT id FROM client_contacts 
            WHERE client_id = c.id 
            LIMIT 1
        )
        WHERE c.is_active = 1
        ORDER BY c.company_name ASC
    """
    return db.execute(sql).fetchall()

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
