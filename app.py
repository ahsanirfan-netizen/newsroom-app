import streamlit as st
import requests
import traceback
import os
import json
import google.generativeai as genai
from exa_py import Exa
from openai import OpenAI
from linkup import LinkupClient
from dotenv import load_dotenv

# ==============================================================================
# 🛠️ SETUP & KEYS
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

st.set_page_config(page_title="Newsroom AI", page_icon="🗺️")
st.title("🗺️ The Newsroom: Cartographer Mode")

try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 🧠 THE CARTOGRAPHER FUNCTION (GEMINI)
# ==============================================================================
def run_cartographer(source_text):
    """
    Uses Gemini to read text and extract Timeline Events into Supabase.
    """
    prompt = f"""
    You are a Data Engineer. Extract a structured timeline from this text.
    
    TEXT:
    {source_text[:5000]}
    
    INSTRUCTIONS:
    1. Identify every MAJOR figure/entity and their location/date.
    2. Output a JSON list.
    3. Keys: "character_name", "location", "start_date" (YYYY-MM-DD), "end_date" (YYYY-MM-DD).
    4. If exact date is unknown, estimate the first of the month.
    5. JSON OUTPUT ONLY. No markdown.
    """
    
    model = genai.GenerativeModel('gemini-2.5-pro') 
    response = model.generate_content(prompt)
    
    raw_json = response.text.replace("```json", "").replace("```", "").strip()
    
    try:
        data = json.loads(raw_json)
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        count = 0
        conflicts = []
        
        for item in data:
            # SAFETY CHECK: Handle NULL locations
            safe_loc = item.get('location')
            if not safe_loc:
                safe_loc = "Unknown Location"

            payload = {
                "character_name": item['character_name'],
                "location": safe_loc,
                "start_date": item['start_date'],
                "end_date": item['end_date']
            }
            
            res = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload)
            if res.status_code == 201:
                count += 1
            elif res.status_code >= 400:
                conflicts.append(f"{item['character_name']} @ {item['location']}")
                
        return count, data, conflicts
        
    except Exception as e:
        raise e

# ==============================================================================
# 📱 THE UI
# ==============================================================================
with st.sidebar:
    st.header("Chapter Settings")
    
    # 1. Database Label
    chapter_title = st.text_input("Chapter Title (DB Label)", "The Assassination of Julius Caesar")
    
    # 2. The Mission Brief
    mission_brief = st.text_area(
        "Mission Brief", 
        "Find primary source descriptions of the assassination of Julius Caesar, specifically focusing on the weapons used and the exact location in the Senate.",
        height=150
    )
    
    st.divider()
    st.caption("Manual Overrides (Optional)")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")
    
    # Bookshelf
    st.divider()
    st.header("📚 Your Book")
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
        pass

# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================

# BUTTON 1: THE CARTOGRAPHER
if st.button("🗺️ 1. Research & Map Territory"):
    status = st.empty()
    try:
        # A. Research (FIXED: Removed use_autoprompt)
        status.info(f"📚 Exa is processing brief...")
        
        search = exa.search_and_contents(
            mission_brief, 
            type="neural", 
            num_results=1, 
            text=True
        )
        
        if not search.results:
            st.error("Exa found no results.")
            st.stop()
            
        source_text = search.results[0].text
        
        # B. Map (Gemini)
        status.info("🧠 Gemini is extracting knowledge graph...")
        count, data, conflicts = run_cartographer(source_text)
        
        status.success(f"Success! Mapped {count} new events to the Physics Engine.")
        
        if len(conflicts) > 0:
            st.warning(f"Skipped {len(conflicts)} conflicting events (Physics Engine Blocked).")
            
        with st.expander("View Extracted Data"):
            st.json(data)
            st.caption("Source Text Preview:")
            st.text(source_text[:500])
            
    except Exception as e:
        st.error("Cartographer Failed")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())

# BUTTON 2: THE WRITER
if st.button("✍️ 2. Write Chapter (With Physics Check)"):
    status = st.empty()
    try:
        status.info("🛡️ Checking Physics...")
        
        # 1. Physics Check
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
            
        status.success("✅ Physics Check Passed")
        
        # 2. Research (FIXED: Removed use_autoprompt)
        status.info("📚 Researching...")
        
        search = exa.search_and_contents(
            mission_brief, 
            type="neural", 
            num_results=1, 
            text=True
        )
        source = search.results[0].text[:2000]
        
        # 3. Draft
        status.info("✍️ Perplexity is writing...")
        
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages
