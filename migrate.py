import os
import psycopg2
from dotenv import load_dotenv

# 1. Load the Environment Variables (from the server's .env file)
load_dotenv()

# 2. Get the Master Key
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    print("❌ Migration Error: DATABASE_URL is missing.")
    # We exit with code 1 so the deployment stops if this fails
    exit(1)

def run_migration():
    print("🔄 Starting Database Migration...")
    
    try:
        # 3. Connect to the Database
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # 4. Read the Blueprint (schema.sql)
        with open("schema.sql", "r") as file:
            sql_script = file.read()

        # 5. Execute the changes
        cur.execute(sql_script)
        conn.commit()
        
        print("✅ Database Schema Applied Successfully!")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"💥 Migration Failed: {e}")
        exit(1)

if __name__ == "__main__":
    run_migration()
