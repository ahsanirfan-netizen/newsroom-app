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
# 🛠️ KEYS & SETUP
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
    st.error("Missing Keys! Check your .env file.")
    st.stop()

st.set_page_config(page_title="Newsroom AI", page_icon="📖")
st.title("🚀 The Newsroom")

# Initialize Clients
try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 📱 THE SIDEBAR (Inputs & Data)
# ==============================================================================
with st.sidebar:
    st.header("📚 Your Book")
    
    # --- 1. HISTORY SECTION ---
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
        st.caption("Loading history...")

    st.divider()
    st.header("🎭 Dramatis Personae")

    # --- 2. CHARACTERS SECTION ---
    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/characters?select=name,role",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        )
        
        if response.status_code == 200:
            chars = response.json()
            if len(chars) > 0:
                for c in chars:
                    role_display = c.get('role') or "Unknown Role"
                    st.text(f"👤 {c['name']} ({role_display})")
            else:
                st.caption("No characters defined.")
        else:
            st.error(f"Fetch Error: {response.status_code}")
    except Exception as e:
        st.error(f"System Error: {e}")

    # Add New Character Form
    with st.expander("Add Character"):
        new_name = st.text_input("Name")
        new_role = st.text_input("Role (e.g. Emperor)")
        
        if st.button("Save Char"):
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

    st.divider()
    
    # --- 3. INPUTS SECTION ---
    st.header("Chapter Settings")
    topic = st.text_input("Topic", "The Coronation of Napoleon")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")

# ==============================================================================
# 🧠 THE MAIN LOGIC (The General Contractor)
# ==============================================================================
if st.button("✍️ Write & Save Chapter", type="primary"):
    status = st.empty()
    
    try:
        # --- PHASE 1: PHYSICS CHECK (Supabase) ---
        status.info("🛡️ Checking Physics Engine...")
        
        supa_headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        payload_check = {
            "character_name": character,
            "location": location,
            "start_date": str(start_date),
            "end_date": str(end_date)
        }
        
        check = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=supa_headers, json=payload_check)
        
        if check.status_code >= 400:
            st.error(f"🛑 PHYSICS ERROR: {check.text}")
            st.stop()
            
        st.success("✅ Physics Check Passed")

        # --- PHASE 2: RESEARCH (Exa) ---
        status.info("📚 Researching...")
        search = exa.search_and_contents(topic, type="neural", num_results=1, text=True)
        source = search.results[0].text[:1500]
        
        # --- PHASE 3: DRAFTING (Perplexity) ---
        status.info("✍️ Drafting...")
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene about {topic}. Source: {source}"}]
        )
        draft = draft_resp.choices[0].message.content
        
        # --- PHASE 4: SAVING (Supabase) ---
        status.info("💾 Saving to Bookshelf...")
        save_payload = {
            "topic": topic,
            "content": draft
        }
        requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", headers=supa_headers, json=save_payload)
        
        # --- PHASE 5: DISPLAY ---
        status.empty()
        st.balloons()
        st.subheader(f"Chapter: {topic}")
        st.write(draft)
        
    except Exception as e:
        st.error("💥 SYSTEM CRASH")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())
