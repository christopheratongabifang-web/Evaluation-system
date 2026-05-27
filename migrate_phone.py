from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                # Add the missing phone_number column
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20) UNIQUE'))
                conn.commit()
                print("Successfully added phone_number column to user table.")
        except Exception as e:
            print(f"Migration error: {e}")

if __name__ == "__main__":
    migrate()
