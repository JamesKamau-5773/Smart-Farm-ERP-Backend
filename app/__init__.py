from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from config import Config

# Globally accessible libraries
db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address)
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

    # Register Blueprints here (Auth, Livestock, etc.)
    from app.models import user
    from app.models import livestock
    from app.models import supply
    from app.models import finance
    from app.models import audit


    from app.api.clinical import clinical_bp
    from app.api.auth import auth_bp
    from app.api.operations import operations_bp
    from app.api.finance import finance_bp
    
    # Register Global Error Handlers
    from app.utils.errors import register_error_handlers
    register_error_handlers(app)

    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(clinical_bp, url_prefix='/api/clinical')
    app.register_blueprint(operations_bp, url_prefix='/api/operations')
    app.register_blueprint(finance_bp, url_prefix='/api/finance')

    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "Jivu Farm ERP Backend Online",
            "version": "1.0",
        }), 200

    return app

    