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
# AGENT 0: THE ARCHITECT
# ------------------------------------------------------------------
def generate_blueprint(topic, briefing):
    """
    Uses Exa (Research) and Gemini (Planning) to create the TOC.
    """
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
        Return ONLY a list of chapter topics, one per line.
        No numbers, no bullets.
        Generate 5-10 chapters.
        """
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp", 
                contents=prompt
            )
            raw_text = response.text if response.text else ""
            chapters = []
            for line in raw_text.split('\n'):
                clean = line.strip()
                # Remove "1. ", "- ", etc.
                while clean and (clean[0].isdigit() or clean[0] in ['.', '-', ' ']):
                    clean = clean[1:].strip()
                if clean:
                    chapters.append(clean)
            return chapters
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
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice_model
                                )
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
                            if index == 0:
                                combined_audio = segment
                            else:
                                combined_audio = combined_audio.append(segment, crossfade=crossfade_duration)
            except Exception as e:
                print(f"Audio Error: {e}")

    output_buffer = io.BytesIO()
    combined_audio.export(output_buffer, format="mp3")
    return output_buffer

# ------------------------------------------------------------------
# AGENT 2: THE WRITER (Background)
# ------------------------------------------------------------------
def update_chapter_status(chapter_id, status, content=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Updates chapter status identified by its PK (id)
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
            
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt
            )
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

    st.sidebar.header("Library")
    conn = get_db_connection()
    cur = conn.cursor()
    
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
                # 1. Create Book
                cur.execute("INSERT INTO books (title) VALUES (%s) RETURNING id", (new_topic,))
                new_book_id = cur.fetchone()[0]
                
                # 2. Architect Agent (Research & Plan)
                generated_chapters = generate_blueprint(new_topic, mission_brief)
                
                # 3. Store Blueprint in Table of Contents (1-to-1 Relationship)
                # We store the raw list as JSON for record-keeping
                toc_json = json.dumps(generated_chapters)
                cur.execute(
                    "INSERT INTO table_of_contents (book_id, content) VALUES (%s, %s)",
                    (new_book_id, toc_json)
                )

                # 4. Create Chapter Rows (1-to-Many Relationship)
                for chapter_title in generated_chapters:
                    cur.execute(
                        "INSERT INTO book_chapters (book_id, topic, status) VALUES (%s, %s, 'Draft')", 
                        (new_book_id, chapter_title)
                    )
                
                conn.commit()
                st.success(f"Blueprint Created: {len(generated_chapters)} Chapters")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Topic and Brief required.")

    # BOOK SELECTOR
    if books:
        book_options = {b[1]: b[0] for b in books}
        selected_title = st.sidebar.selectbox("Select Book", list(book_options.keys()))
        selected_id = book_options[selected_title]
        st.session_state['book_topic'] = selected_title 
        
        st.sidebar.markdown("---")
        
        # FETCH CHAPTERS
        # Uses the 'book_id' Foreign Key to filter chapters for the selected book
        cur.execute("SELECT id, topic, status, content FROM book_chapters WHERE book_id = %s ORDER BY id", (selected_id,))
        chapters = cur.fetchall()
        
        for ch_id, ch_topic, ch_status, ch_content in chapters:
            with st.expander(f"{ch_topic} [{ch_status}]"):
                
                if ch_status in ["Draft", "Error"]:
                    if st.button(f"Write Chapter", key=f"write_{ch_id}"):
                        t = threading.Thread(
                            target=background_writer_task, 
                            # We pass the chapter ID (PK) for updates, and book topic for context
                            args=(ch_id, ch_topic, st.session_state.get('book_topic'))
                        )
                        t.start()
                        st.rerun()
                
                elif ch_status == "Processing":
                    st.info("AI Writer is active...")
                    if ch_content:
                        st.metric("Words", len(ch_content.split()))
                    st.progress(60)
                    time.sleep(3)
                    st.rerun()
                
                elif ch_status == "Completed":
                    st.markdown(ch_content[:500] + "...")
                    st.download_button("Download Text", ch_content, file_name=f"{ch_topic}.md")
                    if st.button("Produce Audio", key=f"audio_{ch_id}"):
                        audio_data = generate_audio_chapter(ch_content)
                        st.audio(audio_data, format='audio/mp3')

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
