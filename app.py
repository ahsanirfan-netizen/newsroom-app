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
    Returns: count (int), data (json), conflicts (summary list), logs (detailed strings)
    """
    prompt = f"""
    You are a Data Engineer. Extract a structured timeline from this text.
    
    TEXT:
    {source_text[:5000]}
    
    INSTRUCTIONS:
    1. Identify every MAJOR figure/entity and their location/date.
    2. Output a JSON list.
    3. Keys: "character_name", "location", "start_date", "end_date".
    4. CRITICAL: For BC dates, use the format "YYYY-MM-DD BC" (e.g. "0044-03-15 BC"). Do NOT use negative numbers.
    5. If exact date is unknown, estimate the first of the month.
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
            char_name = item['character_name']
            
            # ---------------------------------------------------------
            # STEP 1: UPSERT CHARACTER (Fixes Foreign Key Error)
            # ---------------------------------------------------------
            # We try to insert the character first. If they exist, we ignore the error.
            char_payload = {
                "name": char_name, 
                "role": "Auto-Imported" 
            }
            # 'resolution=ignore-duplicates' prevents 409 errors if they already exist
            char_headers = headers.copy()
            char_headers["Prefer"] = "resolution=ignore-duplicates"
            
            requests.post(f"{SUPABASE_URL}/rest/v1/characters", headers=char_headers, json=char_payload)
            
            # ---------------------------------------------------------
            # STEP 2: INSERT TIMELINE EVENT
            # ---------------------------------------------------------
            safe_loc = item.get('location') or "Unknown Location"
            
            payload = {
                "character_name": char_name,
                "location": safe_loc,
                "start_date": item['start_date'],
                "end_date": item['end_date']
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
    st.caption("Manual Overrides (Optional)")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")
    
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
            st.caption("Copy these errors to debug Supabase issues:")
            st.code("\n\n".join(logs), language="yaml")
            
    except Exception as e:
        st.error("Cartographer Failed")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())

# BUTTON 2: THE WRITER
if st.button("✍️ 2. Write Chapter (With Physics Check)"):
    status = st.empty()
    try:
        status.info("🛡️ Checking Physics...")
        
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
        
        status.info("📚 Researching...")
        search = exa.search_and_contents(
            mission_brief, 
            type="neural", 
            num_results=1, 
            text=True
        )
        source = search.results[0].text[:2000]
        
        status.info("✍️ Perplexity is writing...")
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene based on this brief: {mission_brief}. Source Material: {source}"}]
        )
        draft = draft_resp.choices[0].message.content
        
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
