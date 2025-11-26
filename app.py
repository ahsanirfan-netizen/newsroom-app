import os
import time
import threading
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from exa_py import Exa
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
    FIXED: Uses 'gemini-2.0-flash-exp' which is the valid model ID.
    """
    with st.spinner("🕵️ The Architect is researching via Exa..."):
        query = f"{topic}: {briefing}"
        search_response = exa.search_and_contents(
            query,
            num_results=10,
            text=True 
        )
        
        dossier = ""
        for i, result in enumerate(search_response.results):
            # Safe truncation to prevent token overflow
            content_snippet = result.text[:2000] if result.text else "No text content."
            dossier += f"\n--- SOURCE {i+1} ---\nTitle: {result.title}\nContent: {content_snippet}\n"

    with st.spinner("🏗️ The Architect is drafting the Table of Contents..."):
        prompt = f"""
        You are the Chief Editor of a non-fiction publishing house.
        
        Task: Create a Table of Contents for a book.
        Topic: {topic}
        Mission Brief: {briefing}
        
        Use the following research to ensure factual accuracy and depth:
        {dossier} 

        OUTPUT FORMAT:
        Return ONLY a list of chapter topics, one per line. 
        Do not use numbers (1. 2. 3.) or markdown bullets. 
        Just the raw topic text for each chapter.
        Generate between 5 and 10 chapters.
        """
        
        # FIXED: Model Name Update
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp", 
            contents=prompt
        )
        
        raw_text = response.text if response.text else ""
        # Robust cleaning to handle "1. Chapter Name" or "- Chapter Name"
        chapters = []
        for line in raw_text.split('\n'):
            clean_line = line.strip()
            # Remove leading numbers, dots, and hyphens
            while clean_line and (clean_line[0].isdigit() or clean_line[0] in ['.', '-', ' ']):
                clean_line = clean_line[1:].strip()
            
            if clean_line:
                chapters.append(clean_line)
        
        return chapters

# ------------------------------------------------------------------
# AGENT 1: THE AUDIO ENGINEER
# ------------------------------------------------------------------
def generate_audio_chapter(text_content, voice_model="Puck"):
    # Chunking to safe limits (2k characters)
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
                # FIXED: Model Name Update
                response = client.models.generate_content(
                    model="gemini-2.0-flash-exp", 
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
        
        full_narrative = f"# {chapter_topic}\n\n"
        scenes = ["The Context", "The Events", "The Aftermath"]
        
        for scene in scenes:
            time.sleep(2) 
            prompt = f"Write a narrative scene about '{scene}' for the chapter '{chapter_topic}'. Book Context: '{book_context}'."
            
            # FIXED: Model Name Update
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
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