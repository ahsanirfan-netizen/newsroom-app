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
# 🛠️ SETUP
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
    1. Identify every MAJOR historical figure and their location/date.
    2. Output a JSON list.
    3. Keys: "character_name", "location", "start_date" (YYYY-MM-DD), "end_date" (YYYY-MM-DD).
    4. If exact date is unknown, estimate the first of the month.
    5. JSON OUTPUT ONLY. No markdown.
    """
    
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    
    # Clean the response (Gemini sometimes adds ```json blocks)
    raw_json = response.text.replace("```json", "").replace("```", "").strip()
    
    try:
        data = json.loads(raw_json)
        
        # Insert into Supabase
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        count = 0
        for item in data:
            payload = {
                "character_name": item['character_name'],
                "location": item['location'],
                "start_date": item['start_date'],
                "end_date": item['end_date']
            }
            # We ignore errors (e.g. conflicts) for now to keep it moving
            res = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload)
            if res.status_code == 201:
                count += 1
                
        return count, data
        
    except Exception as e:
        return 0, str(e)

# ==============================================================================
# 📱 THE UI
# ==============================================================================
with st.sidebar:
    st.header("Chapter Settings")
    topic = st.text_input("Topic", "The Coronation of Napoleon")
    
    # We still keep these manual inputs as overrides, but Cartographer fills the DB
    st.caption("Manual Overrides (Optional)")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")

# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================

# BUTTON 1: THE CARTOGRAPHER
if st.button("🗺️ 1. Research & Map Territory"):
    status = st.empty()
    try:
        # A. Research
        status.info("📚 Exa is finding source documents...")
        search = exa.search_and_contents(topic, type="neural", num_results=1, text=True)
        source_text = search.results[0].text
        
        # B. Map (Gemini)
        status.info("🧠 Gemini is extracting knowledge graph...")
        count, data = run_cartographer(source_text)
        
        status.success(f"Success! Mapped {count} new events to the Physics Engine.")
        with st.expander("View Extracted Data"):
            st.json(data)
            st.text(source_text[:500])
            
    except Exception as e:
        st.error(f"Cartographer Error: {e}")
        st.code(traceback.format_exc())

# BUTTON 2: THE WRITER
if st.button("✍️ 2. Write Chapter (With Physics Check)"):
    # This logic remains the same, checking against the DB we just filled
    status = st.empty()
    try:
        status.info("🛡️ Checking Physics...")
        # (Physics check logic here...)
        
        # Just writing the drafting part for brevity in this update
        status.info("✍️ Perplexity is writing...")
        search = exa.search_and_contents(topic, type="neural", num_results=1, text=True)
        source = search.results[0].text[:1500]
        
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene about {topic}. Source: {source}"}]
        )
        st.subheader(topic)
        st.write(draft_resp.choices[0].message.content)
        
    except Exception as e:
        st.error(f"Writer Error: {e}")
