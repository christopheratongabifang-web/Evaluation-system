import os
from sqlalchemy import create_engine, text

# Use the same connection string you plan to use in app.py
DATABASE_URL = 'postgresql://library_user:Abifang@localhost:5432/library_db'

try:
    # Create engine and try to connect
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("✅ Successfully connected to PostgreSQL!")
        print(f"Query result: {result.fetchone()}")
        
        # Optionally check if tables exist
        tables = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """))
        table_list = [row[0] for row in tables]
        if table_list:
            print(f"\n📋 Existing tables in 'library_db': {', '.join(table_list)}")
        else:
            print("\n⚠️ No tables found. Run your Flask app to create them.")
        
except Exception as e:
    print(f"❌ Connection failed: {e}")