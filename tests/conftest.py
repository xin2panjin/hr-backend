import sys
from pathlib import Path
import os

os.environ.setdefault("DB_USERNAME", "postgres")
os.environ.setdefault("DB_PASSWORD", "postgres")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("MAIL_USERNAME", "hr@example.com")
os.environ.setdefault("MAIL_PASSWORD", "mail-password")
os.environ.setdefault("DASHSCOPE_API_KEY", "dashscope-key")
os.environ.setdefault("DINGTALK_APP_KEY", "dingtalk-key")
os.environ.setdefault("DINGTALK_APP_SECRET", "dingtalk-secret")
os.environ.setdefault("PADDLE_OCR_ACCESS_TOKEN", "ocr-token")

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
