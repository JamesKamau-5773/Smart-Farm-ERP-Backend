from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import Config

db = SQLAlchemy()
bcrypt = Bcrypt()
jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)

    # Register Blueprints here (Auth, Livestock, etc.)
    from app.api.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    return app