from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE evaluation ADD COLUMN category_id INTEGER REFERENCES category(id)'))
        db.session.commit()
        print("Success: category_id column added to evaluation.")
    except Exception as e:
        print(f"Error or already exists: {e}")
