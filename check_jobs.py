import os
import sys
import psycopg2
from dotenv import load_dotenv

# Load environment variables (to get DATABASE_URL)
load_dotenv()

def check_active_jobs():
    """
    Checks if any AI Agents are currently working.
    Returns Exit Code 1 if busy (blocking deployment).
    Returns Exit Code 0 if idle (allowing deployment).
    """
    try:
        # Connect to Database
        conn = psycopg2.connect(os.getenv("DATABASE_URL"))
        cur = conn.cursor()
        
        # Check for any chapters where the AI is still 'Processing'
        # This matches the status we set in the background_writer_task
        cur.execute("SELECT count(*) FROM book_chapters WHERE status = 'Processing'")
        active_count = cur.fetchone()[0]
        
        cur.close()
        conn.close()
        
        if active_count > 0:
            print(f"⚠️  DEPLOYMENT ABORTED: {active_count} active AI jobs detected.")
            print("The system is busy writing/researching. Restarting now would kill these tasks.")
            sys.exit(1)  # Signal failure to bash script
        else:
            print("✅  System is idle. Safe to restart.")
            sys.exit(0)  # Signal success
            
    except Exception as e:
        print(f"Error checking system status: {e}")
        # If we can't check, it's safer to abort than to risk killing a job
        sys.exit(1)

if __name__ == "__main__":
    check_active_jobs()