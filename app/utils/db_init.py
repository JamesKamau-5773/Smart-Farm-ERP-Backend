from app import db
from app.models.user import User, Role

def seed_roles():
    """
    Ensures a SuperAdmin Farmer exists on the first run.
    """
    farmer_exists = User.query.filter_by(role=Role.FARMER).first()
    if not farmer_exists:
        admin = User(
            username="jivu_admin",
            role=Role.FARMER
        )
        admin.set_password("JivuSecure2026!") # Farmer must change this on first login
        db.session.add(admin)
        db.session.commit()
        print("Backend: SuperAdmin created.")