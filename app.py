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

st.set_page_config(page_title="Newsroom AI", page_icon="🏛️")
st.title("🏛️ The Newsroom")

try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 🧠 HELPER FUNCTIONS
# ==============================================================================
def run_architect(book_concept):
    prompt = f"""
    Act as a Senior Book Editor. Create a comprehensive Outline.
    BOOK CONCEPT: "{book_concept}"
    INSTRUCTIONS:
    1. Create a logical flow of 5 to 10 chapters.
    2. JSON OUTPUT ONLY: [ {{"chapter_number": 1, "title": "...", "summary_goal": "..."}} ]
    """
    model = genai.GenerativeModel('gemini-2.5-pro') 
    response = model.generate_content(prompt)
    raw_json = response.text.replace("```json", "").replace("```", "").strip()
    try:
        chapters = json.loads(raw_json)
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
        
        # Create Book
        book_res = requests.post(f"{SUPABASE_URL}/rest/v1/books", headers=headers, json={"title": book_concept, "user_prompt": book_concept})
        book_id = book_res.json()[0]['id']
        
        # Create Chapters
        for ch in chapters:
            ch_payload = {"book_id": book_id, "chapter_number": ch['chapter_number'], "title": ch['title'], "summary_goal": ch['summary_goal'], "status": "pending"}
            requests.post(f"{SUPABASE_URL}/rest/v1/table_of_contents", headers=headers, json=ch_payload)
        return True, None
    except Exception as e:
        return False, str(e)

def run_cartographer(source_text):
    prompt = f"""
    Extract structured timeline. TEXT: {source_text[:5000]}
    JSON OUTPUT ONLY: [ {{"character_name": "...", "location": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}} ]
    """
    model = genai.GenerativeModel('gemini-2.5-pro') 
    response = model.generate_content(prompt)
    try:
        data = json.loads(response.text.replace("```json", "").replace("```", "").strip())
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        count = 0
        for item in data:
            safe_loc = item.get('location') or "Unknown"
            payload = {"character_name": item['character_name'], "location": safe_loc, "start_date": item['start_date'], "end_date": item['end_date']}
            if requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload).status_code == 201
