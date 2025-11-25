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
st.title("🗺️ The Newsroom")

try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 🧠 THE CARTOGRAPHER FUNCTION
# ==============================================================================
def run_cartographer(source_text):
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
            safe_loc = item.get('location') or "Unknown Location"

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
    
    st.info("💡 Pro Tip: Be specific. E.g., 'Find primary sources describing the exact moment Brutus stabbed Caesar.'")
    
    mission_brief = st.text_area(
        "Mission Brief / Research Prompt", 
        "Find detailed historical accounts of the assassination of Julius Caesar on the Ides of March, 44 BC.",
        height=150
    )
    
    topic_label = st.text_input("Short Label (for files)", "Julius Caesar")
    
    st.divider()
    st.caption("Manual Overrides")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")
    
    st.divider()
    st.header("🎭 Dramatis Personae")
    
    # 1. Add Character
    with st.expander("Add Character"):
        new_name = st.text_input("Name")
        new_role = st.text_input("Role")
        if st.button("Save Char"):
            requests.post(
                f"{SUPABASE_URL}/rest/v1/characters",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"},
                json={"name": new_name, "role": new_role}
            )
            st.rerun()

    # 2. List Characters
    try:
        chars = requests.get(
            f"{SUPABASE_URL}/rest/v1/characters?select=name,role",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        ).json()
        if len(chars) > 0:
            for c in chars:
                role = c.get('role') or "Unknown"
                st.text(f"👤 {c['name']} ({role})")
    except:
        pass

# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================

if st.button("🗺️ 1. Research & Map Territory"):
    status = st.empty()
    try:
        status.info(f"📚 Exa is finding sources for: '{mission_brief[:50]}...'")
        
        search = exa.search_and_contents(mission_brief, type="neural", num_results=1, text=True)
        if not search.results:
            st.error("Exa found no results.")
            st.stop()
            
        source_text = search.results[0].text
        
        status.info("🧠 Gemini is extracting knowledge graph...")
        count, data, conflicts = run_cartographer(source_text)
        
        status.success(f"Success! Mapped {count} new events to the Physics Engine.")
        if len(conflicts) > 0:
            st.warning(f"Skipped {len(conflicts)} conflicts.")
            
        with st.expander("View Data"):
            st.json(data)
            
    except Exception as e:
        st.error("Cartographer Failed")
        with st.expander("Logs"):
            st.code(traceback.format_exc())

if st.button("✍️ 2. Write Chapter"):
    status = st.empty()
    try:
        status.info("🛡️ Checking Physics...")
        
        # Physics Check
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        payload = {"character_name": character, "location": location, "start_date": str(start_date), "end_date": str(end_date)}
        
        check = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload)
        if check.status_code >= 400:
            st.error(f"🛑 PHYSICS ERROR: {check.text}")
            st.stop()
            
        status.success("✅ Physics Check Passed")
        
        status.info("📚 Researching...")
        search = exa.search_and_contents(mission_brief, type="neural", num_results=1, text=True)
        source = search.results[0].text[:1500]
        
        status.info("✍️ Writing...")
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene about {topic_label}. Source: {source}"}]
        )
        draft = draft_resp.choices[0].message.content
        
        status.info("💾 Saving...")
        requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", headers=headers, json={"topic": topic_label, "content": draft})
        
        status.empty()
        st.balloons()
        st.subheader(topic_label)
        st.write(draft)
        
    except Exception as e:
        st.error("Writer Failed")
        st.code(traceback.format_exc())
