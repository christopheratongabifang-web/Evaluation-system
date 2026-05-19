from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE assignment_submission ADD COLUMN grade FLOAT'))
        db.session.execute(text('ALTER TABLE assignment_submission ADD COLUMN feedback TEXT'))
        db.session.execute(text('ALTER TABLE assignment_submission ADD COLUMN is_graded BOOLEAN DEFAULT 0'))
        db.session.commit()
        print("Success: grade, feedback, and is_graded columns added to assignment_submission.")
    except Exception as e:
        print(f"Error or already exists: {e}")
