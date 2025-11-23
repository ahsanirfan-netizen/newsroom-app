import streamlit as st
import requests
import traceback
import google.generativeai as genai
from exa_py import Exa
from openai import OpenAI
from linkup import LinkupClient

# ==============================================================================
# ==============================================================================
# 🛠️ KEYS (Now loading securely from the Server)
# ==============================================================================
try:
    EXA_KEY = st.secrets["EXA_KEY"]
    PERPLEXITY_KEY = st.secrets["PERPLEXITY_KEY"]
    LINKUP_KEY = st.secrets["LINKUP_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
except FileNotFoundError:
    st.error("Secrets not found! Did you set up .streamlit/secrets.toml?")
    st.stop()


# ==============================================================================
# ⚙️ SETUP
# ==============================================================================
st.set_page_config(page_title="Newsroom AI", page_icon="📖")

try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 📱 THE UI
# ==============================================================================
st.title("📖 The Newsroom")
st.caption("Exa • Perplexity • Linkup • Gemini • Supabase")

with st.sidebar:
    st.header("Chapter Settings")
    topic = st.text_input("Topic", "The Coronation of Napoleon")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")

if st.button("✍️ Write Chapter", type="primary"):
    status = st.empty()
    
    try:
        # 1. PHYSICS CHECK (Supabase REST)
        status.info("🛡️ Checking Physics Engine...")
        
        supa_headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        payload = {
            "character_name": character,
            "location": location,
            "start_date": str(start_date),
            "end_date": str(end_date)
        }
        # Attempt insert
        check = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=supa_headers, json=payload)
        
        if check.status_code >= 400:
            st.error(f"🛑 PHYSICS ERROR: {check.text}")
            st.stop() # Stop execution
            
        st.success("✅ Physics Check Passed")

        # 2. RESEARCH (Exa)
        status.info("📚 Researching...")
        search = exa.search_and_contents(topic, type="neural", num_results=1, text=True)
        source = search.results[0].text[:1500]
        
        # 3. DRAFT (Perplexity)
        status.info("✍️ Drafting...")
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene about {topic}. Source: {source}"}]
        )
        draft = draft_resp.choices[0].message.content
        
        # 4. SHOW RESULT
        status.empty()
        st.subheader("Draft Output")
        st.write(draft)
        
    except Exception as e:
        st.error("💥 SYSTEM CRASH")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())
