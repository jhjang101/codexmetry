import click
import os
from flask.cli import with_appcontext
from ..extensions import db
from ..models import SettingsMetadata, ProductCategory, Product, User
from sqlalchemy import select

@click.command('seed-db')
@with_appcontext
def seed_db_command():
    """Ensures vital system records exist."""
    
    # 1. Seed Metadata (ID 1)
    if not db.session.get(SettingsMetadata, 1):
        seed = SettingsMetadata()
        seed.id = 1
        seed.company_name = "CODEXMETRY"

        db.session.add(seed)
        click.echo("Settings seeded successfully.")

    # 2. Seed System Category (SYS-DEP)
    system_category = db.session.execute(
        select(ProductCategory).filter_by(is_system=True)
    ).scalar_one_or_none()

    if not system_category:
        system_category = ProductCategory()
        system_category.id = 1
        system_category.type='SYS-DEP'
        system_category.is_revenue=False # Deposits are not revenue until spent
        system_category.is_system=True

        db.session.add(system_category)
        click.echo("System Category 'SYS-DEP' seeded successfully.")

    # 3.Seed system product: "Applied Deposit"
    # Check if Applied Deposit entry is exist by both name and the is_system flag
    applied_deposit = db.session.execute(
            db.select(Product).filter_by(name='Applied Deposit', is_system=True)
        ).scalar_one_or_none()
    
    if not applied_deposit:
        system_product = Product()
        system_product.name = 'Applied Deposit'
        system_product.catalog_number = 'SYS-DEP'
        system_product.is_system = True
        system_product.default_unit_price = 0
        system_product.is_active = True
        system_product.document_placement='Lineitem'
        system_product.category_id = 1

        db.session.add(system_product)
        click.echo("System Product 'Applied Deposit' seeded successfully.")

    # 4.seed default product: "Prepayment"
    # Check if Prepayment entry is exist by both name and the catalog_number
    prepayment = db.session.execute(
        db.select(Product).filter_by(name='Prepayment', catalog_number='PRE-PMT')
    ).scalar_one_or_none()

    if not prepayment:
        prepayment = Product()
        prepayment.name = 'Prepayment'
        prepayment.catalog_number = 'PRE-PMT'
        prepayment.is_system = False
        prepayment.default_unit_price = 0
        prepayment.is_active = True
        prepayment.document_placement='Lineitem'
        prepayment.category_id = 1

        db.session.add(prepayment)
        click.echo("Default Product 'Prepayment' seeded successfully.")

    # 5. Seed Root Admin User from .env
    admin_user = db.session.execute(
        select(User).filter_by(is_root=True)
    ).scalar_one_or_none()

    if not admin_user:
        admin_user = User()
        admin_user.username = os.getenv('INITIAL_ADMIN_USERNAME', 'admin')
        admin_user.email = os.getenv('INITIAL_ADMIN_EMAIL', 'admin@example.com')
        admin_user.role = 'admin'
        admin_user.is_active = True
        admin_user.is_root = True

        # Use the method in your User model to hash the password safely
        password = os.environ.get('INITIAL_ADMIN_PASSWORD', 'password')
        admin_user.set_password(password)
        
        db.session.add(admin_user)
        click.echo(f"Admin user '{admin_user.username}' created successfully.")

    db.session.commit()
    click.echo("Database initialized and Seeding complete.")