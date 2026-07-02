from app import db
from datetime import datetime, timezone

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
    genetic_score = db.Column(db.Integer, nullable=True)

    # Operational State
    is_hardlocked = db.Column(db.Boolean, default=False)
    current_status = db.Column(db.String(50), default=CowStatus.LACTATING, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    # Relationships
    lactation_cycles = db.relationship('LactationCycle', backref=db.backref('livestock', lazy=True), lazy=True)
    medical_records = db.relationship('MedicalRecord', backref=db.backref('livestock', lazy=True), lazy=True)
    breeding_logs = db.relationship('BreedingLog', backref=db.backref('livestock', lazy=True), lazy=True)
    vet_visits = db.relationship('VetVisit', backref=db.backref('livestock', lazy=True), lazy=True)
    timeline_events = db.relationship(
        'AnimalTimelineEvent',
        backref=db.backref('animal', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )


class AnimalYieldTarget(db.Model):
    __tablename__ = 'animal_yield_targets'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True)
    target_liters = db.Column(db.Numeric(5, 2), nullable=False)
    times_to_feed_daily = db.Column(db.Integer, default=2, nullable=False)
    base_herd_feed_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    milking_topup_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    status = db.Column(db.String(20), default='Active', nullable=False)

    cow = db.relationship('Cow', backref=db.backref('yield_targets', lazy=True))

    __table_args__ = (
        db.CheckConstraint('times_to_feed_daily IN (2, 3, 4)', name='ck_animal_yield_targets_times_to_feed_daily_valid'),
    )


class SemenInventory(db.Model):
    __tablename__ = 'semen_inventory'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    bull_name = db.Column(db.String(100), nullable=False)
    straw_code = db.Column(db.String(50), nullable=False)
    breed = db.Column(db.String(50), nullable=False)
    provider = db.Column(db.String(100), nullable=True)
    cost = db.Column(db.Numeric(10, 2), nullable=True)
    stock_level = db.Column(db.Integer, nullable=False, default=0)
    traits_to_improve = db.Column(db.JSON, nullable=True)

    breeding_logs = db.relationship('BreedingLog', backref=db.backref('semen', lazy=True), lazy=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'straw_code', name='uq_semen_inventory_tenant_straw_code'),
    )


class BreedingLog(db.Model):
    __tablename__ = 'breeding_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False, index=True)
    semen_id = db.Column(db.Integer, db.ForeignKey('semen_inventory.id'), nullable=False, index=True)
    insemination_date = db.Column(db.Date, nullable=False)
    expected_calving_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Pending')

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('Pending', 'Pregnant', 'Failed')",
            name='ck_breeding_logs_status_valid'
        ),
    )

    @property
    def cow(self):
        return self.livestock

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

    @property
    def cow(self):
        return self.livestock

class MedicalRecord(db.Model):
    __tablename__ = 'medical_records'

    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    vet_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    visit_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    diagnosis = db.Column(db.Text, nullable=False)
    medication = db.Column(db.String(255), nullable=True)
    withdrawal_days_recommended = db.Column(db.Integer, default=0)
    remarks = db.Column(db.Text, nullable=True)

    @property
    def cow(self):
        return self.livestock


class VetVisit(db.Model):
    __tablename__ = 'vet_visits'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False, index=True)
    vet_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    visit_date = db.Column(db.Date, nullable=False)
    reason_for_visit = db.Column(db.Text, nullable=False)
    diagnosis = db.Column(db.Text, nullable=True)
    medications = db.Column(db.JSON, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    follow_up_required = db.Column(db.Boolean, nullable=False, default=False)
    follow_up_date = db.Column(db.Date, nullable=True)
    follow_up_status = db.Column(db.String(20), nullable=False, default='Not Required')
    follow_up_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.CheckConstraint(
            "follow_up_status IN ('Not Required', 'Pending', 'Scheduled', 'Completed', 'Overdue', 'Cancelled')",
            name='ck_vet_visits_follow_up_status_valid'
        ),
    )

    @property
    def cow(self):
        return self.livestock

    @property
    def livestock_id(self):
        return self.animal_id


class HerdsmanRoutineTemplate(db.Model):
    __tablename__ = 'herdsman_routine_template'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    task_title = db.Column(db.String(100), nullable=False)
    task_description = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    checklist_items = db.Column(db.JSON, nullable=True)
    display_order = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    task_logs = db.relationship('DailyTaskLog', backref=db.backref('routine', lazy=True), lazy=True)


class DailyTaskLog(db.Model):
    __tablename__ = 'daily_task_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    routine_id = db.Column(db.Integer, db.ForeignKey('herdsman_routine_template.id', ondelete='RESTRICT'), nullable=False, index=True)
    herdsman_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    issue_tag = db.Column(db.String(100), nullable=False, default='None')
    status = db.Column(db.String(20), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    herdsman = db.relationship('User', backref=db.backref('daily_task_logs', lazy=True))

    __table_args__ = (
        db.CheckConstraint("status IN ('Completed', 'Deviated')", name='ck_daily_task_logs_status_valid'),
    )


class AnimalTimelineEvent(db.Model):
    __tablename__ = 'animal_events'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    event_date = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    event_data = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))