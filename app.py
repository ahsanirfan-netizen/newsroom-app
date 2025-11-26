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
from fpdf import FPDF

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

st.set_page_config(page_title="Newsroom AI", page_icon="🏛️", layout="wide")
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
    # 1. DEEP GROUNDING: Fetch 10 distinct sources
    st.info(f"🔎 Architect is reading 10 sources for: {book_concept}...")
    
    try:
        search = exa.search_and_contents(
            f"Comprehensive history, timeline, and academic analysis of: {book_concept}",
            type="neural",
            num_results=10, 
            text=True
        )
        
        grounding_text = f"RESEARCH DOSSIER FOR: {book_concept}\n\n"
        for i, result in enumerate(search.results):
            grounding_text += f"--- SOURCE {i+1}: {result.title} ({result.url}) ---\n"
            grounding_text += f"{result.text[:25000]}\n\n" 
            
    except Exception as e:
        st.warning(f"Deep search failed ({e}). Relying on internal knowledge.")
        grounding_text = "No external sources found."

    # 3. PLANNING: Use the Master Dossier
    prompt = f"""
    Act as a Senior Book Editor. Create a comprehensive Outline.
    
    BOOK CONCEPT: "{book_concept}"
    
    MASTER RESEARCH DOSSIER (Use this for absolute accuracy):
    {grounding_text}
    
    INSTRUCTIONS:
    1. Synthesize the 10 sources into a logical flow of 5 to 15 chapters.
    2. Ensure no major historical events from the sources are missed.
    3. JSON OUTPUT ONLY: [ {{"chapter_number": 1, "title": "...", "summary_goal": "..."}} ]
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
    Extract structured timeline. TEXT: {source_text[:150000]}
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

def create_pdf(book_title, chapters):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Title Page
    pdf.add_page()
    pdf.set_font("helvetica", "B", 24)
    clean_title = book_title.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 60, clean_title, align="C")
    pdf.ln(20)
    
    pdf.set_font("helvetica", "I", 12)
    pdf.cell(0, 10, "Generated by Newsroom AI", align="C", new_x="LMARGIN", new_y="NEXT")
    
    # Chapters
    for ch in chapters:
        if ch.get('content'):
            pdf.add_page()
            # Chapter Title
            pdf.set_font("helvetica", "B", 16)
            clean_ch_title = f"Chapter {ch['chapter_number']}: {ch['title']}".encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 10, clean_ch_title, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
            
            # Chapter Body
            pdf.set_font("times", "", 12)
            safe_text = ch['content'].encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 10, safe_text)
            
    return bytes(pdf.output()) 

# ==============================================================================
# 📱 THE SIDEBAR
# ==============================================================================
with st.sidebar:
    st.header("Draft New Book")
    book_concept = st.text_area("Concept", "History of the Silk Road")
    if st.button("🏗️ Draft Blueprint (Deep Research)"):
        with st.spinner("Reading 10 sources & Architecting..."):
            success, err = run_architect(book_concept)
            if success: st.rerun()
            else: st.error(err)

    st.divider()
    st.header("Open Project")
    try:
        books = requests.get(
            f"{SUPABASE_URL}/rest/v1/books?select=id,title&order=created_at.desc", 
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        ).json()
        
        selected_book = st.selectbox("Select Book", books, format_func=lambda x: x['title']) if len(books) > 0 else None
    except:
        selected_book = None

    # Mission Brief for Context
    if selected_book:
        st.divider()
        st.header("Research Context")
        st.info("💡 Tip: Add specific details here to guide the AI research.")
        mission_brief = st.text_area(
            "Mission Brief / Focus", 
            "Find detailed historical accounts, primary sources, and key dates.",
            height=150
        )

# ==============================================================================
# 🚀 MAIN LOGIC (Project View)
# ==============================================================================
if selected_book:
    st.subheader(f"📖 {selected_book['title']}")
    
    # Fetch Chapters
    chapters = requests.get(f"{SUPABASE_URL}/rest/v1/table_of_contents?book_id=eq.{selected_book['id']}&order=chapter_number.asc", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
    
    for ch in chapters:
        status_icon = "✅" if ch.get('content') else "⚪"
        
        with st.expander(f"{status_icon} Chapter {ch['chapter_number']}: {ch['title']}"):
            st.write(f"**Goal:** {ch['summary_goal']}")
            
            if ch.get('content'):
                # Word Count
                word_count = len(ch['content'].split())
                st.caption(f"📝 Word Count: {word_count}")
                st.markdown("---")
                st.markdown(ch['content'])
            
            col1, col2 = st.columns(2)
            
            # 1. MAP BUTTON (Deep Research)
            if col1.button("🗺️ Map", key=f"map_{ch['id']}"):
                with st.spinner("Reading 10 sources..."):
                    search_query = f"{mission_brief} {ch['title']}"
                    search = exa.search_and_contents(search_query, type="neural", num_results=10, text=True)
                    
                    master_text = f"RESEARCH FOR {ch['title']}:\n"
                    for res in search.results:
                        master_text += f"\n--- Source: {res.title} ---\n{res.text}\n"
                    
                    count, _ = run_cartographer(master_text)
                    st.success(f"Mapped {count} events from 10 sources.")

            # 2. WRITE BUTTON (FRACTAL WRITING)
            if col2.button("✍️ Write (Fractal)", key=f"write_{ch['id']}"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    # --- STEP A: GATHER INTEL ---
                    status_text.text("📚 Phase 1/3: Deep Researching...")
                    search_query = f"{mission_brief} {ch['title']}"
                    search = exa.search_and_contents(search_query, type="neural", num_results=10, text=True) 
                    
                    master_source = ""
                    for res in search.results:
                        master_source += f"\n--- Source: {res.title} ---\n{res.text[:25000]}\n"
                    
                    # --- STEP B: BREAKDOWN (The Sub-Architect) ---
                    status_text.text("🏗️ Phase 2/3: Breaking down chapter into scenes...")
                    progress_bar.progress(10)
                    
                    plan_prompt = f"""
                    You are a Book Outliner. Break this chapter into 5-10 distinct SUB-TOPICS or SCENES.
                    
                    CHAPTER: {ch['title']}
                    GOAL: {ch['summary_goal']}
                    SOURCE MATERIAL LENGTH: {len(master_source)} characters
                    
                    INSTRUCTIONS:
                    1. Each subtopic must cover a specific event or theme from the source material.
                    2. The flow must be chronological and logical.
                    3. JSON OUTPUT ONLY: ["Scene 1 Title", "Scene 2 Title", ...]
                    """
                    
                    model = genai.GenerativeModel('gemini-2.5-pro')
                    plan_resp = model.generate_content(plan_prompt)
                    clean_plan = plan_resp.text.replace("```json", "").replace("```", "").strip()
                    subtopics = json.loads(clean_plan)
                    
                    st.write(f"**Plan:** {subtopics}") # Show the user the plan
                    
                    # --- STEP C: THE ASSEMBLY LINE (Write Each Scene) ---
                    full_chapter_content = ""
                    context_chain = ""
                    
                    # Get previous chapter context if available
                    if ch['chapter_number'] > 1:
                        prev_ch = next((x for x in chapters if x['chapter_number'] == ch['chapter_number'] - 1), None)
                        if prev_ch and prev_ch.get('content'):
                            context_chain = f"PREVIOUS CHAPTER SUMMARY: {prev_ch['content'][-3000:]}"

                    for i, subtopic in enumerate(subtopics):
                        status_text.text(f"✍️ Phase 3/3: Writing Section {i+1}/{len(subtopics)}: {subtopic}...")
                        
                        # Dynamic Context: We feed the end of the PREVIOUS section into the NEW section
                        # This ensures Scene 2 flows naturally from Scene 1
                        local_context = full_chapter_content[-2000:] if full_chapter_content else context_chain
                        
                        section_prompt = f"""
                        You are writing a non-fiction narrative. Write ONE SECTION of the chapter.
                        
                        CHAPTER: {ch['title']}
                        CURRENT SECTION TOPIC: {subtopic}
                        
                        CONTEXT (What just happened):
                        {local_context}
                        
                        SOURCE MATERIAL (Use facts from here):
                        {master_source}
                        
                        INSTRUCTIONS:
                        1. Write 500-1000 words for this specific section.
                        2. Focus deeply on this subtopic. Do not rush.
                        3. Maintain a consistent narrative tone.
                        4. Do not repeat information from the context.
                        """
                        
                        section_resp = model.generate_content(section_prompt)
                        section_text = section_resp.text
                        
                        full_chapter_content += f"\n\n### {subtopic}\n\n{section_text}"
                        
                        # Update Progress
                        progress = int(((i + 1) / len(subtopics)) * 90) + 10
                        progress_bar.progress(progress)
                    
                    # --- STEP D: SAVE ---
                    status_text.text("💾 Saving full chapter...")
                    
                    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
                    requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", headers=headers, json={"topic": ch['title'], "content": full_chapter_content})
                    requests.patch(f"{SUPABASE_URL}/rest/v1/table_of_contents?id=eq.{ch['id']}", headers=headers, json={"content": full_chapter_content, "status": "drafted"})
                    
                    progress_bar.progress(100)
                    status_text.success("Chapter Complete!")
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Fractal Writer Failed: {e}")
                    st.code(traceback.format_exc())

    # ==============================================================================
    # 🖨️ PUBLISHER & TOOLS
    # ==============================================================================
    st.divider()
    st.header("🖨️ Publisher & Tools")
    
    tool_col1, tool_col2 = st.columns(2)
    
    # --- COLUMN 1: MAINTENANCE ---
    with tool_col1:
        st.subheader("🛠️ Maintenance")
        if st.button("🔄 Resync from Backups"):
            with st.spinner("Searching archives..."):
                backups = requests.get(f"{SUPABASE_URL}/rest/v1/book_chapters?select=topic,content", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
                headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"}
                
                synced_count = 0
                for ch in chapters:
                    match = next((b for b in backups if b['topic'] == ch['title']), None)
                    if match and not ch.get('content'):
                        requests.patch(f"{SUPABASE_URL}/rest/v1/table_of_contents?id=eq.{ch['id']}", headers=headers, json={"content": match['content'], "status": "drafted"})
                        synced_count += 1
                
                if synced_count > 0:
                    st.success(f"Restored {synced_count} chapters!")
                    st.rerun()
                else:
                    st.info("No lost chapters found.")

    # --- COLUMN 2: EXPORT ---
    with tool_col2:
        st.subheader("📦 Export")
        
        if st.button("📄 Compile Markdown"):
            full_text = f"# {selected_book['title']}\n\n"
            for ch in chapters:
                if ch.get('content'):
                    full_text += f"## Chapter {ch['chapter_number']}: {ch['title']}\n\n{ch['content']}\n\n---\n\n"
            
            st.download_button(
                label="⬇️ Download (.md)",
                data=full_text,
                file_name=f"{selected_book['title'][:20].replace(' ', '_')}.md",
                mime="text/markdown"
            )

        if st.button("📕 Compile PDF"):
            with st.spinner("Generating PDF..."):
                try:
                    pdf_bytes = create_pdf(selected_book['title'], chapters)
                    st.download_button(
                        label="⬇️ Download (.pdf)",
                        data=bytes(pdf_bytes),
                        file_name=f"{selected_book['title'][:20].replace(' ', '_')}.pdf",
                        mime="application/pdf"
                    )
                except Exception as e:
                    st.error(f"PDF Error: {e}")

else:
    st.info("👈 Create or Select a Project to begin.")


