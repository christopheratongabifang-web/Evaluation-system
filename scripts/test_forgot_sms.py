import os
import sys
# Ensure project root is on sys.path so imports like `from app import app` work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db, bcrypt
from models import User
import re

with app.app_context():
    user = User.query.filter(User.phone_number != None).first()
    if user:
        print('Found existing user with phone:', user.phone_number)
    else:
        print('No user with phone found; creating test user +15550001111')
        user = User(username='testuser', email='testuser@example.com', phone_number='+15550001111', password_hash=bcrypt.generate_password_hash('ChangeMe123!').decode('utf-8'), is_admin=False)
        db.session.add(user)
        db.session.commit()
    client = app.test_client()
    # First GET the form to obtain a CSRF token injected into the page
    get_resp = client.get('/forgot_password')
    html = get_resp.get_data(as_text=True)
    token = None
    m = re.search(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', html)
    if m:
        token = m.group(1)
    else:
        m2 = re.search(r'<input[^>]+name="csrf_token"[^>]+value="([^"]+)"', html)
        if m2:
            token = m2.group(1)

    post_data = {'phone_number': user.phone_number}
    if token:
        post_data['csrf_token'] = token

    resp = client.post('/forgot_password', data=post_data, follow_redirects=True)
    print('POST /forgot_password status:', resp.status_code)
    content = resp.get_data(as_text=True)
    print('--- Response start ---')
    print(content[:2000])
    print('--- Response end ---')
