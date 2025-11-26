import streamlit as st
import requests
import traceback
import os
import json
import io
import tempfile # <--- NEW IMPORT
import google.generativeai as genai
from exa_py import Exa
from openai import OpenAI
from linkup import LinkupClient
from dotenv import load_dotenv
from fpdf import FPDF
from gtts import gTTS
from pydub import AudioSegment
from pydub.effects import normalize
from pydub.utils import which

# ==============================================================================
# 🛠️ SETUP & KEYS
# ==============================================================================
load_dotenv()

# FIX FOR FFPROBE ERROR: Explicitly find and set paths
AudioSegment.converter = which("ffmpeg")
AudioSegment.ffprobe = which("ffprobe")

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
    # Perplexity client is initialized but unused for drafting now
    perplexity = OpenAI(api_key=PERPLEXITY_KEY, base_url="https://api.perplexity.ai")
    linkup = LinkupClient(api_key=LINKUP_KEY)
    genai.configure(api_key=GEMINI_KEY)
except Exception as e:
    st.error(f"Setup Error: {e}")

# ==============================================================================
# 🧠 HELPER FUNCTIONS
# ==============================================================================
def run_architect(book_concept):
    st.info(f"🔎 Architect is reading 10 sources for: {book_concept}...")
    try:
        search = exa.search_and_contents(
            f"Comprehensive history, timeline, and academic analysis of: {book_concept}",
            type="neural", num_results=10, text=True
        )
        grounding_text = f"RESEARCH DOSSIER FOR: {book_concept}\n\n"
        for i, result in enumerate(search.results):
            grounding_text += f"--- SOURCE {i+1}: {result.title} ({result.url}) ---\n{result.text[:25000]}\n\n"
    except Exception as e:
        st.warning(f"Deep search failed ({e}). Relying on internal knowledge.")
        grounding_text = "No external sources found."

    prompt = f"""
    Act as a Senior Book Editor. Create a comprehensive Outline.
    BOOK CONCEPT: "{book_concept}"
    MASTER RESEARCH DOSSIER: {grounding_text}
    INSTRUCTIONS:
    1. Synthesize the 10 sources into a logical flow of 5 to 15 chapters.
    2. JSON OUTPUT ONLY: [ {{"chapter_number": 1, "title": "...", "summary_goal": "..."}} ]
    """
    model = genai.GenerativeModel('gemini-2.5-pro') 
    response = model.generate_content(prompt)
    raw_json = response.text.replace("```json", "").replace("```", "").strip()
    try:
        chapters = json.loads(raw_json)
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=representation"}
        book_res = requests.post(f"{SUPABASE_URL}/rest/v1/books", headers=headers, json={"title": book_concept, "user_prompt": book_concept})
        book_id = book_res.json()[0]['id']
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
    pdf.add_page()
    pdf.set_font("helvetica", "B", 24)
    clean_title = book_title.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 60, clean_title, align="C")
    pdf.ln(20)
    pdf.set_font("helvetica", "I", 12)
    pdf.cell(0, 10, "Generated by Newsroom AI", align="C", new_x="LMARGIN", new_y="NEXT")
    for ch in chapters:
        if ch.get('content'):
            pdf.add_page()
            pdf.set_font("helvetica", "B", 16)
            clean_ch_title = f"Chapter {ch['chapter_number']}: {ch['title']}".encode('latin-1', 'replace').decode('latin-1')
            pdf.cell(0, 10, clean_ch_title, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
            pdf.set_font("times", "", 12)
            safe_text = ch['content'].encode('latin-1', 'replace').decode('latin-1')
            pdf.multi_cell(0, 10, safe_text)
    return bytes(pdf.output()) 

# ==============================================================================
# 🎧 AUDIO ENGINEERING ENGINE (ROBUST TEMP FILES)
# ==============================================================================
def chunk_text(text, max_chars=2000):
    chunks = []
    current_chunk = ""
    sentences = text.split('. ')
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_chars:
            current_chunk += sentence + ". "
        else:
            chunks.append(current_chunk)
            current_chunk = sentence + ". "
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

def produce_audiobook(text, voice_name):
    chunks = chunk_text(text)
    combined_audio = AudioSegment.empty()
    
    # Use a temporary directory for safe file creation
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            for i, chunk in enumerate(chunks):
                tld_map = {
                    "US English": "us", "British English": "co.uk", 
                    "Australian English": "com.au", "Indian English": "co.in", 
                    "South African": "co.za"
                }
                tld = tld_map.get(voice_name, "us")
                
                tts = gTTS(text=chunk, lang='en', tld=tld, slow=False)
                
                # Save to the safe temp directory
                filename = os.path.join(temp_dir, f"chunk_{i}.mp3")
                tts.save(filename)
                
                segment = AudioSegment.from_mp3(filename)
                if i == 0: combined_audio += segment
                else: combined_audio = combined_audio.append(segment, crossfade=100)
            
            final_audio = normalize(combined_audio)
            buffer = io.BytesIO()
            final_audio.export(buffer, format="mp3")
            buffer.seek(0)
            return buffer
            
        except Exception as e:
            st.error(f"Audio Engine Failure: {e}")
            return None
    # Temp dir cleans itself up automatically here

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

    if selected_book:
        st.divider()
        st.header("Research Context")
        mission_brief = st.text_area("Mission Brief / Focus", "Find detailed historical accounts, primary sources, and key dates.", height=150)

# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================
if selected_book:
    st.subheader(f"📖 {selected_book['title']}")
    chapters = requests.get(f"{SUPABASE_URL}/rest/v1/table_of_contents?book_id=eq.{selected_book['id']}&order=chapter_number.asc", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}).json()
    
    for ch in chapters:
        status_icon = "✅" if ch.get('content') else "⚪"
        
        with st.expander(f"{status_icon} Chapter {ch['chapter_number']}: {ch['title']}"):
            st.write(f"**Goal:** {ch['summary_goal']}")
            
            if ch.get('content'):
                word_count = len(ch['content'].split())
                st.caption(f"📝 Word Count: {word_count}")
                st.markdown("---")
                st.markdown(ch['content'])
                
                st.markdown("---")
                st.subheader("🎧 Audiobook Generator")
                col_audio_1, col_audio_2 = st.columns([3, 2])
                with col_audio_1:
                    voice_options = ["US English", "British English", "Australian English", "Indian English", "South African"]
                    selected_voice = st.selectbox("Narrator Accent", voice_options, key=f"v_{ch['id']}")
                with col_audio_2:
                    st.write("") 
                    if st.button("🎙️ Produce Audio", key=f"tts_{ch['id']}"):
                        with st.spinner("Chunking, Stitching & Mastering..."):
                            if ch['content']:
                                audio_buffer = produce_audiobook(ch['content'][:20000], selected_voice) 
                                if audio_buffer:
                                    st.success("Mastering Complete.")
                                    st.audio(audio_buffer, format="audio/mp3")
                                    st.download_button(label="⬇️ Download MP3", data=audio_buffer, file_name=f"Ch_{ch['chapter_number']}.mp3", mime="audio/mpeg")
                            else:
                                st.error("No content to read!")
            
            col1, col2 = st.columns(2)
            if col1.button("🗺️ Map", key=f"map_{ch['id']}"):
                with st.spinner("Reading 10 sources..."):
                    search_query = f"{mission_brief} {ch['title']}"
                    search = exa.search_and_contents(search_query, type="neural", num_results=10, text=True)
                    master_text = f"RESEARCH FOR {ch['title']}:\n"
                    for res in search.results:
                        master_text += f"\n--- Source: {res.title} ---\n{res.text}\n"
                    count, _ = run_cartographer(master_text)
                    st.success(f"Mapped {count} events from 10 sources.")

            if col2.button("✍️ Write", key=f"write_{ch['id']}"):
                with st.spinner("Researching & Writing (Gemini 2.5 Pro - Massive Mode)..."):
                    context_prompt = ""
                    if ch['chapter_number'] > 1:
                        prev_ch = next((x for x in chapters if x['chapter_number'] == ch['chapter_number'] - 1), None)
                        if prev_ch and prev_ch.get('content'):
                            context_prompt = f"\n\nPREVIOUS CHAPTER CONTEXT:\n{prev_ch['content'][-5000:]}" 
                            st.info(f"🔗 Linked to Chapter {prev_ch['chapter_number']}")

                    search_query = f"{mission_brief} {ch['title']}"
                    search = exa.search_and_contents(search_query, type="neural", num_results=10, text=True) 
                    master_source = ""
                    for res in search.results:
                        master_source += f"\n--- Source: {res.title} ---\n{res.text[:50000]}\n"
                    
                    prompt = f"""
                    You are a professional non-fiction author. Write Chapter {ch['chapter_number']}: {ch['title']}.
                    GOAL: {ch['summary_goal']}
                    SOURCE MATERIAL (Use these facts): {master_source}
                    {context_prompt}
                    INSTRUCTIONS:
                    1. Write a detailed, immersive, non-fiction narrative.
                    2. **LENGTH REQUIREMENT:** Produce AT LEAST 9,000 words. Do not summarize.
                    3. Use ONLY the source material provided. Do not hallucinate dates or events.
                    4. Ensure smooth continuity.
                    """
                    model = genai.GenerativeModel('gemini-2.5-pro')
                    response = model.generate_content(prompt)
                    content = response.text
                    
                    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json", "Prefer": "return=minimal"}
                    requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", headers=headers, json={"topic": ch['title'], "content": content})
                    requests.patch(f"{SUPABASE_URL}/rest/v1/table_of_contents?id=eq.{ch['id']}", headers=headers, json={"content": content, "status": "drafted"})
                    st.rerun()

    st.divider()
    st.header("🖨️ Publisher & Tools")
    tool_col1, tool_col2 = st.columns(2)
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
                if synced_count > 0: st.success(f"Restored {synced_count} chapters!"); st.rerun()
                else: st.info("No lost chapters found.")

    with tool_col2:
        st.subheader("📦 Export")
        if st.button("📄 Compile Markdown"):
            full_text = f"# {selected_book['title']}\n\n"
            for ch in chapters:
                if ch.get('content'):
                    full_text += f"## Chapter {ch['chapter_number']}: {ch['title']}\n\n{ch['content']}\n\n---\n\n"
            st.download_button(label="⬇️ Download (.md)", data=full_text, file_name=f"{selected_book['title'][:20].replace(' ', '_')}.md", mime="text/markdown")

        if st.button("📕 Compile PDF"):
            with st.spinner("Generating PDF..."):
                try:
                    pdf_bytes = create_pdf(selected_book['title'], chapters)
                    st.download_button(label="⬇️ Download (.pdf)", data=bytes(pdf_bytes), file_name=f"{selected_book['title'][:20].replace(' ', '_')}.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"PDF Error: {e}")

else:
    st.info("👈 Create or Select a Project to begin.")