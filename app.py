import os
import time
import threading
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydub import AudioSegment
import io
import requests

# Load Environment Variables
# Force load from the absolute path to ensure Systemd finds it
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

api_key = os.getenv("GEMINI_API_KEY")

# Safety Check: Stop the app immediately if the key is missing
if not api_key:
    raise ValueError(f"CRITICAL ERROR: GEMINI_API_KEY not found in {env_path}. Please check your .env file.")

# Initialize Gemini Client (v1 SDK)
client = genai.Client(api_key=api_key)

# ------------------------------------------------------------------
# DATABASE & SETUP
# ------------------------------------------------------------------
st.set_page_config(page_title="The Newsroom", page_icon="🏛️", layout="wide")

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ------------------------------------------------------------------
# AGENT 1: THE AUDIO ENGINEER
# ------------------------------------------------------------------
def generate_audio_chapter(text_content, voice_model="Puck"):
    """
    Converts chapter text to MP3 using Gemini 2.5 Flash Preview.
    """
    chunk_size = 2000
    chunks = [text_content[i:i+chunk_size] for i in range(0, len(text_content), chunk_size)]
    combined_audio = AudioSegment.empty()
    crossfade_duration = 100
    
    # Gemini Native Audio Specs
    SAMPLE_RATE = 24000
    CHANNELS = 1
    SAMPLE_WIDTH = 2 

    # Show a spinner in the UI if called from main thread
    with st.spinner(f"Generating Audio with voice: {voice_model}..."):
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
                            raw_audio_data = part.inline_data.data
                            segment = AudioSegment(
                                data=raw_audio_data,
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

def background_writer_task(chapter_id, chapter_title, topic_context):
    """
    Executes the Writer Agent in a background thread.
    """
    try:
        print(f"Starting background job for Chapter {chapter_id}")
        update_chapter_status(chapter_id, "Processing")
        
        # Simulating Research & Writing Loop
        full_narrative = f"# {chapter_title}\n\n"
        scenes = ["The Beginning", "The Conflict", "The Resolution"]
        
        for scene in scenes:
            time.sleep(3) # Simulate research time
            
            prompt = f"Write a historical narrative scene about '{scene}' regarding '{chapter_title}' in the context of '{topic_context}'."
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview",
                contents=prompt
            )
            scene_text = response.text if response.text else "[Error generating text]"
            
            full_narrative += f"## {scene}\n{scene_text}\n\n"
            update_chapter_status(chapter_id, "Processing", full_narrative)
        
        update_chapter_status(chapter_id, "Completed", full_narrative)
        print(f"Job for Chapter {chapter_id} finished.")

    except Exception as e:
        print(f"Background Writer Error: {e}")
        update_chapter_status(chapter_id, "Error")

# ------------------------------------------------------------------
# MAIN UI ARCHITECTURE
# ------------------------------------------------------------------
def main():
    st.title("🏛️ The Newsroom")
    st.caption("Automated AI Book Publishing Platform")

    # Sidebar: Book Selection
    st.sidebar.header("Library")
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch from 'books'
    cur.execute("SELECT id, title FROM books ORDER BY id DESC")
    books = cur.fetchall()
    
    # Book Creator
    with st.sidebar.expander("New Book"):
        new_topic = st.text_input("Topic")
        if st.button("Draft Blueprint"):
            cur.execute("INSERT INTO books (title) VALUES (%s) RETURNING id", (new_topic,))
            new_id = cur.fetchone()[0]
            
            # FIXED: Insert into 'topic' instead of 'title'
            cur.execute("INSERT INTO book_chapters (book_id, topic, status) VALUES (%s, %s, 'Draft')", (new_id, "Chapter 1: The Spark"))
            conn.commit()
            st.rerun()

    # Book Selector
    if books:
        book_options = {b[1]: b[0] for b in books}
        selected_title = st.sidebar.selectbox("Select Book", list(book_options.keys()))
        selected_id = book_options[selected_title]
        st.session_state['book_topic'] = selected_title 
        
        st.sidebar.markdown("---")
        
        # FIXED: Select 'topic' instead of 'title'
        cur.execute("SELECT id, topic, status, content FROM book_chapters WHERE book_id = %s ORDER BY id", (selected_id,))
        chapters = cur.fetchall()
        
        # Display Chapters
        for ch_id, ch_topic, ch_status, ch_content in chapters:
            with st.expander(f"{ch_topic} [{ch_status}]", expanded=True):
                
                # STATUS: DRAFT or ERROR
                if ch_status in ["Draft", "Error"]:
                    if st.button(f"Write '{ch_topic}'", key=f"write_{ch_id}"):
                        t = threading.Thread(
                            target=background_writer_task, 
                            args=(ch_id, ch_topic, st.session_state.get('book_topic'))
                        )
                        t.start()
                        st.rerun()

                # STATUS: PROCESSING
                elif ch_status == "Processing":
                    st.info("AI Writer is active... (Do not close this tab)")
                    if ch_content:
                        word_count = len(ch_content.split())
                        st.metric("Words Written", word_count)
                    st.progress(60) 
                    time.sleep(3) 
                    st.rerun() 
                
                # STATUS: COMPLETED
                elif ch_status == "Completed":
                    st.success("Chapter Written")
                    st.download_button("Download Text", ch_content, file_name=f"{ch_topic}.md")
                    
                    if st.button(f"Produce Audio", key=f"audio_{ch_id}"):
                        audio_data = generate_audio_chapter(ch_content)
                        st.audio(audio_data, format='audio/mp3')
                        st.download_button("Download MP3", audio_data, file_name=f"{ch_topic}.mp3")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()