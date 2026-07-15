import enum


class CowStatus(str, enum.Enum):
    """Canonical statuses for livestock animals."""
    LACTATING = "Lactating"
    DRY = "Dry"
    HEIFER = "Heifer"
    CALF = "Calf"
    COW = "Cow"
    SOLD = "Sold"
    DIED = "Died"