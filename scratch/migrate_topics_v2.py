from app import app, db
from sqlalchemy import text

with app.app_context():
    # Try creating the table
    try:
        db.session.execute(text('''
            CREATE TABLE IF NOT EXISTS evaluation_topic (
                id INTEGER PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        '''))
        db.session.commit()
        print("Success: EvaluationTopic table ensured.")
    except Exception as e:
        print(f"Topic table error: {e}")

    # Try adding the column
    try:
        db.session.execute(text('ALTER TABLE evaluation ADD COLUMN topic_id INTEGER REFERENCES evaluation_topic(id)'))
        db.session.commit()
        print("Success: topic_id column added to evaluation.")
    except Exception as e:
        if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
            print("Column topic_id already exists.")
        else:
            print(f"Column error: {e}")
