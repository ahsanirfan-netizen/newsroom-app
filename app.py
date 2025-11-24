import streamlit as st
import requests
import traceback
import os
import google.generativeai as genai
from exa_py import Exa
from openai import OpenAI
from linkup import LinkupClient
from dotenv import load_dotenv

# ==============================================================================
# 🛠️ KEYS
# ==============================================================================
load_dotenv()
try:
    EXA_KEY = os.getenv("EXA_KEY")
    PERPLEXITY_KEY = os.getenv("PERPLEXITY_KEY")
    LINKUP_KEY = os.getenv("LINKUP_KEY")
    GEMINI_KEY = os.getenv("GEMINI_KEY")
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
except Exception:
    st.error("Missing Keys!")
    st.stop()

# ==============================================================================
# ⚙️ SETUP
# ==============================================================================
st.set_page_config(page_title="Newsroom AI", page_icon="📖")
st.title("🚀 The Newsroom")

try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 📱 THE UI (Updated)
# ==============================================================================
with st.sidebar:
    st.header("📚 Your Book")
    
    # FETCH HISTORY
    try:
        rows = requests.get(
            f"{SUPABASE_URL}/rest/v1/book_chapters?select=topic,created_at&order=created_at.desc",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        ).json()
        if len(rows) > 0:
            for row in rows:
                st.text(f"📄 {row['topic']}")
        else:
            st.caption("No chapters yet.")
    except:
        st.caption("Loading...")

    st.divider()
    
 # --- NEW SECTION: CHARACTERS ---
    # ... (inside with st.sidebar) ...

    st.divider()
    st.header("🎭 Dramatis Personae")
    
    # 1. FETCH CHARACTERS (Debug Version)
    st.caption("Debug: Fetching list...")
    
    try:
        # We perform the GET request
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/characters?select=name,role",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}"
            }
        )
        
        # Check if the request succeeded
        if response.status_code == 200:
            chars = response.json()
            if len(chars) > 0:
                for c in chars:
                        # Use .get() to avoid crashing if 'role' is None
                        role_display = c.get('role') or "Unknown Role"
                        st.text(f"👤 {c['name']} ({role_display})")

            else:
                st.info("Table found, but empty.")
        else:
            # PRINT THE ERROR IF IT FAILS
            st.error(f"Fetch Error {response.status_code}: {response.text}")

    except Exception as e:
        st.error(f"System Error: {e}")

    # 2. ADD NEW CHARACTER (Debug Version)
    with st.expander("Add Character"):
        new_name = st.text_input("Name")
        new_role = st.text_input("Role (e.g. Emperor)")
        
        if st.button("Save Char"):
            # Check for duplicates before sending? No, let the DB handle it.
            res = requests.post(
                f"{SUPABASE_URL}/rest/v1/characters",
                headers={
                    "apikey": SUPABASE_KEY,
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json={"name": new_name, "role": new_role}
            )
            
            if res.status_code == 201:
                st.success("Saved!")
                st.rerun()
            elif res.status_code == 409:
                st.warning(f"'{new_name}' already exists!")
            else:
                st.error(f"Save Error {res.status_code}: {res.text}")

# --- MAIN BUTTON ---
if st.button("✍️ Write & Save Chapter", type="primary"):
    # (Keep your existing logic here, I won't repeat it to save space)
    # Just ensure you have the existing code block for "Physics Check", "Research", etc.
    st.info("Generating... (This logic is unchanged)")
