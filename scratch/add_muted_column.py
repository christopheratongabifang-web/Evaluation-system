from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE user ADD COLUMN is_muted BOOLEAN DEFAULT 0 NOT NULL'))
        db.session.commit()
        print("Success: is_muted column added.")
    except Exception as e:
        print(f"Error or already exists: {e}")
