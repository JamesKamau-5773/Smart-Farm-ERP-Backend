from datetime import timedelta, date

class ReproductionService:
    # Standard Biological Constants
    GESTATION_DAYS = 280
    DRYING_OFFSET = 60
    STEAMING_OFFSET = 21
    PREGNANCY_CHECK_OFFSET_DAYS = 21

    @classmethod
    def calculate_milestones(cls, insemination_date: date) -> dict:
        """
        Calculates biological milestones based on the date of AI service.
        """
        expected_calving = insemination_date + timedelta(days=cls.GESTATION_DAYS)
        drying_date = expected_calving - timedelta(days=cls.DRYING_OFFSET)
        steaming_date = expected_calving - timedelta(days=cls.STEAMING_OFFSET)
        pregnancy_check_date = insemination_date + timedelta(days=cls.PREGNANCY_CHECK_OFFSET_DAYS)

        return {
            "expected_calving_date": expected_calving,
            "drying_date": drying_date,
            "steaming_date": steaming_date,
            "pregnancy_check_date": pregnancy_check_date,
        }

    @staticmethod
    def get_next_heat_window(last_heat_date: date) -> tuple:
        """
        Predicts the next 21-day heat window.
        Observation starts on day 18 and ends on day 24.
        """
        observation_start = last_heat_date + timedelta(days=18)
        observation_end = last_heat_date + timedelta(days=24)
        return (observation_start, observation_end)

    @staticmethod
    def get_pregnancy_check_date(insemination_date: date) -> date:
        """Returns the recommended date to check whether the cow has returned to heat."""
        return insemination_date + timedelta(days=21)