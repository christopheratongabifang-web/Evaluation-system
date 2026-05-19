from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                # Add the missing columns for the proctoring feature
                conn.execute(text("ALTER TABLE evaluation_attempt ADD COLUMN IF NOT EXISTS latest_snapshot TEXT"))
                conn.execute(text("ALTER TABLE evaluation_attempt ADD COLUMN IF NOT EXISTS last_snapshot_time TIMESTAMP"))
                conn.commit()
                print("Successfully updated PostgreSQL schema with proctoring columns.")
        except Exception as e:
            print(f"Migration error: {e}")

if __name__ == "__main__":
    migrate()
