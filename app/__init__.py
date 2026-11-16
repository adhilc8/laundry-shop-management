from flask import Flask
from pathlib import Path
import shutil
from config import Config
from .extensions import db, login_manager, csrf, migrate, limiter

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["ORDER_UPLOAD_FOLDER"] = str(Path(app.instance_path) / "uploads" / "orders")
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    csrf.init_app(app)
    limiter.init_app(app)

    from .routes import main, auth, customer, admin, staff, delivery
    for bp in (main, auth, customer, admin, staff, delivery):
        app.register_blueprint(bp)

    # Move legacy uploads out of the public static tree into private instance storage.
    legacy_uploads = Path(app.static_folder) / "uploads" / "orders"
    private_uploads = Path(app.config["ORDER_UPLOAD_FOLDER"])
    if legacy_uploads.exists():
        private_uploads.mkdir(parents=True, exist_ok=True)
        for old_file in legacy_uploads.iterdir():
            if old_file.is_file():
                new_file = private_uploads / old_file.name
                if new_file.exists():
                    old_file.unlink()
                else:
                    shutil.move(str(old_file), str(new_file))
        try:
            legacy_uploads.rmdir()
            legacy_uploads.parent.rmdir()
        except OSError:
            pass

    return app
