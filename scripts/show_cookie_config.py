import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app

with app.app_context():
    print('SESSION_COOKIE_SECURE =', app.config.get('SESSION_COOKIE_SECURE'))
    print('REMEMBER_COOKIE_SECURE =', app.config.get('REMEMBER_COOKIE_SECURE'))
    print('SESSION_COOKIE_HTTPONLY =', app.config.get('SESSION_COOKIE_HTTPONLY'))
    print('SESSION_COOKIE_SAMESITE =', app.config.get('SESSION_COOKIE_SAMESITE'))
    print('FLASK_ENV =', os.environ.get('FLASK_ENV'))
    print('ENABLE_SECURE_COOKIES =', os.environ.get('ENABLE_SECURE_COOKIES'))
