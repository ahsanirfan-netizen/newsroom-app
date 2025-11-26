import os
import time
import threading
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from exa_py import Exa  # Added Exa Library
from pydub import AudioSegment
import io

# Load Environment Variables
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

# Validate Keys
gemini_key = os.getenv("GEMINI_API_KEY")
exa_key = os.getenv("EXA_API_KEY")

if not gemini_key:
    raise ValueError("CRITICAL: GEMINI_API_KEY missing.")
if not exa_key:
    raise ValueError("CRITICAL: EXA_API_KEY missing.")

# Initialize Clients
client = genai.Client(api_key=gemini_key)
exa = Exa(api_key=exa_key)

# ------------------------------------------------------------------
# DATABASE & SETUP
# ------------------------------------------------------------------
st.set_page_config(page_title="The Newsroom", page_icon="🏛️", layout="wide")

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ------------------------------------------------------------------
# AGENT 0: THE ARCHITECT (Blueprinting)
# ------------------------------------------------------------------
def generate_blueprint(topic, briefing):
    """
    Uses Exa to research and Gemini to plan the Table of Contents.
    """
    with st.spinner("🕵️ The Architect is researching via Exa..."):
        # 1. Research (Exa)
        # We combine topic and briefing for a semantic search
        query = f"{topic}: {briefing}"
        search_response = exa.search_and_contents(
            query,
            num_results=10,
            text=True  # Get full text content
        )
        
        # Compile research into a dossier
        dossier = ""
        for i, result in enumerate(search_response.results):
            dossier += f"\n--- SOURCE {i+1} ---\nTitle: {result.title}\nContent: {result.text[:5000]}\n"

    with st.spinner("🏗️ The Architect is drafting the Table of Contents..."):
        # 2. Planning (Gemini)
        prompt = f"""
        You are the Chief Editor of a non-fiction publishing house.
        
        Task: Create a Table of Contents for a book.
        Topic: {topic}
        Mission Brief: {briefing}
        
        Use the following research to ensure factual accuracy and depth:
        {dossier[:100000]} 

        OUTPUT FORMAT:
        Return ONLY a list of chapter topics, one per line. 
        Do not use numbers (1. 2. 3.) or markdown bullets. 
        Just the raw topic text for each chapter.
        Generate between 5 and 10 chapters.
        """
        
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview",
            contents=prompt
        )
        
        # Parse response into a list
        raw_text = response.text if response.text else ""
        # Clean up lines (remove empty lines or numbering if AI hallucinated them)
        chapters = [line.strip().lstrip("1234567890. ") for line in raw_text.split('\n') if line.strip()]
        
        return chapters

# ------------------------------------------------------------------
# AGENT 1: THE AUDIO ENGINEER
# ------------------------------------------------------------------
def generate_audio_chapter(text_content, voice_model="Puck"):
    chunk_size = 2000
    chunks = [text_content[i:i+chunk_size] for i in range(0, len(text_content), chunk_size)]
    combined_audio = AudioSegment.empty()
    crossfade_duration = 100
    
    SAMPLE_RATE = 24000
    CHANNELS = 1
    SAMPLE_WIDTH = 2 

    with st.spinner(f"Generating Audio ({voice_model})..."):
        for index, chunk in enumerate(chunks):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash-preview", 
                    contents=f"Read the following text clearly and naturally:\n\n{chunk}",
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
                                sample_width=SAMPLE_WIDTH,
                                frame_rate=SAMPLE_RATE,
                                channels=CHANNELS
                            )
                            if index == 0:
                                combined_audio = segment
                            else:
                                combined_audio = combined_audio.append(segment, crossfade=crossfade_duration)
            except Exception as e:
                print(f"Error generating chunk {index}: {e}")

    output_buffer = io.BytesIO()
    combined_audio.export(output_buffer, format="mp3")
    return output_buffer

# ------------------------------------------------------------------
# AGENT 2: THE WRITER
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
        
        # Research specific to this chapter (Simulated or Real Exa call can go here)
        full_narrative = f"# {chapter_topic}\n\n"
        scenes = ["The Context", "The Events", "The Aftermath"]
        
        for scene in scenes:
            time.sleep(2) 
            prompt = f"Write a narrative scene about '{scene}' for the chapter '{chapter_topic}'. Book Context: '{book_context}'."
            
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview",
                contents=prompt
            )
            scene_text = response.text if response.text else ""
            full_narrative += f"## {scene}\n{scene_text}\n\n"
            update_chapter_status(chapter_id, "Processing", full_narrative)
        
        update_chapter_status(chapter_id, "Completed", full_narrative)

    except Exception as e:
        print(f"Writer Error: {e}")
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
    
    # 1. Fetch Books
    cur.execute("SELECT id, title FROM books ORDER BY id DESC")
    books = cur.fetchall()
    
    # 2. Book Creator (UPDATED with Exa/Mission Brief)
    with st.sidebar.expander("New Book", expanded=False):
        new_topic = st.text_input("Book Topic", placeholder="e.g. The Fall of Rome")
        # Added: Mission Brief Input
        mission_brief = st.text_area("Mission Brief", placeholder="Focus on economic factors...")
        
        if st.button("Draft Blueprint"):
            if new_topic and mission_brief:
                # A. Create Book Entry
                cur.execute("INSERT INTO books (title) VALUES (%s) RETURNING id", (new_topic,))
                new_book_id = cur.fetchone()[0]
                conn.commit() # Commit early to get ID
                
                # B. Run Architect Agent
                generated_chapters = generate_blueprint(new_topic, mission_brief)
                
                # C. Insert Chapters
                for chapter_title in generated_chapters:
                    # NOTE: Assuming 'book_id' column exists. If user insists on 'id' being the FK, change 'book_id' to 'id'.
                    # Standard SQL: book_chapters(id PK, book_id FK, topic, status)
                    cur.execute(
                        "INSERT INTO book_chapters (book_id, topic, status) VALUES (%s, %s, 'Draft')", 
                        (new_book_id, chapter_title)
                    )
                conn.commit()
                st.success(f"Blueprint created with {len(generated_chapters)} chapters!")
                time.sleep(1)
                st.rerun()
            else:
                st.warning("Please provide both a Topic and a Mission Brief.")

    # 3. Book Selector
    if books:
        book_options = {b[1]: b[0] for b in books}
        selected_title = st.sidebar.selectbox("Select Book", list(book_options.keys()))
        selected_id = book_options[selected_title]
        st.session_state['book_topic'] = selected_title 
        
        st.sidebar.markdown("---")
        
        # 4. Fetch Chapters
        # Note: 'book_id' is the standard FK column name.
        cur.execute("SELECT id, topic, status, content FROM book_chapters WHERE book_id = %s ORDER BY id", (selected_id,))
        chapters = cur.fetchall()
        
        for ch_id, ch_topic, ch_status, ch_content in chapters:
            with st.expander(f"{ch_topic} [{ch_status}]"):
                if ch_status in ["Draft", "Error"]:
                    if st.button(f"Write Chapter", key=f"write_{ch_id}"):
                        t = threading.Thread(
                            target=background_writer_task, 
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
