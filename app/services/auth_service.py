from flask import jsonify
from flask_jwt_extended import create_access_token, set_access_cookies, unset_jwt_cookies

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.repositories.user_repo import UserRepository
from app.utils.jwt_payload import (
    build_auth_payload,
    normalize_tenant_type,
    parse_public_int_id,
)

class AuthService:
    @staticmethod
    def _ensure_default_tenant_and_farm(user):
        """Best-effort safety net for older DBs / seedless dev envs."""
        tenant = getattr(user, "tenant", None)
        if tenant is None and getattr(user, "tenant_id", None) is not None:
            tenant = db.session.get(Tenant, user.tenant_id)

        if tenant is None:
            tenant = Tenant(name="Default Tenant", tenant_type="single")
            db.session.add(tenant)
            db.session.flush()
            user.tenant_id = tenant.id
            user.tenant = tenant

        farms = list(getattr(tenant, "farms", []) or [])
        if not farms:
            farm = Farm(tenant_id=tenant.id, name="Default Farm")
            db.session.add(farm)
            db.session.flush()
            farms = [farm]

        db.session.commit()
        return tenant, farms

    @staticmethod
    def _pick_active_farm(*, tenant, farms, requested_farm_id: str | None):
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))

        if tenant_type == "single":
            return farms[0]

        # cooperative
        if requested_farm_id:
            requested_pk = parse_public_int_id(requested_farm_id, "farm_")
            for farm in farms:
                if farm.id == requested_pk:
                    return farm
            raise ValueError("Invalid farm_id for this tenant")

        return farms[0]

    @staticmethod
    def _issue_token_and_payload(*, user, tenant, farms, active_farm):
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))
        available_farms = [(f.id, f.name) for f in farms]

        payload = build_auth_payload(
            user_id=user.id,
            name=(user.name or user.username),
            email=(user.email or user.username),
            role=user.role,
            tenant_pk=tenant.id,
            tenant_name=tenant.name,
            tenant_type=tenant_type,
            active_farm_pk=active_farm.id,
            active_farm_name=active_farm.name,
            available_farms=available_farms,
        )

        additional_claims = dict(payload)
        additional_claims.pop("sub", None)

        access_token = create_access_token(
            identity=str(user.id),
            additional_claims=additional_claims,
        )

        return access_token, payload

    @staticmethod
    def authenticate_user(username, password, farm_id=None):
        user = UserRepository.get_by_username(username)
        
        # 1. Verify User Exists and Password Matches
        if user and user.check_password(password):
            
            # 2. Check if account is locked/inactive
            if not user.is_active:
                return jsonify({"error": "Account is disabled. Contact Farm Administrator."}), 403
            
            tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
            try:
                active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=farm_id)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400

            try:
                access_token, payload = AuthService._issue_token_and_payload(
                    user=user,
                    tenant=tenant,
                    farms=farms,
                    active_farm=active_farm,
                )
            except ValueError as e:
                return jsonify({"error": str(e)}), 500

            response = jsonify({
                "access_token": access_token,
                **payload,
            })

            set_access_cookies(response, access_token)
            return response, 200
            
        return jsonify({"error": "Invalid username or password"}), 401

    @staticmethod
    def switch_farm(user_id: str, farm_id: str):
        user = UserRepository.get_by_id(int(user_id))
        if not user:
            return jsonify({"error": "User not found"}), 404

        tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
        tenant_type = normalize_tenant_type(getattr(tenant, "tenant_type", None))
        if tenant_type != "cooperative":
            return jsonify({"error": "Farm switching is only allowed for cooperative tenants"}), 403

        try:
            active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=farm_id)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        access_token, payload = AuthService._issue_token_and_payload(
            user=user,
            tenant=tenant,
            farms=farms,
            active_farm=active_farm,
        )

        response = jsonify({
            "access_token": access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 200

    @staticmethod
    def logout_user():
        response = jsonify({"message": "Successfully logged out."})
        unset_jwt_cookies(response)
        return response, 200