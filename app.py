import os
import time
import json
import threading
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from exa_py import Exa
from pydub import AudioSegment
import io

# ------------------------------------------------------------------
# CONFIG & KEYS
# ------------------------------------------------------------------
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

gemini_key = os.getenv("GEMINI_API_KEY")
exa_key = os.getenv("EXA_API_KEY")

if not gemini_key:
    st.error("CRITICAL: GEMINI_API_KEY missing from .env")
    st.stop()
if not exa_key:
    st.error("CRITICAL: EXA_API_KEY missing from .env")
    st.stop()

client = genai.Client(api_key=gemini_key)
exa = Exa(api_key=exa_key)

st.set_page_config(page_title="The Newsroom", page_icon="🏛️", layout="wide")

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ------------------------------------------------------------------
# SELF-HEALING SCHEMA
# ------------------------------------------------------------------
def run_schema_check():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Base Tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS book_chapters (
                id SERIAL PRIMARY KEY,
                book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
                topic TEXT NOT NULL,
                status TEXT DEFAULT 'Draft',
                content TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT,
                description TEXT,
                book_id INTEGER REFERENCES books(id) ON DELETE CASCADE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS timeline (
                id SERIAL PRIMARY KEY,
                character_name TEXT,
                location TEXT,
                start_date DATE,
                end_date DATE,
                book_id INTEGER REFERENCES books(id) ON DELETE CASCADE,
                chapter_id INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS table_of_contents (
                id SERIAL PRIMARY KEY,
                content JSONB,
                book_id INTEGER UNIQUE REFERENCES books(id) ON DELETE CASCADE
            );
        """)

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        st.error(f"Schema Check Error: {e}")

run_schema_check()

# ------------------------------------------------------------------
# AGENT 0: THE ARCHITECT
# ------------------------------------------------------------------
def generate_blueprint(topic, briefing):
    with st.spinner("🕵️ The Architect is researching via Exa..."):
        query = f"{topic}: {briefing}"
        try:
            search_response = exa.search_and_contents(query, num_results=10, text=True)
        except Exception as e:
            st.error(f"Exa Error: {e}")
            return []

        dossier = ""
        if search_response and search_response.results:
            for i, result in enumerate(search_response.results):
                content_snippet = result.text[:2000] if result.text else "No text."
                dossier += f"\n--- SOURCE {i+1} ---\nTitle: {result.title}\nContent: {content_snippet}\n"

    with st.spinner("🏗️ The Architect is drafting the Table of Contents..."):
        prompt = f"""
        You are the Chief Editor of a non-fiction publishing house.
        Task: Create a Table of Contents for a book.
        Topic: {topic}
        Brief: {briefing}
        Research: {dossier}
        
        OUTPUT FORMAT:
        Return a JSON list of objects with keys: "topic", "content" (content is a detailed outline).
        Generate 5-10 chapters.
        """
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp", 
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(response.text)
            if isinstance(data, list): return data
            elif isinstance(data, dict): return data.get("chapters", list(data.values())[0])
            return []
        except Exception as e:
            st.error(f"Gemini Blueprint Error: {e}")
            return []

# ------------------------------------------------------------------
# AGENT 1: THE AUDIO ENGINEER
# ------------------------------------------------------------------
def generate_audio_chapter(text_content, voice_model="Puck"):
    chunk_size = 2000
    chunks = [text_content[i:i+chunk_size] for i in range(0, len(text_content), chunk_size)]
    combined_audio = AudioSegment.empty()
    crossfade_duration = 100
    
    with st.spinner(f"Generating Audio ({voice_model})..."):
        for index, chunk in enumerate(chunks):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash-exp", 
                    contents=f"Read this naturally:\n\n{chunk}",
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"], 
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_model)
                            )
                        )
                    )
                )
                if response.candidates and response.candidates[0].content.parts:
                    for part in response.candidates[0].content.parts:
                        if part.inline_data:
                            segment = AudioSegment(
                                data=part.inline_data.data,
                                sample_width=2, frame_rate=24000, channels=1
                            )
                            if index == 0: combined_audio = segment
                            else: combined_audio = combined_audio.append(segment, crossfade=crossfade_duration)
            except Exception as e:
                print(f"Audio Error: {e}")

    output_buffer = io.BytesIO()
    combined_audio.export(output_buffer, format="mp3")
    return output_buffer

# ------------------------------------------------------------------
# AGENT 3: THE CARTOGRAPHER
# ------------------------------------------------------------------
def run_cartographer_task(chapter_id, book_id, content):
    try:
        prompt = f"""
        Analyze this text. Extract structured data.
        TEXT: {content[:30000]}
        
        OUTPUT JSON keys:
        1. "characters": list of {{"name": "...", "role": "...", "description": "..."}}
        2. "timeline": list of {{"character_name": "...", "location": "...", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}
        """
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(response.text)
        
        conn = get_db_connection()
        cur = conn.cursor()

        chars_count = 0
        for char in data.get("characters", []):
            cur.execute("""
                INSERT INTO characters (name, role, description, book_id)
                VALUES (%s, %s, %s, %s)
            """, (char['name'], char['role'], char['description'], book_id))
            chars_count += 1

        events_count = 0
        for event in data.get("timeline", []):
            cur.execute("""
                INSERT INTO timeline (character_name, location, start_date, end_date, book_id, chapter_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (event['character_name'], event['location'], event['start_date'], event['end_date'], book_id, chapter_id))
            events_count += 1

        conn.commit()
        cur.close()
        conn.close()
        return chars_count, events_count

    except Exception as e:
        print(f"Cartographer Error: {e}")
        return 0, 0

# ------------------------------------------------------------------
# AGENT 2: THE WRITER (Background)
# ------------------------------------------------------------------
def update_chapter_status(chapter_id, status, content=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if content:
            cur.execute("UPDATE book_chapters SET status = %s, content = %s WHERE id = %s", (status, content, chapter_id))
        else:
            cur.execute("UPDATE book_chapters SET status = %s WHERE id = %s", (status, chapter_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

def background_writer_task(chapter_id, chapter_topic, book_context):
    try:
        update_chapter_status(chapter_id, "Processing")
        full_narrative = f"# {chapter_topic}\n\n"
        scenes = ["The Context", "The Events", "The Aftermath"]
        
        for scene in scenes:
            time.sleep(2) 
            prompt = f"Write a scene about '{scene}' for '{chapter_topic}'. Context: '{book_context}'."
            response = client.models.generate_content(model="gemini-2.0-flash-exp", contents=prompt)
            scene_text = response.text if response.text else ""
            full_narrative += f"## {scene}\n{scene_text}\n\n"
            update_chapter_status(chapter_id, "Processing", full_narrative)
        
        update_chapter_status(chapter_id, "Completed", full_narrative)

    except Exception as e:
        update_chapter_status(chapter_id, "Error")

# ------------------------------------------------------------------
# MAIN UI
# ------------------------------------------------------------------
def main():
    st.title("🏛️ The Newsroom")
    st.caption("Automated AI Book Publishing Platform")

    conn = get_db_connection()
    cur = conn.cursor()
    
    # ----------------------------------------------------------------
    # SIDEBAR: Library & Creation
    # ----------------------------------------------------------------
    st.sidebar.header("Library")
    
    # Initialize session state for selection
    if 'selected_book_id' not in st.session_state:
        st.session_state['selected_book_id'] = None
    if 'selected_book_title' not in st.session_state:
        st.session_state['selected_book_title'] = ""

    # FETCH BOOKS
    try:
        cur.execute("SELECT id, title FROM books ORDER BY id DESC")
        books = cur.fetchall()
    except Exception:
        books = []

    # NEW BOOK CREATOR
    with st.sidebar.expander("New Book", expanded=False):
        new_topic = st.text_input("Topic", placeholder="e.g. The Silk Road")
        mission_brief = st.text_area("Brief", placeholder="Focus on trade economics...")
        
        if st.button("Draft Blueprint"):
            if new_topic and mission_brief:
                cur.execute("INSERT INTO books (title) VALUES (%s) RETURNING id", (new_topic,))
                new_book_id = cur.fetchone()[0]
                
                generated_data = generate_blueprint(new_topic, mission_brief)
                toc_json = json.dumps(generated_data)
                cur.execute("INSERT INTO table_of_contents (book_id, content) VALUES (%s, %s)", (new_book_id, toc_json))

                for chapter in generated_data:
                    cur.execute(
                        "INSERT INTO book_chapters (book_id, topic, status, content) VALUES (%s, %s, 'Draft', %s)", 
                        (new_book_id, chapter.get('topic'), chapter.get('content'))
                    )
                conn.commit()
                # Auto-select the new book
                st.session_state['selected_book_id'] = new_book_id
                st.session_state['selected_book_title'] = new_topic
                st.success(f"Blueprint Created: {len(generated_data)} Chapters")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Topic and Brief required.")

    st.sidebar.markdown("---")

    # BOOK LIST CONTAINER (Replaces Dropdown)
    if books:
        for book_id, book_title in books:
            # Create a compact row layout
            col1, col2 = st.sidebar.columns([4, 1])
            
            # Button 1: Open Book
            # Highlight the currently selected book visually with an emoji or style
            label = f"📂 {book_title}" if st.session_state['selected_book_id'] == book_id else f"📄 {book_title}"
            
            if col1.button(label, key=f"open_book_{book_id}"):
                st.session_state['selected_book_id'] = book_id
                st.session_state['selected_book_title'] = book_title
                st.rerun()

            # Button 2: Delete Book
            if col2.button("🗑️", key=f"del_book_{book_id}", help="Delete Book"):
                try:
                    cur.execute("DELETE FROM books WHERE id = %s", (book_id,))
                    conn.commit()
                    # Reset selection if we deleted the active book
                    if st.session_state['selected_book_id'] == book_id:
                        st.session_state['selected_book_id'] = None
                        st.session_state['selected_book_title'] = ""
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Delete failed: {e}")

    else:
        st.sidebar.info("No books yet. Create one above!")

    # ----------------------------------------------------------------
    # MAIN PAGE: Chapter Interface
    # ----------------------------------------------------------------
    if st.session_state['selected_book_id']:
        st.header(f"📖 {st.session_state['selected_book_title']}")
        
        cur.execute("SELECT id, topic, status, content FROM book_chapters WHERE book_id = %s ORDER BY id", (st.session_state['selected_book_id'],))
        chapters = cur.fetchall()
        
        if not chapters:
            st.info("This book has no chapters. Try re-generating the blueprint.")
        
        for ch_id, ch_topic, ch_status, ch_content in chapters:
            # Chapter Container
            with st.expander(f"{ch_topic} [{ch_status}]"):
                
                # 1. Content Display
                if ch_status == "Draft":
                    st.caption("📝 **Outline:**")
                    st.write(ch_content if ch_content else "No outline available.")
                    
                elif ch_status == "Processing":
                    st.info("AI Writer is active...")
                    st.progress(60)
                    if ch_content:
                        st.caption(f"Drafting... ({len(ch_content.split())} words)")
                    time.sleep(3)
                    st.rerun()
                    
                elif ch_status == "Completed":
                    st.caption("✅ **Final Draft:**")
                    st.markdown(ch_content[:500] + "...\n\n*(Preview truncated)*")

                st.divider()

                # 2. Action Buttons (Below Outline/Content)
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    if ch_status in ["Draft", "Error"]:
                        if st.button("✍️ Write Chapter", key=f"write_{ch_id}"):
                            t = threading.Thread(
                                target=background_writer_task, 
                                args=(ch_id, ch_topic, st.session_state['selected_book_title'])
                            )
                            t.start()
                            st.rerun()

                with col2:
                    if ch_status == "Completed":
                        st.download_button("📥 Download Text", ch_content, file_name=f"{ch_topic}.md")

                with col3:
                    if ch_status == "Completed":
                        if st.button("🎧 Generate Audio", key=f"audio_{ch_id}"):
                            audio_data = generate_audio_chapter(ch_content)
                            st.audio(audio_data, format='audio/mp3')

                with col4:
                    if ch_status == "Completed":
                        if st.button("🗺️ Map Chapter", key=f"map_{ch_id}"):
                            with st.spinner("Cartographer is extracting data..."):
                                n_chars, n_events = run_cartographer_task(ch_id, st.session_state['selected_book_id'], ch_content)
                                st.success(f"Extracted: {n_chars} Characters, {n_events} Events")
    
    else:
        st.info("👈 Please select a book from the Library sidebar to view its chapters.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()