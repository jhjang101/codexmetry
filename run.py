from app import create_app, db
from app.models import SettingsMetadata, Product

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
            print("Database initialized: Tables created and Settings seeded.")

        # 2.seed system product: "Applied Deposit"
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

            db.session.add(system_product)
            db.session.commit()
            print("System Product 'Applied Deposit' seeded successfully.")

    app.run(host='0.0.0.0', debug=True, port=5001)