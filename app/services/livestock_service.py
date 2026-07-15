import logging
from datetime import date, datetime
from typing import Any, Dict

from dateutil.relativedelta import relativedelta

from app.models.enums import CowStatus
# from app.models.livestock import Cow as Livestock  # Assuming alias for transition
# from app.repositories.livestock_repo import LivestockRepository
# from app.utils.exceptions import ConflictError, UnprocessableEntityError

# Note: The above imports are assumed to exist. For this example, we will mock them.
from unittest.mock import MagicMock
Livestock = MagicMock()
LivestockRepository = MagicMock()
class UnprocessableEntityError(ValueError): pass
class ConflictError(ValueError): pass
class NotFoundError(ValueError): pass


log = logging.getLogger(__name__)


class LivestockService:
    @staticmethod
    def _calculate_initial_status(date_of_birth: date, has_calved: bool) -> CowStatus:
        """
        Calculates the initial status of a cow based on its age and whether it has calved.
        This business logic was moved from the frontend to ensure a single source of truth.
        """
        if has_calved:
            return CowStatus.LACTATING

        if not date_of_birth:
            # If no DOB is provided, we can't determine age, so default to Cow.
            return CowStatus.COW

        today = date.today()
        if date_of_birth > today:
            raise UnprocessableEntityError("Date of birth cannot be in the future.")

        delta = relativedelta(today, date_of_birth)
        age_months = delta.years * 12 + delta.months

        if age_months < 6:
            return CowStatus.CALF
        elif 6 <= age_months <= 15:
            return CowStatus.HEIFER
        else:
            return CowStatus.COW

    @staticmethod
    def create_livestock(data: Dict[str, Any], tenant_id: int, farm_id: int) -> Livestock:
        """
        Creates a new livestock animal, calculating its initial status based on business rules.
        The API layer is responsible for normalizing field names (e.g., tagNumber -> tag_number).
        """
        tag_number = data.get('tag_number')
        date_of_birth_str = data.get('date_of_birth')

        if not tag_number or not str(tag_number).strip():
            raise UnprocessableEntityError("tag_number is required and cannot be empty.")
        if not date_of_birth_str:
            raise UnprocessableEntityError("date_of_birth is required.")

        tag_number = tag_number.strip().upper()

        if LivestockRepository.find_by_tag_number(tag_number, tenant_id):
            raise ConflictError(f"Livestock with tag number '{tag_number}' already exists for this tenant.")

        try:
            date_of_birth = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            raise UnprocessableEntityError("Invalid date_of_birth format. Use YYYY-MM-DD.")

        initial_status = LivestockService._calculate_initial_status(date_of_birth, data.get('has_calved', False))

        livestock_data = {'tenant_id': tenant_id, 'farm_id': farm_id, 'tag_number': tag_number, 'name': data.get('name', 'Unnamed'), 'date_of_birth': date_of_birth, 'breed_status': data.get('breed_status', 'Foundation'), 'current_status': initial_status, 'is_active': True}

        log.info("Creating new livestock '%s' for tenant %d with status %s", tag_number, tenant_id, initial_status.value)
        return LivestockRepository.create(**livestock_data)

    @staticmethod
    def get_livestock_by_tag_number(tag_number: str, tenant_id: int) -> Livestock:
        """
        Retrieves a single livestock animal by its tag_number for a given tenant.

        This ensures that the business key (tag_number) used by the frontend in URLs
        is the canonical way to fetch a specific animal.
        """
        if not tag_number or not str(tag_number).strip():
            raise UnprocessableEntityError("tag_number is required and cannot be empty.")

        animal = LivestockRepository.find_by_tag_number(tag_number.strip().upper(), tenant_id)

        if not animal:
            raise NotFoundError(f"Livestock with tag number '{tag_number}' not found for this tenant.")

        return animal