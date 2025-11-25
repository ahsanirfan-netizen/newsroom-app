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
st.title("🏛️ The Newsroom: Architect Mode")

try:
    exa = Exa(EXA_KEY)
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 🧠 AGENT 1: THE ARCHITECT (Outline Generator)
# ==============================================================================
def run_architect(book_concept):
    """
    Uses Gemini to generate a Table of Contents and saves it to Supabase.
    """
    prompt = f"""
    Act as a Senior Book Editor. Create a comprehensive Outline for a non-fiction book.
    
    BOOK CONCEPT: "{book_concept}"
    
    INSTRUCTIONS:
    1. Create a logical flow of 5 to 10 chapters.
    2. For each chapter, provide a 'title' and a 'summary_goal' (what the writer must cover).
    3. OUTPUT JSON ONLY. List of objects.
    
    JSON FORMAT:
    [
      {{"chapter_number": 1, "title": "...", "summary_goal": "..."}},
      ...
    ]
    """
    
    model = genai.GenerativeModel('gemini-2.5-pro') 
    response = model.generate_content(prompt)
    raw_json = response.text.replace("```json", "").replace("```", "").strip()
    
    try:
        chapters = json.loads(raw_json)
        
        # 1. Create the Book Entry
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation" # Ask DB to return the ID
        }
        
        book_payload = {"title": book_concept, "user_prompt": book_concept, "status": "planning"}
        book_res = requests.post(f"{SUPABASE_URL}/rest/v1/books", headers=headers, json=book_payload)
        
        if book_res.status_code != 201:
            return False, f"Failed to create book: {book_res.text}"
            
        book_id = book_res.json()[0]['id']
        
        # 2. Create the Chapters
        for ch in chapters:
            ch_payload = {
                "book_id": book_id,
                "chapter_number": ch['chapter_number'],
                "title": ch['title'],
                "summary_goal": ch['summary_goal'],
                "status": "pending"
            }
            requests.post(f"{SUPABASE_URL}/rest/v1/table_of_contents", headers=headers, json=ch_payload)
            
        return True, chapters
        
    except Exception as e:
        return False, str(e)

# ==============================================================================
# 🧠 AGENT 2: THE CARTOGRAPHER (Timeline Extractor)
# ==============================================================================
def run_cartographer(source_text):
    prompt = f"""
    You are a Data Engineer. Extract a structured timeline from this text.
    TEXT: {source_text[:5000]}
    INSTRUCTIONS: Output JSON list. Keys: "character_name", "location", "start_date" (YYYY-MM-DD), "end_date".
    JSON OUTPUT ONLY.
    """
    model = genai.GenerativeModel('gemini-2.5-pro') 
    response = model.generate_content(prompt)
    raw_json = response.text.replace("```json", "").replace("```", "").strip()
    
    try:
        data = json.loads(raw_json)
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
        count = 0
        conflicts = []
        for item in data:
            safe_loc = item.get('location') or "Unknown Location"
            payload = {"character_name": item['character_name'], "location": safe_loc, "start_date": item['start_date'], "end_date": item['end_date']}
            res = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=headers, json=payload)
            if res.status_code == 201: count += 1
            elif res.status_code >= 400: conflicts.append(f"{item['character_name']} @ {item['location']}")
        return count, data, conflicts
    except Exception as e:
        raise e

# ==============================================================================
# 📱 THE UI
# ==============================================================================
with st.sidebar:
    st.header("🏛️ The Architect")
    book_concept = st.text_area("Book Concept", "A history of the Internet from ARPANET to AI")
    
    if st.button("🏗️ Draft Blueprint"):
        with st.spinner("Architecting..."):
            success, result = run_architect(book_concept)
            if success:
                st.success("Blueprint Created!")
                st.rerun()
            else:
                st.error(f"Architect Failed: {result}")

    st.divider()
    
    # SHOW ACTIVE BOOKS
    st.header("📂 Active Projects")
    try:
        books = requests.get(f"{SUPABASE_URL}/rest/v1/books?select=id,title", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
        if len(books) > 0:
            selected_book = st.selectbox("Select Book", books, format_func=lambda x: x['title'])
            # Fetch chapters for selected book
            if selected_book:
                chapters = requests.get(f"{SUPABASE_URL}/rest/v1/table_of_contents?book_id=eq.{selected_book['id']}&order=chapter_number.asc", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
        else:
            st.caption("No books planned yet.")
            selected_book = None
            chapters = []
    except:
        st.caption("Loading projects...")
        selected_book = None
        chapters = []

# ==============================================================================
# 🚀 MAIN LOGIC (Project View)
# ==============================================================================

if selected_book:
    st.header(f"Project: {selected_book['title']}")
    
    # Display the Outline
    for ch in chapters:
        with st.expander(f"Chapter {ch['chapter_number']}: {ch['title']}"):
            st.write(f"**Goal:** {ch['summary_goal']}")
            st.caption(f"Status: {ch['status']}")
            
            # ACTION BUTTONS FOR THIS CHAPTER
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("🗺️ Map", key=f"map_{ch['id']}"):
                    # Trigger Cartographer for this chapter
                    st.info(f"Mapping {ch['title']}...")
                    search = exa.search_and_contents(f"History of {ch['title']}", type="neural", num_results=1, text=True)
                    count, data, conflicts = run_cartographer(search.results[0].text)
                    st.success(f"Mapped {count} events.")
            
            with col2:
                if st.button("✍️ Write", key=f"write_{ch['id']}"):
                    # Trigger Writer for this chapter
                    st.info("Writing...")
                    search = exa.search_and_contents(f"{selected_book['title']} {ch['title']}", type="neural", num_results=1, text=True)
                    draft_resp = perplexity.chat.completions.create(
                        model="sonar-pro",
                        messages=[{"role": "user", "content": f"Write Chapter {ch['chapter_number']}: {ch['title']}. Context: {ch['summary_goal']}. Source: {search.results[0].text[:1500]}"}]
                    )
                    
                    # Save Draft
                    requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", 
                        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}, 
                        json={"topic": ch['title'], "content": draft_resp.choices[0].message.content})
                    
                    # Update Status
                    requests.patch(f"{SUPABASE_URL}/rest/v1/table_of_contents?id=eq.{ch['id']}", 
                        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}, 
                        json={"status": "drafted"})
                    
                    st.rerun()

else:
    st.info("👈 Use the Sidebar to Plan a New Book.")
    st.markdown("### Recent Drafts")
    # (Your old history view code could go here)
