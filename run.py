import os
from app import create_app, db
from app.models import SettingsMetadata, Product, User, ProductCategory
from sqlalchemy import select

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # Create all tables defined in models.py
        db.create_all()
        
        # 1. Seed the single-row settings if not exists
        if not db.session.get(SettingsMetadata, 1):
            seed = SettingsMetadata()
            seed.id = 1
            seed.company_name = "Codexmetry Corp"
            db.session.add(seed)
            db.session.commit()
            print("Database initialized: Tables created and Settings seeded successfully.")

        # 2. Seed System Category (SYSTEM-DEPOSIT)
        system_category = db.session.execute(
            select(ProductCategory).filter_by(is_system=True)
        ).scalar_one_or_none()

        if not system_category:
            system_category = ProductCategory()
            system_category.id = 1
            system_category.type='SYSTEM-DEPOSIT'
            system_category.is_revenue=False # Deposits are not revenue until spent
            system_category.is_system=True
            
            db.session.add(system_category)
            db.session.commit()
            print("System Category 'SYSTEM-DEPOSIT' seeded successfully.")

        # 3.seed system product: "Applied Deposit"
        # Check if Applied Deposit entry is exist by both name and the is_system flag
        applied_deposit = db.session.execute(
            db.select(Product).filter_by(name='Applied Deposit', is_system=True)
        ).scalar_one_or_none()

        if not applied_deposit:
            system_product = Product()
            system_product.name = 'Applied Deposit'
            system_product.catalog_number = 'SYSTEM-DEPOSIT'
            system_product.is_system = True
            system_product.default_unit_price = 0
            system_product.is_active = True
            system_product.document_placement='Lineitem'
            system_product.category_id = 1

            db.session.add(system_product)
            db.session.commit()
            print("System Product 'Applied Deposit' seeded successfully.")

        # 3. Seed Initial Admin User from .env
        if db.session.execute(select(User)).first() is None:
            admin_user = User()
            admin_user.username = os.getenv('INITIAL_ADMIN_USERNAME', 'admin')
            admin_user.email = os.getenv('INITIAL_ADMIN_EMAIL', 'admin@codexmetry.local')
            admin_user.role = 'admin'
            admin_user.is_active = True
            
            # Use the method in your User model to hash the password safely
            password = os.environ.get('INITIAL_ADMIN_PASSWORD', 'admin123')
            admin_user.set_password(password)
            
            db.session.add(admin_user)
            db.session.commit()
            print(f"Admin user '{admin_user.username}' created successfully.")

    app.run(host='0.0.0.0', debug=True, port=5001)