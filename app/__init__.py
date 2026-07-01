from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from config import Config

from app.celery_utils import make_celery
from app.utils.rate_limiting import tenant_based_key_func
# Globally accessible libraries
db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()
limiter = Limiter(key_func=tenant_based_key_func, strategy="fixed-window")
migrate = Migrate()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize Plugins
    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)
    migrate.init_app(app, db)

    celery = make_celery(app)

    @app.before_request
    def handle_cors_preflight():
        if request.method != 'OPTIONS':
            return None
        response = app.make_response(('', 200))
        return response

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get('Origin', '*')
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = request.headers.get(
            'Access-Control-Request-Headers',
            'Authorization,Content-Type,X-Tenant-ID,X-Farm-ID',
        )
        response.headers['Access-Control-Allow-Methods'] = 'GET,POST,PATCH,PUT,DELETE,OPTIONS'
        return response

    # Register the middleware
    from app.middleware import set_tenant_context
    app.before_request(set_tenant_context)


    # Register Blueprints here (Auth, Livestock, etc.)
    from app.models import user
    from app.models import livestock
    from app.models import supply
    from app.models import finance
    from app.models import audit
    from app.models import tenant
    from app.models import farm
    from app.models import hr


    from app.api.clinical import clinical_bp
    from app.api.auth import auth_bp
    from app.api.operations import operations_bp, operations_alias_bp
    from app.api.breeding import breeding_bp
    from app.api.export import export_bp
    from app.api.inventory import inventory_bp
    from app.api.finance import finance_bp
    from app.api.hr import hr_bp
    from app.api.tenant import tenant_bp
    from app.api.feed import feed_bp
    from app.api.nutrition import nutrition_bp
    from app.api.nutrition import nutrition_alias_bp
    from app.api.dashboard import dashboard_bp
    from app.api.herdsman import herdsman_bp
    from app.api.clinical import medical_alias_bp, safety_bp, veterinary_bp
    
    # Register Global Error Handlers
    from app.utils.errors import register_error_handlers
    register_error_handlers(app)

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(clinical_bp, url_prefix='/api/clinical')
    app.register_blueprint(operations_bp, url_prefix='/api/operations')
    app.register_blueprint(operations_alias_bp)
    app.register_blueprint(breeding_bp, url_prefix='/api/v1/breeding')
    app.register_blueprint(export_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(finance_bp, url_prefix='/api/finance')
    app.register_blueprint(hr_bp, url_prefix='/api/hr')
    app.register_blueprint(tenant_bp, url_prefix='/api/tenant')
    app.register_blueprint(feed_bp)
    app.register_blueprint(nutrition_bp)
    app.register_blueprint(nutrition_alias_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(herdsman_bp)
    app.register_blueprint(medical_alias_bp)
    app.register_blueprint(safety_bp)
    app.register_blueprint(veterinary_bp)

    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "Jivu Farm ERP Backend Online",
            "version": "1.0",
        }), 200

    return app

    