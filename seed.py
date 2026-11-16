import os
from app import create_app
from app.extensions import db
from app.models import User, Service

app = create_app()
with app.app_context():
    if not User.query.filter_by(role="admin").first():
        password = os.getenv("SEED_ADMIN_PASSWORD")
        if not password or len(password) < 12:
            raise RuntimeError("Set SEED_ADMIN_PASSWORD to a unique password of at least 12 characters before seeding the first admin.")
        phone = os.getenv("SEED_ADMIN_PHONE", "9999999999")
        admin = User(name="Aseel Admin", phone=phone, email=os.getenv("SEED_ADMIN_EMAIL", "admin@aseel.local"), role="admin")
        admin.set_password(password)
        db.session.add(admin)
        print(f"Created initial admin account for phone {phone}. Store its password securely.")
    services = [
        ("Advanced Machine Washing", "Professional machine washing", 0, "kg"),
        ("Steam Ironing", "Professional steam ironing", 0, "piece"),
        ("Dry Cleaning", "Specialist garment dry cleaning", 0, "piece"),
        ("Blanket Cleaning", "Blanket cleaning service", 0, "blanket"),
        ("Shoe Cleaning", "Shoe cleaning service", 0, "pair"),
        ("Bag Cleaning", "Bag cleaning service", 0, "bag"),
    ]
    for name, desc, price, unit in services:
        if not Service.query.filter_by(name=name).first():
            db.session.add(Service(name=name, description=desc, price=price, unit=unit))
    db.session.commit()
    print("Seeded services with zero placeholder prices. Set actual prices in Admin > Services & pricing.")
