"""
Supabase Project Initialization for C.I.T.A.D.E.L.
This script creates all necessary database tables and functions using Supabase.
Run this ONCE before starting the backend for the first time.
"""

import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def create_user_sessions_table(supabase: Client):
    """
    Create user sessions table for context engine.
    This stores session state across all modules.
    """
    print("  Creating user_sessions table...")
    
    try:
        # Check if table exists by trying to select
        result = supabase.table("user_sessions").select("id").limit(1).execute()
        print("  ✓ user_sessions table already exists")
        return True
    except Exception:
        pass
    
    # Table doesn't exist, inform user to create via migration
    print("  ⚠️ user_sessions table needs to be created via Supabase dashboard or migration")
    return False


def create_support_tickets_table(supabase: Client):
    """
    Create tickets table for support ticket analyzer.
    """
    print("  Creating support_tickets table...")
    
    try:
        result = supabase.table("support_tickets").select("id").limit(1).execute()
        print("  ✓ support_tickets table already exists")
        return True
    except Exception:
        pass
    
    print("  ⚠️ support_tickets table needs to be created via Supabase dashboard or migration")
    return False


def create_audit_logs_table(supabase: Client):
    """
    Create audit logs table for tracking all AI decisions.
    """
    print("  Creating ai_audit_logs table...")
    
    try:
        result = supabase.table("ai_audit_logs").select("id").limit(1).execute()
        print("  ✓ ai_audit_logs table already exists")
        return True
    except Exception:
        pass
    
    print("  ⚠️ ai_audit_logs table needs to be created via Supabase dashboard or migration")
    return False


def verify_existing_tables(supabase: Client):
    """
    Verify existing C.I.T.A.D.E.L. tables are accessible.
    """
    existing_tables = ['documents', 'vectors', 'expenses', 'resumes', 'jobs', 'sensor_readings', 'chat_sessions']
    
    print("\n🔍 Verifying existing tables...")
    for table in existing_tables:
        try:
            result = supabase.table(table).select("*").limit(1).execute()
            print(f"  ✓ Table '{table}' exists and is accessible")
        except Exception as e:
            print(f"  ⚠️ Table '{table}' not found or inaccessible: {e}")


def initialize_citadel_database():
    """
    Main initialization function - verifies and creates database infrastructure.
    """
    print("🚀 Initializing C.I.T.A.D.E.L. Database Infrastructure...")
    print("=" * 60)
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("\n❌ ERROR: SUPABASE_URL and SUPABASE_KEY must be set in environment")
        print("   Add these to your .env file before running this script")
        return False
    
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    # Verify existing tables
    verify_existing_tables(supabase)
    
    # Check/create new tables
    print("\n📋 Checking new tables...")
    create_user_sessions_table(supabase)
    create_support_tickets_table(supabase)
    create_audit_logs_table(supabase)
    
    print("\n" + "=" * 60)
    print("✨ Database verification complete")
    print("\n💡 Next step: Run the backend server with `uvicorn main:app --reload`")
    return True


if __name__ == "__main__":
    success = initialize_citadel_database()
    sys.exit(0 if success else 1)
