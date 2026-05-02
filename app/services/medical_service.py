from app.repositories.medical_repo import MedicalRepository
from app.repositories.cow_repo import CowRepository
from flask import jsonify

class MedicalService:
    @staticmethod
    def log_clinical_visit(cow_id, vet_id, data):
        """Processes Vet input and suggests a hardlock if withdrawal days > 0."""
        # 1. Validate Cow Exists
        cow = CowRepository.get_by_id(cow_id)
        if not cow:
            return jsonify({"error": "Cow not found in registry."}), 404

        # 2. Extract Data
        diagnosis = data.get('diagnosis')
        medication = data.get('medication')
        withdrawal_days = int(data.get('withdrawal_days', 0))
        remarks = data.get('remarks')

        if not diagnosis:
            return jsonify({"error": "Diagnosis is required for clinical logs."}), 400

        # 3. Save Record
        record = MedicalRepository.create_record(cow_id, vet_id, diagnosis, medication, withdrawal_days, remarks)
        
        # 4. Generate Alert Payload
        response = {
            "message": "Clinical record saved successfully.",
            "record_id": record.id,
            "requires_hardlock": withdrawal_days > 0,
            "alert": f"Suggested withdrawal period of {withdrawal_days} days. Farmer action required." if withdrawal_days > 0 else "No withdrawal period necessary."
        }
        
        return jsonify(response), 201

    @staticmethod
    def enforce_hardlock(cow_id, is_locked, user_id, ip_address):
        """Processes the Farmer's decision to lock/unlock a cow."""
        cow = CowRepository.get_by_id(cow_id)
        if not cow:
            return jsonify({"error": "Cow not found in registry."}), 404

        updated_cow = MedicalRepository.toggle_hardlock(cow_id, is_locked, user_id, ip_address)
        
        status = "LOCKED (Internal Use Only)" if is_locked else "UNLOCKED (Saleable)"
        return jsonify({"message": f"Cow {updated_cow.tag_number} is now {status}."}), 200