import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import User

with app.app_context():
    admins = User.query.filter_by(is_admin=True).all()
    print('Admin count:', len(admins))
    for a in admins:
        print('ADMIN:', a.id, a.username, a.email, a.phone_number)
    print('\nAll users (first 50):')
    users = User.query.order_by(User.id.asc()).limit(50).all()
    for u in users:
        print(u.id, u.username, u.email, u.phone_number, 'is_admin=' + str(u.is_admin))
