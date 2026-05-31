from app import app, db, bcrypt
from models import User

DEFAULT_ADMIN_USERNAME = 'admin'
DEFAULT_ADMIN_EMAIL = 'admin@example.com'
DEFAULT_ADMIN_PASSWORD = 'ChangeMe123!'

with app.app_context():
    db.create_all()
    existing = User.query.filter_by(username=DEFAULT_ADMIN_USERNAME).first()
    if existing:
        print(f"Admin user already exists: {existing.username} <{existing.email}>")
    else:
        hashed = bcrypt.generate_password_hash(DEFAULT_ADMIN_PASSWORD).decode('utf-8')
        user = User(username=DEFAULT_ADMIN_USERNAME, email=DEFAULT_ADMIN_EMAIL, password_hash=hashed, is_admin=True)
        db.session.add(user)
        db.session.commit()
        print(f"Created admin user: {DEFAULT_ADMIN_USERNAME} with password: {DEFAULT_ADMIN_PASSWORD}")
