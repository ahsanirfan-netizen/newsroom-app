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
st.title("🏛️ The Newsroom: Context Mode")

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
            if requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload).status_code == 201: count += 1
        return count, data
    except:
        return 0, []

# ==============================================================================
# 📱 THE UI
# ==============================================================================
with st.sidebar:
    st.header("Draft New Book")
    book_concept = st.text_area("Concept", "History of the Silk Road")
    if st.button("🏗️ Draft Blueprint"):
        with st.spinner("Architecting..."):
            success, err = run_architect(book_concept)
            if success: st.rerun()
            else: st.error(err)

    st.divider()
    st.header("Open Project")
    try:
        books = requests.get(f"{SUPABASE_URL}/rest/v1/books?select=id,title", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
        selected_book = st.selectbox("Select Book", books, format_func=lambda x: x['title']) if len(books) > 0 else None
    except:
        selected_book = None

# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================
if selected_book:
    st.subheader(f"📖 {selected_book['title']}")
    
    # Fetch Chapters
    chapters = requests.get(f"{SUPABASE_URL}/rest/v1/table_of_contents?book_id=eq.{selected_book['id']}&order=chapter_number.asc", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
    
    for ch in chapters:
        # Color code the status
        status_icon = "✅" if ch['status'] == 'drafted' else "⚪"
        
        with st.expander(f"{status_icon} Chapter {ch['chapter_number']}: {ch['title']}"):
            st.write(f"**Goal:** {ch['summary_goal']}")
            
            if ch.get('content'):
                st.markdown("---")
                st.markdown(ch['content'])
            
            col1, col2 = st.columns(2)
            
            # --- BUTTON 1: MAP ---
            if col1.button("🗺️ Map", key=f"map_{ch['id']}"):
                with st.spinner("Mapping..."):
                    search = exa.search_and_contents(f"History of {ch['title']}", type="neural", num_results=1, text=True)
                    count, _ = run_cartographer(search.results[0].text)
                    st.success(f"Mapped {count} events.")

            # --- BUTTON 2: WRITE (WITH CONTEXT CHAIN) ---
            if col2.button("✍️ Write", key=f"write_{ch['id']}"):
                with st.spinner("Writing..."):
                    # A. GET PREVIOUS CHAPTER CONTEXT
                    context_prompt = ""
                    if ch['chapter_number'] > 1:
                        # Look for the previous chapter in the list we already fetched
                        prev_ch = next((x for x in chapters if x['chapter_number'] == ch['chapter_number'] - 1), None)
                        if prev_ch and prev_ch.get('content'):
                            # We feed the last 2000 chars of the previous chapter to keep context
                            context_prompt = f"\n\nPREVIOUS CHAPTER CONTEXT:\n{prev_ch['content'][-2000:]}\n\n(Ensure continuity with the above event)."
                            st.info(f"🔗 Linked to Chapter {prev_ch['chapter_number']}")

                    # B. RESEARCH
                    search = exa.search_and_contents(f"{selected_book['title']} {ch['title']}", type="neural", num_results=1, text=True)
                    source = search.results[0].text[:2000]
                    
                    # C. WRITE
                    prompt = f"""
                    Write Chapter {ch['chapter_number']}: {ch['title']}.
                    
                    GOAL: {ch['summary_goal']}
                    
                    SOURCE MATERIAL:
                    {source}
                    {context_prompt}
                    """
                    
                    draft_resp = perplexity.chat.completions.create(
                        model="sonar-pro",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    content = draft_resp.choices[0].message.content
                    
                    # D. SAVE TO OUTLINE TABLE
                    requests.patch(
                        f"{SUPABASE_URL}/rest/v1/table_of_contents?id=eq.{ch['id']}", 
                        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}, 
                        json={"content": content, "status": "drafted"}
                    )
                    st.rerun()
else:
    st.info("👈 Create a new book in the sidebar to begin.")
