#!/usr/bin/env python
from app import app, db
from models import User

if __name__ == '__main__':
    with app.app_context():
        user = User.query.filter_by(username='Abifang Christopher').first()
        if user:
            print(f"Found: {user.username}, is_admin before: {user.is_admin}")
            user.is_admin = True
            db.session.commit()
            print(f"Success! {user.username} is now admin: {user.is_admin}")
        else:
            all_users = User.query.all()
            print(f"User not found. Available users: {[u.username for u in all_users]}")
