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
from pydub.effects import normalize
import io

# ------------------------------------------------------------------
# 1. INITIALIZATION
# ------------------------------------------------------------------
st.set_page_config(page_title="The Newsroom", page_icon="🏛️", layout="wide")

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path)

gemini_key = os.getenv("GEMINI_API_KEY")
exa_key = os.getenv("EXA_API_KEY")

if not gemini_key or not exa_key:
    st.error("CRITICAL: API Keys missing from .env file.")
    st.stop()

try:
    client = genai.Client(api_key=gemini_key)
    exa = Exa(api_key=exa_key)
except Exception as e:
    st.error(f"Client Init Error: {e}")
    st.stop()

def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ------------------------------------------------------------------
# 2. SCHEMA CHECK
# ------------------------------------------------------------------
def run_schema_check():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS books (id SERIAL PRIMARY KEY, title TEXT NOT NULL, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());")
        cur.execute("CREATE TABLE IF NOT EXISTS book_chapters (id SERIAL PRIMARY KEY, book_id INTEGER REFERENCES books(id) ON DELETE CASCADE, topic TEXT NOT NULL, status TEXT DEFAULT 'Draft', content TEXT, created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW());")
        cur.execute("CREATE TABLE IF NOT EXISTS characters (id SERIAL PRIMARY KEY, name TEXT NOT NULL, role TEXT, description TEXT, book_id INTEGER REFERENCES books(id) ON DELETE CASCADE);")
        cur.execute("CREATE TABLE IF NOT EXISTS timeline (id SERIAL PRIMARY KEY, character_name TEXT, location TEXT, start_date DATE, end_date DATE, book_id INTEGER REFERENCES books(id) ON DELETE CASCADE, chapter_id INTEGER);")
        cur.execute("CREATE TABLE IF NOT EXISTS table_of_contents (id SERIAL PRIMARY KEY, content JSONB, book_id INTEGER UNIQUE REFERENCES books(id) ON DELETE CASCADE);")
        
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='book_chapters' AND column_name='audio_status') THEN
                    ALTER TABLE book_chapters ADD COLUMN audio_status TEXT DEFAULT 'None';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='book_chapters' AND column_name='audio_msg') THEN
                    ALTER TABLE book_chapters ADD COLUMN audio_msg TEXT;
                END IF;
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='book_chapters' AND column_name='audio_data') THEN
                    ALTER TABLE book_chapters ADD COLUMN audio_data BYTEA;
                END IF;
            END $$;
        """)
        
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        st.error(f"Schema Error: {e}")

run_schema_check()

# ------------------------------------------------------------------
# 3. HELPER: SMART TEXT SPLITTER
# ------------------------------------------------------------------
def split_text_safe(text, max_chars=2500):
    if len(text) <= max_chars: return [text]
    chunks = []
    current = ""
    sentences = text.replace("! ", "!|").replace("? ", "?|").replace(". ", ".|").split("|")
    for s in sentences:
        if len(current) + len(s) < max_chars: current += s + " "
        else:
            if current: chunks.append(current.strip())
            current = s + " "
    if current: chunks.append(current.strip())
    return chunks

# ------------------------------------------------------------------
# 4. AGENTS
# ------------------------------------------------------------------
def generate_blueprint(topic, briefing):
    with st.spinner("Architect researching..."):
        query = f"{topic}: {briefing}"
        try:
            search = exa.search_and_contents(query, num_results=10, text=True)
        except: return []
        
        dossier = ""
        for r in search.results:
            txt = r.text[:2000].replace("{", "(").replace("}", ")") if r.text else ""
            dossier += f"\nTitle: {r.title}\nText: {txt}\n"

    with st.spinner("Architect drafting..."):
        prompt = f"Create a book TOC (JSON list of objects with keys 'topic', 'content').\nTopic: {topic}\nBrief: {briefing}\nContext: {dossier}"
        try:
            res = client.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(res.text)
            if isinstance(data, dict): return data.get("chapters", list(data.values())[0])
            return data
        except: return []

def run_cartographer_task(chapter_id, book_id, content):
    try:
        prompt = "Extract JSON: {'characters': [{'name','role','description'}], 'timeline': [{'character_name','location','start_date','end_date'}]}.\nTEXT: " + content[:30000]
        res = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(res.text)
        conn = get_db_connection()
        cur = conn.cursor()
        
        c_count = 0
        for c in data.get("characters", []):
            cur.execute("INSERT INTO characters (name, role, description, book_id) VALUES (%s, %s, %s, %s)", (c.get('name'), c.get('role'), c.get('description'), book_id))
            c_count += 1
            
        e_count = 0
        for e in data.get("timeline", []):
            cur.execute("INSERT INTO timeline (character_name, location, start_date, end_date, book_id, chapter_id) VALUES (%s, %s, %s, %s, %s, %s)", (e.get('character_name'), e.get('location'), e.get('start_date'), e.get('end_date'), book_id, chapter_id))
            e_count += 1
            
        conn.commit()
        cur.close()
        conn.close()
        return c_count, e_count
    except Exception as e:
        print(e)
        return 0, 0

def update_status(cid, status, text=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if text: cur.execute("UPDATE book_chapters SET status=%s, content=%s WHERE id=%s", (status, text, cid))
        else: cur.execute("UPDATE book_chapters SET status=%s WHERE id=%s", (status, cid))
        conn.commit()
        cur.close()
        conn.close()
    except: pass

def update_audio_status(cid, status, msg=None, data=None):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if data:
            cur.execute("UPDATE book_chapters SET audio_status=%s, audio_msg=%s, audio_data=%s WHERE id=%s", (status, msg, psycopg2.Binary(data), cid))
        else:
            cur.execute("UPDATE book_chapters SET audio_status=%s, audio_msg=%s WHERE id=%s", (status, msg, cid))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Audio DB Error: {e}")

# ------------------------------------------------------------------
# WORKER: TEXT WRITER
# ------------------------------------------------------------------
def background_writer_task(chapter_id, topic, book_title):
    try:
        update_status(chapter_id, "Processing")
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT book_id, content FROM book_chapters WHERE id=%s", (chapter_id,))
        res = cur.fetchone()
        bid, summary = res[0], res[1]
        
        cur.execute("SELECT name, role, description FROM characters WHERE book_id=%s", (bid,))
        chars = "\n".join([f"- {c[0]} ({c[1]}): {c[2]}" for c in cur.fetchall()])
        
        cur.execute("SELECT start_date, location, character_name FROM timeline WHERE chapter_id=%s ORDER BY start_date", (chapter_id,))
        events = "\n".join([f"- {e[0]}: {e[2]} in
