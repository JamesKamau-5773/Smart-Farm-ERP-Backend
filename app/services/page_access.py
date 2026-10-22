from __future__ import annotations

from flask import g, jsonify, request

PAGE_ACCESS = {
    'dashboard': 'Command Center', 'production': 'Production and milk usage',
    'tasks': 'Daily routine and task view', 'herd': 'Cow register and animal records',
    'breeding': 'Breeding and genetics', 'medical': 'Medical records and veterinary care',
    'feed': 'Feed planning and milk lab', 'customers': 'Customer and buyer management',
    'finance': 'Ledger and financial reports', 'inventory': 'Inventory',
    'reports': 'Farm and milk reports', 'safety': 'Safety dashboard',
    'staff': 'Staff registry', 'payroll': 'Payroll', 'member_admin': 'Member onboarding',
}

ROLE_DEFAULT_PAGE_ACCESS = {
    'FARMER': list(PAGE_ACCESS),
    'ADMIN': list(PAGE_ACCESS),
    'SUPER_ADMIN': list(PAGE_ACCESS),
    'FARM_HAND': ['production', 'tasks', 'herd', 'feed'],
    'VETERINARY_DOCTOR': ['herd', 'breeding', 'medical'],
    'FARM_SUPERVISOR': ['production', 'tasks', 'herd', 'breeding', 'medical', 'feed', 'reports', 'safety'],
    'FARM_MANAGER': ['dashboard', 'production', 'tasks', 'herd', 'breeding', 'medical', 'feed', 'customers', 'reports', 'safety'],
    'FARM_ADMIN': list(PAGE_ACCESS),
}


def normalize_page_access(value, role=None):
    if value is None:
        return sorted(set(ROLE_DEFAULT_PAGE_ACCESS.get(str(role or '').upper(), [])))
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('page_access must be a list of page access keys.')
    normalized = sorted(set(value))
    invalid = [item for item in normalized if item not in PAGE_ACCESS]
    if invalid:
        raise ValueError(f'Unknown page access keys: {", ".join(invalid)}.')
    return normalized


def page_key_for_path(path: str):
    path = path or ''
    if path.startswith(('/api/breeding/', '/api/breeding')):
        return 'breeding'
    if path.startswith('/api/herd/genetic-progress'):
        return 'breeding'
    if path.startswith(('/api/v1/tasks/', '/api/routine/')):
        return 'tasks'
    if path.startswith(('/api/v1/herd/feeding-plan', '/api/v1/feed/', '/api/lab/', '/api/clerk/')):
        return 'feed'
    if path.startswith(('/api/v1/animals/', '/api/animals/')) and 'yield-target' in path:
        return 'feed'
    if path.startswith(('/api/v1/animals/', '/api/animals/')):
        return 'herd'
    if path.startswith(('/api/ledger', '/api/deliveries', '/api/transactions', '/api/receipts', '/api/buyers')):
        return 'finance'
    if path.startswith('/api/production/milk-drop-alerts'):
        return 'medical'
    if path.startswith('/api/export/'):
        return 'herd'
    if path.startswith('/api/hr/payroll'):
        return 'payroll'
    if path.startswith('/api/hr/'):
        return 'staff'
    if path.startswith('/api/onboarding/'):
        return 'member_admin'
    if path.startswith(('/api/tenant/cooperatives/', '/api/tenant/members/')):
        return 'member_admin'
    if path.startswith('/api/finance/'):
        return 'customers' if any(part in path for part in ('/customers', '/buyers')) else 'finance'
    if path.startswith(('/api/buyers/', '/api/customers/')):
        return 'customers'
    if path.startswith('/api/inventory'):
        return 'inventory'
    if path.startswith('/api/reports'):
        return 'reports'
    if path.startswith(('/api/safety', '/api/api/safety')):
        return 'safety'
    if path.startswith(('/api/clinical/', '/api/veterinary/', '/api/medical/')):
        return 'medical'
    if path.startswith(('/api/v1/breeding/', '/api/v1/genetics/')):
        return 'breeding'
    if path.startswith(('/api/nutrition/', '/api/feed/', '/api/v1/feed/', '/api/v1/nutrition/')):
        return 'feed'
    if path.startswith('/api/herdsman/'):
        return 'tasks'
    if path.startswith('/api/herd/'):
        return 'herd'
    if path.startswith('/api/operations/'):
        if any(part in path for part in ('breeding', 'semen', 'heat-observations', 'genetic-progress')):
            return 'breeding'
        if any(part in path for part in ('medical', 'vet', 'clinical', 'milk-drop-alerts')):
            return 'medical'
        if any(part in path for part in ('herd', 'animals', 'cows', 'calving')):
            return 'herd'
        if any(part in path for part in ('lab', 'clerk')):
            return 'feed'
        return 'production'
    if path.startswith(('/api/production/', '/api/milk-dispositions/')):
        return 'production'
    if path.startswith('/api/v1/dashboard/'):
        return 'dashboard'
    if path in {'/api/dashboard', '/api/command-center'} or path.startswith(('/api/dashboard/', '/api/command-center/')):
        return 'dashboard'
    if path.startswith('/api/') and any(part in path for part in ('/milk-logs', '/production-log', '/milk-production')):
        return 'production'
    return None


def enforce_page_access():
    if request.method == 'OPTIONS' or not request.path.startswith('/api/'):
        return None
    actor_id = getattr(g, 'actor_id', None)
    page_key = page_key_for_path(request.path)
    if actor_id is None or page_key is None:
        return None
    from app import db
    from app.models.user import User
    user = db.session.get(User, int(actor_id))
    page_access = normalize_page_access(getattr(user, 'page_access', None), getattr(user, 'role', None)) if user else []
    if user and page_key not in page_access:
        return jsonify({'error': 'This page is not included in your farm access.'}), 403
    return None
