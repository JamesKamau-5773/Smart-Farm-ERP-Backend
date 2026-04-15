from app import db
from datetime import datetime

class ItemCategory:
    FEED = "Feed"
    SUPPLEMENT = "Supplement"
    EQUIPMENT = "Equipment"
    MEDICINE = "Medicine"

class StoreItem(db.Model):
    """Tracks physical inventory in the farm store."""
    __tablename__ = 'store_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    category = db.Column(db.String(50), default=ItemCategory.FEED, nullable=False)
    unit_of_measure = db.Column(db.String(20), nullable=False) # e.g., 'kg', 'liters', 'pieces'
    
    current_stock = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    min_threshold = db.Column(db.Numeric(10, 2), default=10.00, nullable=False) # For restock alerts
    unit_cost = db.Column(db.Numeric(10, 2), default=0.00, nullable=False) # Cost per UoM

    requisitions = db.relationship('FeedRequisition', backref='item', lazy=True)

class FeedRequisition(db.Model):
    """The Audit Trail for who took what from the store, and for which cow."""
    __tablename__ = 'feed_requisitions'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('store_items.id'), nullable=False)
    amount_used = db.Column(db.Numeric(10, 2), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    target_cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=True) 
    notes = db.Column(db.String(255), nullable=True)

class MilkSession:
    MORNING = "Morning"
    EVENING = "Evening"

class MilkLog(db.Model):
    """Tracks daily yield and flags anomalies or hardlocked milk."""
    __tablename__ = 'milk_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    amount_liters = db.Column(db.Numeric(10, 2), nullable=False)
    session = db.Column(db.String(20), nullable=False) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Critical Commercial Flags
    is_saleable = db.Column(db.Boolean, default=True, nullable=False) 
    anomaly_flag = db.Column(db.Boolean, default=False, nullable=False) # True if yield dropped > 15%