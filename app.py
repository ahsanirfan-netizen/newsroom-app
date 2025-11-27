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
            # Standard Text Model for Logic
            res = client.models.generate_content(
                model="gemini-2.5-flash-preview", 
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
            model="gemini-2.5-flash-preview",
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
        events = "\n".join([f"- {e[0]}: {e[2]} in {e[1]}" for e in cur.fetchall()])
        cur.close()
        conn.close()

        full_research = ""
        try:
            safe_q = f"{topic}: {summary}".replace("{","").replace("}","")
            search = exa.search_and_contents(safe_q, num_results=10, text=True)
            for i, r in enumerate(search.results):
                txt = r.text[:10000].replace("{", "(").replace("}", ")") if r.text else ""
                full_research += f"\nSOURCE {i+1}: {r.title}\n{txt}\n"
        except: full_research = "No Exa results."

        SYSTEM_PROMPT = """
        ROLE: You are a master subject matter expert and a world-class storyteller.
        GOAL: Write a verbose, detailed, and exhaustive narrative based on the data provided.
        STYLE: Extremely engaging, immersive, and expert-level. Do not summarize; dramatize and explain in depth.
        """

        MASTER = f"{SYSTEM_PROMPT}\n\nBOOK: {book_title}\nCHAPTER: {topic}\nSUMMARY: {summary}\nCHARS: {chars}\nEVENTS: {events}\nRESEARCH: {full_research[:200000]}"

        plan_prompt = f"Outline subtopics (JSON list of strings).\nCONTEXT: {MASTER[:50000]}"
        try:
            res = client.models.generate_content(model="gemini-2.5-flash-preview", contents=plan_prompt, config=types.GenerateContentConfig(response_mime_type="application/json"))
            subtopics = json.loads(res.text)
            if isinstance(subtopics, dict): subtopics = list(subtopics.values())[0]
        except: subtopics = ["Part 1", "Part 2", "Part 3"]

        narrative = f"# {topic}\n\n"
        prev_sum = "Start."
        
        for sub in subtopics:
            time.sleep(2)
            wp = f"""
            Using the SYSTEM PROMPT defined in context:
            Write 500-1000 words for Subtopic: {sub}
            Previous Context: {prev_sum}
            JSON OUTPUT: {{'text': '...', 'summary': '...'}}
            CONTEXT: {MASTER[:100000]}
            """
            try:
                w_res = client.models.generate_content(model="gemini-2.5-flash-preview", contents=wp, config=types.GenerateContentConfig(response_mime_type="application/json"))
                wd = json.loads(w_res.text)
                narrative += f"## {sub}\n{wd.get('text','')}\n\n"
                prev_sum = wd.get('summary','')
                update_status(chapter_id, "Processing", narrative)
            except: pass
            
        update_status(chapter_id, "Completed", narrative)
    except:
        update_status(chapter_id, "Error")

# ------------------------------------------------------------------
# WORKER: AUDIO ENGINEER (FIXED MODEL NAME)
# ------------------------------------------------------------------
def background_audio_task(chapter_id, text, voice="Puck"):
    try:
        update_audio_status(chapter_id, "Processing", msg="Initializing...")
        
        if not text or len(text) < 10:
            update_audio_status(chapter_id, "Error", msg="Text too short.")
            return

        chunks = split_text_safe(text, max_chars=2500)
        combined_audio = AudioSegment.empty()
        
        for i, chunk in enumerate(chunks):
            update_audio_status(chapter_id, "Processing", msg=f"Generating segment {i+1}/{len(chunks)}")
            
            try:
                # CRITICAL FIX: Using the user-verified model name
                res = client.models.generate_content(
                    model="gemini-2.5-flash-preview-tts", 
                    contents=chunk,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                            )
                        )
                    )
                )

                if res.candidates and res.candidates[0].content.parts:
                    part = res.candidates[0].content.parts[0]
                    if part.inline_data:
                        seg = AudioSegment(data=part.inline_data.data, sample_width=2, frame_rate=24000, channels=1)
                        seg = normalize(seg)
                        if i == 0: combined_audio = seg
                        else: combined_audio = combined_audio.append(seg, crossfade=100)
                    else:
                        raise ValueError("No inline audio data")
                else:
                    raise ValueError("Empty response")
                
                time.sleep(2) # Rate limit safety
                
            except Exception as e:
                # Capture full error
                update_audio_status(chapter_id, "Error", msg=f"Err Seg {i+1}: {str(e)}")
                return
        
        if len(combined_audio) > 0:
            combined_audio = normalize(combined_audio)
            buf = io.BytesIO()
            combined_audio.export(buf, format="mp3")
            update_audio_status(chapter_id, "Completed", msg="Ready", data=buf.getvalue())
        else:
            update_audio_status(chapter_id, "Error", msg="No audio generated.")

    except Exception as e:
        update_audio_status(chapter_id, "Error", msg=f"Crit: {str(e)}")

# ------------------------------------------------------------------
# 5. UI MAIN LOOP
# ------------------------------------------------------------------
def main():
    st.sidebar.header("Library")
    if 'sel_bid' not in st.session_state: st.session_state['sel_bid'] = None
    if 'sel_title' not in st.session_state: st.session_state['sel_title'] = ""

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT id, title FROM books ORDER BY id DESC")
        books = cur.fetchall()
    except: books = []

    with st.sidebar.expander("New Book"):
        new_t = st.text_input("Topic")
        new_b = st.text_area("Brief")
        if st.button("Draft Blueprint"):
            if new_t and new_b:
                cur.execute("INSERT INTO books (title) VALUES (%s) RETURNING id", (new_t,))
                bid = cur.fetchone()[0]
                data = generate_blueprint(new_t, new_b)
                cur.execute("INSERT INTO table_of_contents (book_id, content) VALUES (%s, %s)", (bid, json.dumps(data)))
                for c in data:
                    cur.execute("INSERT INTO book_chapters (book_id, topic, status, content) VALUES (%s, %s, 'Draft', %s)", (bid, c.get('topic'), c.get('content')))
                conn.commit()
                st.session_state['sel_bid'] = bid
                st.session_state['sel_title'] = new_t
                st.rerun()

    st.sidebar.divider()
    
    for bid, title in books:
        c1, c2 = st.sidebar.columns([4,1])
        lbl = f"📂 {title}" if st.session_state['sel_bid'] == bid else f"📄 {title}"
        if c1.button(lbl, key=f"open_{bid}"):
            st.session_state['sel_bid'] = bid
            st.session_state['sel_title'] = title
            st.rerun()
        if c2.button("🗑️", key=f"del_{bid}"):
            cur.execute("DELETE FROM books WHERE id=%s", (bid,))
            conn.commit()
            st.rerun()

    if st.session_state['sel_bid']:
        st.header(f"📖 {st.session_state['sel_title']}")
        cur.execute("SELECT id, topic, status, content, audio_status, audio_msg, audio_data FROM book_chapters WHERE book_id=%s ORDER BY id", (st.session_state['sel_bid'],))
        chapters = cur.fetchall()
        
        if not chapters: st.info("No chapters.")
        
        for cid, topic, status, content, aud_stat, aud_msg, aud_data in chapters:
            with st.expander(f"{topic} [{status}]"):
                if status == "Draft":
                    st.caption("Outline:")
                    st.write(content)
                elif status == "Processing":
                    st.info("AI writing...")
                    st.progress(50)
                    time.sleep(3)
                    st.rerun()
                elif status == "Completed":
                    st.markdown(content[:500]+"...")
                
                st.divider()
                c1, c2, c3, c4 = st.columns(4)
                
                if status == "Draft":
                    if c1.button("🗺️ Map Plan", key=f"map_{cid}"):
                        with st.spinner("Mapping..."):
                            nc, ne = run_cartographer_task(cid, st.session_state['sel_bid'], content)
                            st.success(f"Mapped {nc} chars, {ne} events")
                
                if status in ["Draft", "Error"]:
                    if c2.button("✍️ Write", key=f"wr_{cid}"):
                        t = threading.Thread(target=background_writer_task, args=(cid, topic, st.session_state['sel_title']))
                        t.start()
                        st.rerun()
                
                if status == "Completed":
                    c3.download_button("📥 Text", content, file_name=f"{topic}.md")
                
                if status == "Completed":
                    if not aud_stat or aud_stat == "None":
                        if c4.button("🎧 Gen Audio", key=f"au_{cid}"):
                            t = threading.Thread(target=background_audio_task, args=(cid, content))
                            t.start()
                            st.rerun()
                    elif aud_stat == "Processing":
                        c4.info(f"🎙️ {aud_msg}")
                        time.sleep(2)
                        st.rerun()
                    elif aud_stat == "Completed" and aud_data:
                        c4.audio(bytes(aud_data), format='audio/mp3')
                        if c4.button("🔄 Reset", key=f"rst_{cid}"):
                            update_audio_status(cid, "None")
                            st.rerun()
                    elif aud_stat == "Error":
                        c4.error(f"{aud_msg}")
                        if c4.button("🔄 Retry", key=f"rty_{cid}"):
                            t = threading.Thread(target=background_audio_task, args=(cid, content))
                            t.start()
                            st.rerun()

    else:
        st.info("Select a book from the sidebar.")

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
