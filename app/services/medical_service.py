from app.repositories.medical_repo import MedicalRepository
from app.repositories.cow_repo import CowRepository
from flask import jsonify

class MedicalService:
    @staticmethod
    def log_clinical_visit(cow_id, vet_id, data):
        """Processes Vet input and suggests a hardlock if withdrawal days > 0."""
        livestock_id = cow_id

        # 1. Validate Livestock Exists
        livestock = CowRepository.get_by_id(livestock_id)
        if not livestock:
            return jsonify({"error": "Cow not found in registry."}), 404

        # 2. Extract Data
        diagnosis = data.get('diagnosis')
        medication = data.get('medication')
        withdrawal_days = int(data.get('withdrawal_days', 0))
        remarks = data.get('remarks')

        if not diagnosis:
            return jsonify({"error": "Diagnosis is required for clinical logs."}), 400

        # 3. Save Record
        record = MedicalRepository.create_record(livestock_id, vet_id, diagnosis, medication, withdrawal_days, remarks)
        
        # 4. Generate Alert Payload
        response = {
            "message": "Clinical record saved successfully.",
            "record": {
                "id": record.id,
                "cow_id": record.cow_id,
                "vet_id": record.vet_id,
                "visit_date": record.visit_date.isoformat() if record.visit_date else None,
                "diagnosis": record.diagnosis,
                "medication": record.medication,
                "withdrawal_days_recommended": record.withdrawal_days_recommended,
                "remarks": record.remarks,
                "created_at": record.visit_date.isoformat() if record.visit_date else None,
                "created_by": vet_id,
            },
            "record_id": record.id,
            "requires_hardlock": withdrawal_days > 0,
            "alert": f"Suggested withdrawal period of {withdrawal_days} days. Farmer action required." if withdrawal_days > 0 else "No withdrawal period necessary."
        }
        
        return jsonify(response), 201

    @staticmethod
    def enforce_hardlock(cow_id, is_locked, user_id, ip_address):
        """Processes the Farmer's decision to lock/unlock livestock."""
        livestock_id = cow_id
        livestock = CowRepository.get_by_id(livestock_id)
        if not livestock:
            return jsonify({"error": "Cow not found in registry."}), 404

        updated_livestock = MedicalRepository.toggle_hardlock(livestock_id, is_locked, user_id, ip_address)
        
        status = "LOCKED (Internal Use Only)" if is_locked else "UNLOCKED (Saleable)"
        return jsonify({
            "message": f"Livestock {updated_livestock.tag_number} is now {status}.",
            "cow_id": updated_livestock.id,
            "cow_name": updated_livestock.name,
            "tag_number": updated_livestock.tag_number,
            "is_hardlocked": updated_livestock.is_hardlocked,
            "updated_by": user_id,
            "updated_at": None,
        }), 200