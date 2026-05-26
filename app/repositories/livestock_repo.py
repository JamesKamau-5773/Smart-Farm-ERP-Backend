from app.repositories.cow_repo import CowRepository


class LivestockRepository(CowRepository):
    """Compatibility alias for livestock-facing code paths while cows remain the storage model."""

    pass
