import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app, db, bcrypt
from models import User

def usage():
    print('Usage: python scripts/reset_user_password.py <username_or_email> <new_password>')

if __name__ == '__main__':
    if len(sys.argv) < 3:
        usage(); sys.exit(1)
    identifier = sys.argv[1]
    new_password = sys.argv[2]

    with app.app_context():
        user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
        if not user:
            print('User not found for identifier:', identifier)
            sys.exit(2)
        if len(new_password) < 8:
            print('Password must be at least 8 characters long')
            sys.exit(3)
        user.password_hash = bcrypt.generate_password_hash(new_password).decode('utf-8')
        db.session.commit()
        print(f'Success: password for {user.username} ({user.email}) updated.')
