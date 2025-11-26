import threading
import time
import streamlit as st
# ... other imports (psycopg2, google_genai, etc.) ...

# ------------------------------------------------------------------
# BACKGROUND WORKER: The Writer Agent
# ------------------------------------------------------------------
def background_writer_task(chapter_id, chapter_title, topic_context):
    """
    Executes the Writer Agent logic in a background thread.
    This prevents the Streamlit UI from blocking/timing out.
    """
    try:
        # 1. Update DB Status -> 'Processing'
        # (Assuming you have a function `update_chapter_status(id, status)`)
        update_chapter_status(chapter_id, "Processing")
        
        # 2. Research Phase (Exa.ai)
        # Fetch sources for this specific chapter
        sources = get_exa_research(f"{topic_context}: {chapter_title}")
        
        # 3. Writing Phase (Gemini 2.5)
        # Initialize the narrative
        full_narrative = ""
        
        # "Fractal Mode": Break chapter into 5 scenes to manage context
        scenes = generate_scene_list(chapter_title) # Returns list of 5 sub-topics
        
        for i, scene in enumerate(scenes):
            # Fetch last 5000 chars for context
            prev_context = full_narrative[-5000:] if full_narrative else ""
            
            # Write the scene
            scene_text = write_scene_with_gemini(scene, sources, prev_context)
            full_narrative += f"\n\n## {scene}\n{scene_text}"
            
            # CRITICAL: Save progress to DB after EACH scene.
            # This allows the user to see the word count grow in real-time.
            save_chapter_draft(chapter_id, full_narrative)
        
        # 4. Finalize
        update_chapter_status(chapter_id, "Completed")
        print(f"Chapter {chapter_id} writing complete.")

    except Exception as e:
        print(f"Error in background writer: {e}")
        update_chapter_status(chapter_id, "Error")

# ------------------------------------------------------------------
# FRONTEND UI: The "Write" Button
# ------------------------------------------------------------------
def render_writer_ui(chapter):
    st.subheader(f"Chapter: {chapter['title']}")
    
    # Check current status from DB
    # (Assuming `get_chapter_details` fetches the row from Supabase)
    current_state = get_chapter_details(chapter['id'])
    status = current_state.get('status', 'Draft')
    content = current_state.get('content', '')
    
    # 1. Button Logic
    if status == "Draft" or status == "Error":
        if st.button("Start AI Writer"):
            # Spawn the thread!
            t = threading.Thread(
                target=background_writer_task, 
                args=(chapter['id'], chapter['title'], st.session_state.get('book_topic'))
            )
            t.start()
            
            # Force a rerun to update the UI state immediately
            st.rerun()

    # 2. Polling Logic (The "Keep-Alive" Fix)
    elif status == "Processing":
        st.info("AI Writer is active... (Do not close this tab)")
        
        # Show live progress
        word_count = len(content.split())
        st.metric(label="Words Written", value=word_count)
        
        # Animated progress bar
        st.progress(60) # Indeterminate or calculated based on scene count
        
        # Wait 5 seconds and refresh. 
        # This keeps the websocket active and prevents Nginx timeout.
        time.sleep(5) 
        st.rerun()

    # 3. Completion State
    elif status == "Completed":
        st.success("Chapter Complete!")
        st.markdown(content)
        
        # Option to regenerate audio (using the fixed Audio code)
        if st.button("Generate Audio"):
            # ... call audio generation ...
            pass