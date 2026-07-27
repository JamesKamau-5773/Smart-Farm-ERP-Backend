from datetime import datetime, timezone

from app import db


class GeneticTraitDefinition(db.Model):
    """
    Lookup table for the bounded set of genetic traits tracked by the system.
    Seeded once; not modified at runtime.
    """

    __tablename__ = 'genetic_trait_definitions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)  # e.g. "milk_volume"
    display_name = db.Column(db.String(100), nullable=False)        # e.g. "Milk Volume"
    category = db.Column(db.String(50), nullable=False)             # Production | Health | Conformation
    unit = db.Column(db.String(50), nullable=True)                  # "liters/day", "%", "score"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'category': self.category,
            'unit': self.unit,
        }


class GeneticProfile(db.Model):
    """
    One profile per animal. Acts as the anchor for all trait scores.
    A profile is created once (at registration or first calving) and updated via
    trait scores — never replaced.
    """

    __tablename__ = 'genetic_profiles'

    SOURCE_GENOMIC_TEST = 'GENOMIC_TEST'
    SOURCE_PROJECTED = 'PROJECTED'
    SOURCE_MANUAL = 'MANUAL'

    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(
        db.Integer,
        db.ForeignKey('cows.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    tenant_id = db.Column(
        db.Integer,
        db.ForeignKey('tenants.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # How the baseline data was established for this animal.
    source = db.Column(db.String(50), nullable=False, default=SOURCE_MANUAL)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    trait_scores = db.relationship(
        'GeneticTraitScore',
        backref='profile',
        cascade='all, delete-orphan',
        lazy=True,
    )
    cow = db.relationship('Cow', back_populates='genetic_profile')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'cow_id': self.cow_id,
            'source': self.source,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'trait_scores': [ts.to_dict() for ts in self.trait_scores],
        }


class GeneticTraitScore(db.Model):
    """
    One row per (profile, trait). Stores the numeric value and a reliability
    percentage (0–100). The reliability is recalculated by GeneticReliabilityService
    as the animal accumulates performance history (lactation cycles).
    """

    __tablename__ = 'genetic_trait_scores'

    SCORED_SOURCE_USER = 'USER_INPUT'
    SCORED_SOURCE_SYSTEM = 'SYSTEM_PROJECTED'

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer,
        db.ForeignKey('genetic_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    trait_definition_id = db.Column(
        db.Integer,
        db.ForeignKey('genetic_trait_definitions.id'),
        nullable=False,
    )
    value = db.Column(db.Numeric(10, 4), nullable=False)
    # Confidence in this score; 50 = projected baseline, 90 = 3+ lactations observed.
    reliability = db.Column(db.Integer, nullable=False, default=50)
    scored_source = db.Column(db.String(50), nullable=False, default=SCORED_SOURCE_USER)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    trait_definition = db.relationship('GeneticTraitDefinition', lazy='joined')

    __table_args__ = (
        db.UniqueConstraint(
            'profile_id', 'trait_definition_id',
            name='uq_genetic_trait_score_profile_trait',
        ),
        db.CheckConstraint('reliability >= 0 AND reliability <= 100', name='ck_genetic_trait_score_reliability'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'trait': self.trait_definition.to_dict() if self.trait_definition else None,
            'value': float(self.value),
            'reliability': self.reliability,
            'scored_source': self.scored_source,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
