import os
import secrets
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    database_url = os.getenv("DATABASE_URL") or "mysql+pymysql://root:your_password@localhost/aseel_laundry?charset=utf8mb4"
    if database_url.startswith("mysql://"):
        database_url = database_url.replace("mysql://", "mysql+pymysql://", 1)
    if not database_url.startswith("mysql+pymysql://"):
        raise RuntimeError("This project requires MySQL. Set DATABASE_URL to a mysql+pymysql:// connection URL.")
    SQLALCHEMY_DATABASE_URI = database_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
