import os

MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:secret@172.17.0.1:30001")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", str(1024 * 1024 * 1024)))  # default 1GB
JWT_SECRET = os.getenv("JWT_SECRET", "very_secret_key")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "admin_secret_key")
