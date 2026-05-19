from app import app, db
from sqlalchemy import text

def run_migration():
    with app.app_context():
        try:
            print("Adding student_class to student_profile...")
            db.session.execute(text("ALTER TABLE student_profile ADD COLUMN student_class VARCHAR(50) NULL;"))
        except Exception as e:
            print(f"Column might already exist: {e}")
            db.session.rollback()
            
        try:
            print("Adding target_class to book...")
            db.session.execute(text("ALTER TABLE book ADD COLUMN target_class VARCHAR(50) DEFAULT 'All' NOT NULL;"))
        except Exception as e:
            print(f"Column might already exist: {e}")
            db.session.rollback()

        try:
            print("Adding target_class to evaluation...")
            db.session.execute(text("ALTER TABLE evaluation ADD COLUMN target_class VARCHAR(50) DEFAULT 'All' NOT NULL;"))
        except Exception as e:
            print(f"Column might already exist: {e}")
            db.session.rollback()

        try:
            print("Adding target_class to assignment...")
            db.session.execute(text("ALTER TABLE assignment ADD COLUMN target_class VARCHAR(50) DEFAULT 'All' NOT NULL;"))
        except Exception as e:
            print(f"Column might already exist: {e}")
            db.session.rollback()

        db.session.commit()
        print("Migration complete!")

if __name__ == '__main__':
    run_migration()
