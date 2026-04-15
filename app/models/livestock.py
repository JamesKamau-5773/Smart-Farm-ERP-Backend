from app import db
from datetime import datetime

class BreedStatus:
    FOUNDATION = "Foundation"
    INTERMEDIATE = "Intermediate"
    APPENDIX = "Appendix"
    PEDIGREE = "Pedigree"

class CowStatus:
    CALF = "Calf"
    HEIFER = "Heifer"
    LACTATING = "Lactating"
    DRY = "Dry"

class Cow(db.Model):
    __tablename__ = 'cows'

    id = db.Column(db.Integer, primary_key=True)
    tag_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100))
    breed_status = db.Column(db.String(50), default=BreedStatus.FOUNDATION, nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)

    # Genetic Tracking (Self-referential foreign key for lineage)
    dam_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=True) 
    sire_name = db.Column(db.String(100), nullable=True) 

    # Operational State
    is_hardlocked = db.Column(db.Boolean, default=False)
    current_status = db.Column(db.String(50), default=CowStatus.LACTATING, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    # Relationships
    lactation_cycles = db.relationship('LactationCycle', backref='cow', lazy=True)
    medical_records = db.relationship('MedicalRecord', backref='cow', lazy=True)

class LactationCycle(db.Model):
    __tablename__ = 'lactation_cycles'

    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    cycle_number = db.Column(db.Integer, nullable=False)

    # Biological State Machine Dates
    insemination_date = db.Column(db.Date, nullable=True)
    expected_calving_date = db.Column(db.Date, nullable=True)
    drying_date = db.Column(db.Date, nullable=True)
    steaming_date = db.Column(db.Date, nullable=True)

    actual_calving_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

class MedicalRecord(db.Model):
    __tablename__ = 'medical_records'

    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    vet_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    visit_date = db.Column(db.DateTime, default=datetime.utcnow)

    diagnosis = db.Column(db.Text, nullable=False)
    medication = db.Column(db.String(255), nullable=True)
    withdrawal_days_recommended = db.Column(db.Integer, default=0)
    remarks = db.Column(db.Text, nullable=True)