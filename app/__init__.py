from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from config import Config
from flask_cors import CORS

from app.celery_utils import make_celery
db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address, strategy="fixed-window")
migrate = Migrate()
celery = None  # Initialised by create_app(); imported by app.tasks.*

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Override the default rate-limiter key_func to use our tenant-based one.
    # This is done inside create_app to avoid circular imports at the top level.
    from app.utils.rate_limiting import tenant_based_key_func
    limiter.key_func = tenant_based_key_func

    # Initialize Plugins
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)
    migrate.init_app(app, db)

    # Initialize CORS properly and explicitly allow your frontend
    CORS(app, supports_credentials=True, origins=[
        "https://jivu-smart-dairy-system.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173"
    ])

    global celery
    celery = make_celery(app)

    @app.after_request
    def add_security_headers(response):
        # Baseline hardening for browser responses.
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        return response

    # Register the middleware
    from app.middleware import (
        begin_idempotent_request,
        complete_idempotent_request,
        enforce_required_password_reset,
        set_tenant_context,
    )
    app.before_request(set_tenant_context)
    app.before_request(enforce_required_password_reset)
    app.before_request(begin_idempotent_request)
    app.after_request(complete_idempotent_request)


    # --- Model Imports for Alembic Autodiscovery ---
    # These imports are necessary for Flask-Migrate to detect all model
    # classes and generate correct migration scripts. By importing the modules
    # here, we ensure all model classes are registered with SQLAlchemy's metadata.
    # We import model classes directly from their modules to avoid circular dependencies.
    from app.models.user import User
    from app.models.user import RevokedToken
    from app.models.finance import Buyer, Customer, Delivery, Receipt, SalesLedger, Transaction
    from app.models.supply import MilkDisposition, MilkLog # Inferred from finance API
    # The following modules are also imported for model discovery by Alembic.
    # The Cow model is imported from livestock.py as per the diagnosis.
    from app.models.livestock import Cow
    from app.models.audit import AuditLog
    from app.models.tenant import Tenant
    from app.models.farm import Farm
    from app.models.hr import Employee, Payroll, PayrollRun, PayrollRunLineItem
    # Correcting Genetics to GeneticProfile based on the relationship in the Cow model
    from app.models.genetics import GeneticProfile
    from app.models.messaging import ChatSession
    from app.models.idempotency import IdempotencyRecord

    @jwt.token_in_blocklist_loader
    def is_token_revoked(_jwt_header, jwt_payload):
        token_id = jwt_payload.get('jti')
        return bool(token_id and RevokedToken.query.filter_by(jti=token_id).first())

    # --- Blueprint Registration ---
    from app.api.clinical import clinical_bp
    from app.api.auth import auth_bp
    from app.api.operations import operations_bp, operations_alias_bp
    from app.api.breeding import breeding_bp
    from app.api.export import export_bp
    from app.api.inventory import inventory_bp
    from app.api.finance import finance_bp
    from app.api.webhooks import webhooks_bp
    from app.api.whatsapp_webhook import whatsapp_bp
    from app.api.hr import hr_bp
    from app.api.tenant import tenant_bp
    from app.api.feed import feed_bp
    from app.api.nutrition import nutrition_bp
    from app.api.nutrition import nutrition_alias_bp
    from app.api.dashboard import dashboard_bp
    from app.api.herdsman import herdsman_bp
    from app.api.clinical import medical_alias_bp, safety_bp, veterinary_bp
    from app.api.herd import herd_bp
    from app.api.genetics import genetics_bp
    from app.api.reports import reports_bp
    from app.api.uploads import uploads_bp
    from app.api.milk_dispositions import milk_dispositions_bp
    from app.api.onboarding import onboarding_bp
    from app.api import api_bp

    # Register Global Error Handlers
    from app.utils.errors import register_error_handlers
    register_error_handlers(app)

    from app.utils.db_init import ensure_super_admin_account
    app.extensions.setdefault('super_admin_bootstrapped', False)

    @app.before_request
    def ensure_bootstrapped_super_admin():
        if request.endpoint == 'whatsapp.verify_webhook':
            return None
        if app.extensions.get('super_admin_bootstrapped'):
            return None
        ensure_super_admin_account()
        app.extensions['super_admin_bootstrapped'] = True

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(clinical_bp, url_prefix='/api/clinical')
    app.register_blueprint(operations_bp, url_prefix='/api/operations')
    app.register_blueprint(operations_alias_bp)
    app.register_blueprint(breeding_bp, url_prefix='/api/v1/breeding')
    app.register_blueprint(export_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(finance_bp, url_prefix='/api/finance')
    app.register_blueprint(finance_bp, url_prefix='/api', name='finance_legacy')
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(whatsapp_bp)
    app.register_blueprint(hr_bp, url_prefix='/api/hr')
    app.register_blueprint(tenant_bp, url_prefix='/api/tenant')
    app.register_blueprint(feed_bp)
    app.register_blueprint(nutrition_bp)
    app.register_blueprint(nutrition_alias_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(herdsman_bp)
    app.register_blueprint(medical_alias_bp)
    app.register_blueprint(herd_bp, url_prefix='/api/herd')
    app.register_blueprint(safety_bp)
    app.register_blueprint(veterinary_bp)
    app.register_blueprint(genetics_bp, url_prefix='/api/v1/genetics')
    app.register_blueprint(reports_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(milk_dispositions_bp)
    app.register_blueprint(onboarding_bp, url_prefix='/api/onboarding')
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "Jivu Farm ERP Backend Online",
            "version": "1.0",
        }), 200

    return app
