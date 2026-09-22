from __future__ import annotations

import math


class StaffingRecommendationService:
    @staticmethod
    def recommend(employee_count: int) -> dict:
        count = max(int(employee_count), 0)

        if count == 0:
            farm_size = 'NO_STAFF'
            managers = supervisors = farm_admins = 0
        elif count <= 5:
            farm_size = 'SMALL'
            managers = supervisors = farm_admins = 0
        elif count <= 15:
            farm_size = 'GROWING'
            managers = farm_admins = 0
            supervisors = 1
        elif count <= 30:
            farm_size = 'ESTABLISHED'
            managers = supervisors = 1
            farm_admins = 0
        else:
            farm_size = 'LARGE'
            farm_admins = 1
            managers = max(1, math.ceil(count / 30))
            supervisors = max(1, math.ceil(count / 10))

        leadership = farm_admins + managers + supervisors
        return {
            'employee_count': count,
            'farm_size': farm_size,
            'recommended_roles': {
                'FARM_ADMIN': farm_admins,
                'FARM_MANAGER': managers,
                'FARM_SUPERVISOR': supervisors,
                'FARM_HAND': max(count - leadership, 0),
            },
            'advisory_only': True,
            'note': 'Assign access according to responsibility; headcount recommendations do not grant permissions.',
        }
