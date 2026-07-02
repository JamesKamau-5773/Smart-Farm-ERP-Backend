from __future__ import annotations

import csv
import io
from datetime import timedelta
from uuid import uuid4

from flask import jsonify, current_app
from flask_jwt_extended import create_access_token, decode_token
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.farm import Farm
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.auth_service import AuthService
from app.utils.jwt_payload import normalize_tenant_type, public_tenant_id


class CooperativeService:
    INVITE_TOKEN_EXPIRY_DAYS = 7

    @staticmethod
    def _normalize_username(data: dict, phone_number: str, full_name: str) -> str:
        username = (data.get('username') or phone_number or full_name or '').strip()
        if username:
            return username
        return f"member_{uuid4().hex[:12]}"

    @staticmethod
    def _default_farm_name(cooperative_name: str) -> str:
        return f"{cooperative_name} Main Farm"

    @staticmethod
    def _serialize_cooperative(tenant: Tenant) -> dict:
        return {
            'cooperative_id': public_tenant_id(tenant.id),
            'tenant_id': public_tenant_id(tenant.id),
            'cooperative_name': tenant.name,
            'tenant_name': tenant.name,
            'tenant_type': normalize_tenant_type(getattr(tenant, 'tenant_type', None)),
            'region': getattr(tenant, 'region', None),
            'registration_number': getattr(tenant, 'registration_number', None),
            'is_active': tenant.is_active,
        }

    @staticmethod
    def _csv_value(row: dict, *keys: str) -> str:
        for key in keys:
            value = row.get(key)
            if value is None:
                continue
            text_value = str(value).strip()
            if text_value:
                return text_value
        return ''

    @staticmethod
    def create_cooperative(data: dict):
        cooperative_name = (data.get('name') or data.get('cooperative_name') or '').strip()
        region = (data.get('region') or '').strip() or None
        registration_number = (data.get('registration_number') or data.get('registrationNumber') or '').strip() or None
        admin_name = (data.get('admin_name') or data.get('adminName') or '').strip()
        admin_phone = AuthService._normalize_phone_number(data.get('admin_phone_number') or data.get('adminPhoneNumber'))
        admin_username = (data.get('admin_username') or data.get('adminUsername') or admin_phone or '').strip()
        admin_password = data.get('admin_password') or data.get('adminPassword') or ''
        admin_email = (data.get('admin_email') or data.get('adminEmail') or '').strip() or None

        if not cooperative_name:
            return jsonify({'error': 'name is required.'}), 400
        if not region:
            return jsonify({'error': 'region is required.'}), 400
        if not registration_number:
            return jsonify({'error': 'registration_number is required.'}), 400
        if not admin_name:
            return jsonify({'error': 'admin_name is required.'}), 400
        if not admin_username:
            return jsonify({'error': 'admin_username or admin_phone_number is required.'}), 400
        if len(admin_password) < 8:
            return jsonify({'error': 'admin_password must be at least 8 characters.'}), 400

        try:
            tenant = Tenant(
                name=cooperative_name,
                tenant_type='cooperative',
                region=region,
                registration_number=registration_number,
            )
            db.session.add(tenant)
            db.session.flush()

            farm = Farm(tenant_id=tenant.id, name=CooperativeService._default_farm_name(cooperative_name))
            db.session.add(farm)
            db.session.flush()

            admin_user = User(
                tenant_id=tenant.id,
                identifier=f"phone_{admin_phone}" if admin_phone else f"coop_admin_{tenant.id}",
                username=admin_username,
                name=admin_name,
                email=admin_email,
                role=Role.ADMIN,
                is_active=True,
            )
            admin_user.set_password(admin_password)
            db.session.add(admin_user)
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Could not create cooperative due to duplicate fields.'}), 409
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'Registration failed.'}), 500

        access_token, payload = AuthService._issue_token_and_payload(
            user=admin_user,
            tenant=tenant,
            farms=[farm],
            active_farm=farm,
        )

        return jsonify({
            'message': 'Cooperative created successfully.',
            **CooperativeService._serialize_cooperative(tenant),
            'admin': {
                'id': admin_user.id,
                'name': admin_user.name,
                'username': admin_user.username,
                'role': admin_user.role,
            },
            'access_token': access_token,
            **payload,
        }), 201

    @staticmethod
    def invite_member(cooperative_id: str, data: dict):
        try:
            cooperative_pk = int(str(cooperative_id).replace('tenant_', '').strip())
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid cooperative id.'}), 400

        tenant = db.session.get(Tenant, cooperative_pk)
        if not tenant or normalize_tenant_type(getattr(tenant, 'tenant_type', None)) != 'cooperative':
            return jsonify({'error': 'Cooperative not found.'}), 404

        full_name = (data.get('full_name') or data.get('name') or '').strip()
        phone_number = AuthService._normalize_phone_number(data.get('phone_number') or data.get('phoneNumber'))
        email = (data.get('email') or '').strip() or None
        role = (data.get('role') or Role.FARMER).strip() or Role.FARMER

        if not full_name:
            return jsonify({'error': 'full_name is required.'}), 400
        if not phone_number:
            return jsonify({'error': 'phone_number is required.'}), 400

        username = CooperativeService._normalize_username(data, phone_number, full_name)

        try:
            temp_password = uuid4().hex
            member = User(
                tenant_id=tenant.id,
                identifier=f'phone_{phone_number}',
                username=username,
                name=full_name,
                email=email,
                role=role,
                is_active=False,
                farm_location=(data.get('farm_location') or data.get('farmLocation') or data.get('location') or '').strip() or None,
            )
            member.set_password(temp_password)
            db.session.add(member)
            db.session.commit()

            invite_token = create_access_token(
                identity=str(member.id),
                additional_claims={
                    'purpose': 'member_invite',
                    'tenant_id': public_tenant_id(tenant.id),
                    'cooperative_id': public_tenant_id(tenant.id),
                    'tenant_name': tenant.name,
                    'cooperative_name': tenant.name,
                    'role': role,
                    'member_name': full_name,
                    'member_phone_number': phone_number,
                    'farm_location': member.farm_location,
                },
                expires_delta=timedelta(days=CooperativeService.INVITE_TOKEN_EXPIRY_DAYS),
            )
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Could not create member due to duplicate fields.'}), 409
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'Could not create member invite.'}), 500

        frontend_base = current_app.config.get('FRONTEND_BASE_URL', '').rstrip('/')
        invite_path = f'/claim-account?token={invite_token}'
        invite_url = f'{frontend_base}{invite_path}' if frontend_base else invite_path

        return jsonify({
            'message': 'Member invite created successfully.',
            'member': {
                'id': member.id,
                'name': member.name,
                'username': member.username,
                'role': member.role,
                'is_active': member.is_active,
                'farm_location': member.farm_location,
            },
            'invite_token': invite_token,
            'invite_url': invite_url,
            'cooperative_id': public_tenant_id(tenant.id),
            'cooperative_name': tenant.name,
        }), 201

    @staticmethod
    def import_members_from_csv(cooperative_id: str, file_storage):
        try:
            cooperative_pk = int(str(cooperative_id).replace('tenant_', '').strip())
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid cooperative id.'}), 400

        tenant = db.session.get(Tenant, cooperative_pk)
        if not tenant or normalize_tenant_type(getattr(tenant, 'tenant_type', None)) != 'cooperative':
            return jsonify({'error': 'Cooperative not found.'}), 404

        if not file_storage:
            return jsonify({'error': 'CSV file is required.'}), 400

        raw_bytes = file_storage.read()
        if isinstance(raw_bytes, bytes):
            raw_text = raw_bytes.decode('utf-8-sig')
        else:
            raw_text = str(raw_bytes)

        csv_reader = csv.DictReader(io.StringIO(raw_text))
        if not csv_reader.fieldnames:
            return jsonify({'error': 'CSV file must include a header row.'}), 400

        created_members = []
        errors = []

        for row_number, row in enumerate(csv_reader, start=2):
            if not any(str(value).strip() for value in row.values() if value is not None):
                continue

            full_name = CooperativeService._csv_value(row, 'full_name', 'name', 'member_name')
            phone_number = CooperativeService._csv_value(row, 'phone_number', 'phone', 'phoneNumber')
            email = CooperativeService._csv_value(row, 'email') or None
            farm_location = CooperativeService._csv_value(row, 'farm_location', 'farmLocation', 'location') or None
            role = CooperativeService._csv_value(row, 'role') or Role.FARMER
            username = CooperativeService._normalize_username(row, phone_number, full_name)

            if not full_name or not phone_number:
                errors.append({'row': row_number, 'error': 'full_name and phone_number are required.'})
                continue

            normalized_phone = AuthService._normalize_phone_number(phone_number)

            try:
                with db.session.begin_nested():
                    temp_password = uuid4().hex
                    member = User(
                        tenant_id=tenant.id,
                        identifier=f'phone_{normalized_phone}',
                        username=username,
                        name=full_name,
                        email=email,
                        role=role,
                        is_active=False,
                        farm_location=farm_location,
                    )
                    member.set_password(temp_password)
                    db.session.add(member)
                    db.session.flush()

                    invite_token = create_access_token(
                        identity=str(member.id),
                        additional_claims={
                            'purpose': 'member_invite',
                            'tenant_id': public_tenant_id(tenant.id),
                            'cooperative_id': public_tenant_id(tenant.id),
                            'tenant_name': tenant.name,
                            'cooperative_name': tenant.name,
                            'role': role,
                            'member_name': full_name,
                            'member_phone_number': normalized_phone,
                            'farm_location': farm_location,
                        },
                        expires_delta=timedelta(days=CooperativeService.INVITE_TOKEN_EXPIRY_DAYS),
                    )

                    frontend_base = current_app.config.get('FRONTEND_BASE_URL', '').rstrip('/')
                    invite_path = f'/claim-account?token={invite_token}'
                    invite_url = f'{frontend_base}{invite_path}' if frontend_base else invite_path

                    created_members.append({
                        'id': member.id,
                        'name': member.name,
                        'username': member.username,
                        'phone_number': normalized_phone,
                        'farm_location': farm_location,
                        'role': member.role,
                        'is_active': member.is_active,
                        'invite_token': invite_token,
                        'invite_url': invite_url,
                    })
            except IntegrityError:
                errors.append({'row': row_number, 'error': 'Could not create member due to duplicate fields.'})
            except Exception:
                errors.append({'row': row_number, 'error': 'Could not create member from CSV row.'})

        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'Could not import members.'}), 500

        status_code = 201 if not errors else 207
        return jsonify({
            'message': 'CSV member import completed.',
            'cooperative_id': public_tenant_id(tenant.id),
            'cooperative_name': tenant.name,
            'created_count': len(created_members),
            'error_count': len(errors),
            'members': created_members,
            'errors': errors,
        }), status_code

    @staticmethod
    def claim_member_invite(token: str, password: str):
        try:
            decoded = decode_token(token)
        except Exception:
            return jsonify({'error': 'Invalid or expired invite token.'}), 400

        if decoded.get('purpose') != 'member_invite':
            return jsonify({'error': 'Invalid invite token.'}), 400

        try:
            member_id = int(decoded.get('sub'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid invite token subject.'}), 400

        member = db.session.get(User, member_id)
        if not member:
            return jsonify({'error': 'Member not found.'}), 404

        member.set_password(password)
        member.is_active = True
        db.session.commit()

        tenant = getattr(member, 'tenant', None)
        if tenant is None:
            return jsonify({'error': 'Cooperative context missing.'}), 400

        farms = list(getattr(tenant, 'farms', []) or [])
        if not farms:
            farm = Farm(tenant_id=tenant.id, name=CooperativeService._default_farm_name(tenant.name))
            db.session.add(farm)
            db.session.commit()
            farms = [farm]

        active_farm = farms[0]
        access_token, payload = AuthService._issue_token_and_payload(
            user=member,
            tenant=tenant,
            farms=farms,
            active_farm=active_farm,
        )

        return jsonify({
            'message': 'Account claimed successfully.',
            'access_token': access_token,
            **payload,
        }), 200