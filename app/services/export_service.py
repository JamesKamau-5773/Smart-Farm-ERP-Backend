from __future__ import annotations

from datetime import datetime

from sqlalchemy import desc

from app import db
from app.models.livestock import BreedingLog, Cow, MedicalRecord, SemenInventory
from app.models.supply import MilkLog


class AnimalPassportService:
    @staticmethod
    def _format_datetime(value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime('%d %b %Y, %H:%M')
        return value.strftime('%d %b %Y')

    @staticmethod
    def _build_event(*, date_value, category, title, details, sort_value):
        return {
            'date': AnimalPassportService._format_datetime(date_value),
            'category': category,
            'title': title,
            'details': details,
            'sort_value': sort_value,
        }

    @staticmethod
    def build_passport_context(*, animal_id: int, tenant_id: int):
        animal = db.session.get(Cow, animal_id)
        if animal is None:
            return None

        events = []

        milk_logs = (
            MilkLog.query.filter_by(cow_id=animal_id)
            .order_by(desc(MilkLog.timestamp))
            .all()
        )
        for log in milk_logs:
            events.append(
                AnimalPassportService._build_event(
                    date_value=log.timestamp,
                    category='Milk Yield',
                    title=f'{float(log.amount_liters):.2f} L in {log.session}',
                    details=(
                        f"Saleable: {'Yes' if log.is_saleable else 'No'} | "
                        f"Anomaly: {'Yes' if log.anomaly_flag else 'No'}"
                    ),
                    sort_value=log.timestamp,
                )
            )

        medical_records = (
            MedicalRecord.query.filter_by(cow_id=animal_id)
            .order_by(desc(MedicalRecord.visit_date))
            .all()
        )
        for record in medical_records:
            events.append(
                AnimalPassportService._build_event(
                    date_value=record.visit_date,
                    category='Medical',
                    title=record.diagnosis,
                    details=(
                        f"Medication: {record.medication or 'N/A'} | "
                        f"Withdrawal days: {record.withdrawal_days_recommended}"
                    ),
                    sort_value=record.visit_date,
                )
            )

        breeding_logs = (
            db.session.query(BreedingLog, SemenInventory)
            .join(SemenInventory, SemenInventory.id == BreedingLog.semen_id)
            .filter(BreedingLog.cow_id == animal_id, BreedingLog.tenant_id == tenant_id)
            .order_by(desc(BreedingLog.insemination_date))
            .all()
        )
        for breeding_log, semen in breeding_logs:
            events.append(
                AnimalPassportService._build_event(
                    date_value=breeding_log.insemination_date,
                    category='Breeding',
                    title=f'Inseminated with {semen.bull_name}',
                    details=(
                        f"Straw: {semen.straw_code} | Status: {breeding_log.status} | "
                        f"Expected calving: {AnimalPassportService._format_datetime(breeding_log.expected_calving_date) or 'N/A'}"
                    ),
                    sort_value=datetime.combine(breeding_log.insemination_date, datetime.min.time()),
                )
            )

        events.sort(key=lambda item: item['sort_value'], reverse=True)
        for event in events:
            event.pop('sort_value', None)

        animal_context = {
            'id': animal.id,
            'tag_number': animal.tag_number,
            'name': animal.name or 'Unnamed Animal',
            'breed_status': animal.breed_status,
            'date_of_birth': animal.date_of_birth.strftime('%d %b %Y'),
            'current_status': animal.current_status,
            'is_active': animal.is_active,
            'is_hardlocked': animal.is_hardlocked,
        }

        return {
            'animal': animal_context,
            'events': events,
            'generated_at': datetime.utcnow().strftime('%d %b %Y, %H:%M UTC'),
        }