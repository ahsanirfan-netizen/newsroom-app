import streamlit as st
import requests
import traceback
import os
import json
import psycopg2
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
    # DATABASE_URL is required for the "Repair" button to work
    DATABASE_URL = os.getenv("DATABASE_URL") 
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
# 🧠 HELPER: EXTRACT SPECS FROM BRIEF
# ==============================================================================
def analyze_brief_for_specs(brief):
    """
    Uses Gemini to determine WHO, WHERE, and WHEN the user wants to write about.
    """
    prompt = f"""
    Analyze this writing prompt and extract the scene constraints.
    
    PROMPT: "{brief}"
    
    OUTPUT JSON ONLY:
    {{
        "character_name": "Name" (Return a SINGLE string, e.g. "Julius Caesar"),
        "location": "Location", 
        "start_date": "YYYY-MM-DD" (or "YYYY-MM-DD BC"),
        "end_date": "YYYY-MM-DD" (or "YYYY-MM-DD BC")
    }}
    """
    model = genai.GenerativeModel('gemini-2.5-pro')
    response = model.generate_content(prompt)
    try:
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except:
        return None

# ==============================================================================
# 🧠 THE CARTOGRAPHER FUNCTION (GEMINI)
# ==============================================================================
def run_cartographer(source_text):
    prompt = f"""
    You are a Data Engineer. Extract a structured timeline from this text.
    
    TEXT:
    {source_text[:5000]}
    
    INSTRUCTIONS:
    1. Identify every MAJOR figure/entity and their location/date.
    2. Output a JSON list.
    3. Keys: 
       - "character_name" (String only)
       - "location"
       - "start_date" (Format: "YYYY-MM-DD" or "YYYY-MM-DD BC")
       - "end_date"
    4. CRITICAL: For BC dates, use "YYYY-MM-DD BC".
    5. If only year is known: Set dates to Jan 1st - Dec 31st.
    6. JSON OUTPUT ONLY. No markdown.
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
        error_logs = [] 
        
        for item in data:
            # FIX 1: FLATTEN LISTS (Handles ["Caesar", "Pirates"])
            raw_names = item['character_name']
            
            if isinstance(raw_names, str):
                names_to_process = [raw_names]
            elif isinstance(raw_names, list):
                names_to_process = raw_names
            else:
                names_to_process = [str(raw_names)]

            for char_name in names_to_process:
                # STEP 1: UPSERT CHARACTER
                char_payload = {"name": char_name, "role": "Auto-Imported"}
                char_headers = headers.copy()
                char_headers["Prefer"] = "resolution=ignore-duplicates"
                requests.post(f"{SUPABASE_URL}/rest/v1/characters", headers=char_headers, json=char_payload)
                
                # FIX 2: AUTO-CALCULATE GRANULARITY
                s_date = item['start_date']
                e_date = item['end_date']
                
                if s_date != e_date:
                    computed_granularity = "year"
                else:
                    computed_granularity = "day"

                safe_loc = item.get('location') or "Unknown Location"
                
                payload = {
                    "character_name": char_name,
                    "location": safe_loc,
                    "start_date": s_date,
                    "end_date": e_date,
                    "granularity": computed_granularity
                }
                
                res = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload)
                
                if res.status_code == 201:
                    count += 1
                elif res.status_code >= 400:
                    log_entry = (
                        f"❌ FAILED: {char_name} @ {safe_loc}\n"
                        f"   Status: {res.status_code}\n"
                        f"   Response: {res.text}\n"
                        f"   Payload: {json.dumps(payload)}"
                    )
                    error_logs.append(log_entry)
                    conflicts.append(f"{char_name} ({res.status_code})")
                
        return count, data, conflicts, error_logs
        
    except Exception as e:
        st.error(f"JSON Parsing Error: {e}")
        st.text(raw_json) 
        raise e

# ==============================================================================
# 📱 THE UI
# ==============================================================================
with st.sidebar:
    st.header("Chapter Settings")
    
    chapter_title = st.text_input("Chapter Title (DB Label)", "The Assassination of Julius Caesar")
    
    mission_brief = st.text_area(
        "Mission Brief", 
        "Find primary source descriptions of the assassination of Julius Caesar, specifically focusing on the weapons used and the exact location in the Senate.",
        height=150
    )
    
    st.divider()
    st.caption("Manual Overrides")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")
    
    # --- NEW: DATABASE REPAIR TOOL ---
    st.divider()
    st.header("🛠️ Admin Tools")
    if st.button("🛠️ Repair Database Schema"):
        if not DATABASE_URL:
            st.error("DATABASE_URL not found in env vars.")
        else:
            try:
                with st.spinner("Updating Physics Engine Logic..."):
                    conn = psycopg2.connect(DATABASE_URL)
                    cur = conn.cursor()
                    
                    # 1. Add Granularity Column
                    cur.execute("ALTER TABLE timeline ADD COLUMN IF NOT EXISTS granularity TEXT DEFAULT 'day';")
                    
                    # 2. Update the Trigger Function (The Fix for 'Year' overlaps)
                    sql_func = """
                    CREATE OR REPLACE FUNCTION check_physics_violation()
                    RETURNS TRIGGER AS $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM timeline
                            WHERE character_name = NEW.character_name
                              AND location <> NEW.location
                              AND (start_date, end_date) OVERLAPS (NEW.start_date, NEW.end_date)
                              AND id <> NEW.id
                              AND granularity = 'day'
                              AND NEW.granularity = 'day'
                        ) THEN
                            RAISE EXCEPTION 'IMPOSSIBILITY ERROR: % cannot be in % and another location at the same time.', NEW.character_name, NEW.location USING ERRCODE = 'P0001';
                        END IF;
                        RETURN NEW;
                    END;
                    $$ LANGUAGE plpgsql;
                    """
                    cur.execute(sql_func)
                    
                    # 3. Re-apply Trigger
                    cur.execute("DROP TRIGGER IF EXISTS trigger_physics_check ON timeline;")
                    cur.execute("""
                        CREATE TRIGGER trigger_physics_check
                        BEFORE INSERT OR UPDATE ON timeline
                        FOR EACH ROW EXECUTE FUNCTION check_physics_violation();
                    """)
                    
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success("✅ Database Logic Updated! Granularity check is now active.")
            except Exception as e:
                st.error(f"Repair Failed: {e}")


# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================

# BUTTON 1: THE CARTOGRAPHER
if st.button("🗺️ 1. Research & Map Territory"):
    status = st.empty()
    try:
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
        
        status.info("🧠 Gemini is extracting knowledge graph...")
        
        count, data, conflicts, logs = run_cartographer(source_text)
        
        status.success(f"Success! Mapped {count} new events to the Physics Engine.")
        
        if len(conflicts) > 0:
            st.warning(f"Skipped {len(conflicts)} conflicting events.")
            
        with st.expander("View Extracted Data"):
            st.json(data)
            st.caption("Source Text Preview:")
            st.text(source_text[:500])
        
        if logs:
            st.divider()
            st.subheader("🛑 Error Console")
            st.code("\n\n".join(logs), language="yaml")
            
    except Exception as e:
        st.error("Cartographer Failed")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())

# BUTTON 2: THE WRITER
if st.button("✍️ 2. Write Chapter (With Physics Check)"):
    status = st.empty()
    try:
        # 1. AUTO-DETECT SPECS
        status.info("🕵️ Analyzing Brief for Constraints...")
        specs = analyze_brief_for_specs(mission_brief)
        
        if specs:
            check_char = specs.get("character_name", character)
            
            # FIX: HANDLE LISTS IN WRITER (e.g. ["Caesar", "Pirates"])
            if isinstance(check_char, list):
                check_char = check_char[0]
                
            check_loc = specs.get("location", location)
            check_start = specs.get("start_date", str(start_date))
            check_end = specs.get("end_date", str(end_date))
        else:
            check_char = character
            check_loc = location
            check_start = str(start_date)
            check_end = str(end_date)

        # Auto-Calculate Granularity
        if check_start != check_end:
            check_granularity = "year"
        else:
            check_granularity = "day"

        st.caption(f"Checking: {check_char} in {check_loc} ({check_granularity})")

        # 2. PHYSICS CHECK
        status.info("🛡️ Checking Physics...")
        
        supa_headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        payload_check = {
            "character_name": check_char,
            "location": check_loc,
            "start_date": check_start,
            "end_date": check_end,
            "granularity": check_granularity
        }
        
        # Register Character
        char_reg = {"name": check_char, "role": "Protagonist"}
        reg_headers = supa_headers.copy()
        reg_headers["Prefer"] = "resolution=ignore-duplicates"
        requests.post(f"{SUPABASE_URL}/rest/v1/characters", headers=reg_headers, json=char_reg)
        
        # Check Timeline
        check = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=supa_headers, json=payload_check)
        
        if check.status_code >= 400:
            st.error(f"🛑 PHYSICS VIOLATION: Chapter Blocked.")
            st.divider()
            st.subheader("🛑 Error Console")
            st.code(
                f"❌ CHECK FAILED\n"
                f"Status: {check.status_code}\n"
                f"Response: {check.text}\n"
                f"Payload: {json.dumps(payload_check)}", 
                language="yaml"
            )
            st.stop()
            
        status.success("✅ Physics Check Passed")
        
        # 3. RESEARCH
        status.info("📚 Researching...")
        search = exa.search_and_contents(
            mission_brief, 
            type="neural", 
            num_results=1, 
            text=True
        )
        source = search.results[0].text[:2000]
        
        # 4. WRITE
        status.info("✍️ Perplexity is writing...")
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene based on this brief: {mission_brief}. Source Material: {source}"}]
        )
        draft = draft_resp.choices[0].message.content
        
        # 5. SAVE
        status.info("💾 Saving to Bookshelf...")
        save_payload = {"topic": chapter_title, "content": draft}
        requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", headers=supa_headers, json=save_payload)
        
        status.empty()
        st.balloons()
        st.subheader(f"Chapter: {chapter_title}")
        st.write(draft)
        
    except Exception as e:
        st.error("Writer Failed")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())
