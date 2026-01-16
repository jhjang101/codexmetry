from app import create_app, db
from app.models import SettingsMetadata

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        # Create all tables defined in models.py
        db.create_all()
        
        # Seed the single-row settings if not exists
        if not db.session.get(SettingsMetadata, 1):
            seed = SettingsMetadata()
            seed.id = 1
            seed.company_name = "Codexmetry Corp"
            db.session.add(seed)
            db.session.commit()
            print("Database initialized: Tables created and Settings seeded.")

    app.run(host='0.0.0.0', debug=True, port=5001)