from app.repositories.livestock_repo import LivestockRepository
from app.services.medical_service import MedicalService
from app.services.production_service import ProductionService


class LivestockService:
    """Compatibility service alias that forwards livestock-facing calls to the existing cow-based implementation."""

    @staticmethod
    def get_by_id(livestock_id: int):
        return LivestockRepository.get_by_id(livestock_id)

    @staticmethod
    def get_by_tag(tag_number: str):
        return LivestockRepository.get_by_tag(tag_number)

    @staticmethod
    def get_all_active():
        return LivestockRepository.get_all_active()

    @staticmethod
    def log_daily_yield(livestock_id: int, amount: float, session: str, user_id: int):
        return ProductionService.log_daily_yield(livestock_id, amount, session, user_id)

    @staticmethod
    def log_clinical_visit(livestock_id: int, vet_id: int, data):
        return MedicalService.log_clinical_visit(livestock_id, vet_id, data)

    @staticmethod
    def enforce_hardlock(livestock_id: int, is_locked: bool, user_id: int, ip_address: str):
        return MedicalService.enforce_hardlock(livestock_id, is_locked, user_id, ip_address)
