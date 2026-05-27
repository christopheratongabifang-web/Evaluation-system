from app import app, db
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            with db.engine.connect() as conn:
                # Add the missing columns for OTP functionality
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS reset_otp VARCHAR(6)'))
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS reset_otp_expires_at TIMESTAMP'))
                conn.commit()
                print("Successfully added OTP columns to user table.")
        except Exception as e:
            print(f"Migration error: {e}")

if __name__ == "__main__":
    migrate()
