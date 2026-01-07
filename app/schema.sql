-- schema.sql

-- 1. LOOKUP & META TABLES
CREATE TABLE IF NOT EXISTS po_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS product_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS expense_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payment_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS transaction_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS settings_metadata (
    id INTEGER PRIMARY KEY CHECK (id = 1), -- Enforce single row
    company_name TEXT DEFAULT 'My Business',
    address TEXT,
    company_logo TEXT,
    timezone TEXT DEFAULT 'America/Chicago',
    invoice_threshold INTEGER DEFAULT 10000, -- Stored in cents
    doc_padding INTEGER DEFAULT 4
);

-- 2. MASTER DATA
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    address TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS client_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    catalog_number TEXT,
    category_id INTEGER,
    image TEXT,
    default_unit_price INTEGER DEFAULT 0, -- Cents
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (category_id) REFERENCES product_categories(id)
);

CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    url TEXT,
    address TEXT,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS vendor_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
);

-- 3. SALES & FINANCIALS (The Registry)
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT UNIQUE NOT NULL, -- ON-YY0000
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    client_id INTEGER NOT NULL,
    bill_to_id INTEGER NOT NULL,
    po_number TEXT, -- Client's reference
    po_date DATE,
    po_type_id INTEGER,
    status TEXT DEFAULT 'open', -- open, completed
    note TEXT,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (client_id) REFERENCES clients(id),
    FOREIGN KEY (bill_to_id) REFERENCES clients(id),
    FOREIGN KEY (po_type_id) REFERENCES po_types(id)
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    po_id INTEGER NOT NULL,
    client_id INTEGER NOT NULL,
    bill_to_id INTEGER NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_date DATE,
    tracking_number TEXT,
    status TEXT DEFAULT 'open',
    note TEXT,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id),
    FOREIGN KEY (client_id) REFERENCES clients(id),
    FOREIGN KEY (bill_to_id) REFERENCES clients(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL,
    invoice_id INTEGER,
    client_id INTEGER NOT NULL,
    paid_from_id INTEGER NOT NULL,
    payment_type_id INTEGER,
    amount INTEGER NOT NULL, -- Cents
    payment_date DATE,
    note TEXT,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id),
    FOREIGN KEY (client_id) REFERENCES clients(id),
    FOREIGN KEY (paid_from_id) REFERENCES clients(id),
    FOREIGN KEY (payment_type_id) REFERENCES payment_types(id)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_number TEXT UNIQUE NOT NULL, -- EN-YY0000
    vendor_id INTEGER,
    category_id INTEGER,
    expense_date DATE,
    note TEXT,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    FOREIGN KEY (category_id) REFERENCES expense_categories(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_number TEXT UNIQUE NOT NULL, -- TR-YY0000
    description TEXT,
    amount INTEGER NOT NULL, -- Cents
    transaction_date DATE,
    category_id INTEGER,
    note TEXT,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (category_id) REFERENCES transaction_categories(id)
);

-- 4. ITEMS & UTILITIES
CREATE TABLE IF NOT EXISTS po_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER DEFAULT 1,
    agreed_unit_price INTEGER DEFAULT 0, -- Cents
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) -- No cascade here! (We want to keep the product)
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER DEFAULT 1,
    billed_unit_price INTEGER DEFAULT 0, -- Cents
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) -- No cascade here! (We want to keep the product)
);

CREATE TABLE IF NOT EXISTS expense_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    item TEXT NOT NULL,
    quantity INTEGER DEFAULT 1,
    unit_price INTEGER DEFAULT 0, -- Cents
    FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL, -- 'PO', 'Invoice', 'Payment', 'Expense', 'Transaction'
    entity_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);