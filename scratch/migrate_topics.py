from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        # Create the new table
        db.session.execute(text('''
            CREATE TABLE evaluation_topic (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        '''))
        
        # Add the new column to evaluation
        db.session.execute(text('ALTER TABLE evaluation ADD COLUMN topic_id INTEGER REFERENCES evaluation_topic(id)'))
        
        # Drop the old column if it exists (Optional, but let's keep it safe for now by just adding the new one)
        # db.session.execute(text('ALTER TABLE evaluation DROP COLUMN category_id'))
        
        db.session.commit()
        print("Success: EvaluationTopic table created and evaluation table updated.")
    except Exception as e:
        print(f"Error or already exists: {e}")
