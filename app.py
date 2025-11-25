# ... (Keep imports and setup at the top) ...

# ==============================================================================
# 📱 THE UI (Updated Sidebar)
# ==============================================================================
with st.sidebar:
    st.header("Chapter Settings")
    
    # --- NEW: THE MISSION BRIEF ---
    st.info("💡 Pro Tip: Be specific. E.g., 'Find primary sources describing the exact moment Brutus stabbed Caesar in the Senate.'")
    
    mission_brief = st.text_area(
        "Mission Brief / Research Prompt", 
        "Find detailed historical accounts of the assassination of Julius Caesar on the Ides of March, 44 BC, focusing on the conspirators Brutus and Cassius.",
        height=150
    )
    
    # We derive a short "Topic" just for the file name/header
    topic_label = st.text_input("Short Label (for files)", "Julius Caesar")
    
    st.divider()
    st.caption("Manual Overrides (Optional)")
    character = st.text_input("Character", "Napoleon")
    location = st.text_input("Location", "Paris")
    start_date = st.date_input("Start Date")
    end_date = st.date_input("End Date")
    
    # ... (Keep History & Dramatis Personae sections) ...

# ==============================================================================
# 🚀 MAIN LOGIC
# ==============================================================================

# BUTTON 1: THE CARTOGRAPHER
if st.button("🗺️ 1. Research & Map Territory"):
    status = st.empty()
    try:
        # A. Research (Using the Full Mission Brief)
        status.info(f"📚 Exa is finding sources for: '{mission_brief[:50]}...'")
        
        # Use the full brief for the Neural Search
        search = exa.search_and_contents(
            mission_brief, 
            type="neural", 
            num_results=1, 
            text=True
        )
        
        if not search.results:
            st.error("Exa found no results. Try a different prompt.")
            st.stop()
            
        source_text = search.results[0].text
        
        # B. Map (Gemini)
        status.info("🧠 Gemini is extracting knowledge graph...")
        count, data, conflicts = run_cartographer(source_text)
        
        status.success(f"Success! Mapped {count} new events to the Physics Engine.")
        
        if len(conflicts) > 0:
            st.warning(f"Skipped {len(conflicts)} conflicting events (Physics Engine Blocked).")
            
        with st.expander("View Extracted Data"):
            st.json(data)
            st.caption("Source Text Preview:")
            st.text(source_text[:500])
            
    except Exception as e:
        st.error("Cartographer Failed")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())

# BUTTON 2: THE WRITER
if st.button("✍️ 2. Write Chapter (With Physics Check)"):
    status = st.empty()
    try:
        status.info("🛡️ Checking Physics...")
        
        # 1. Physics Check (Manual Override)
        supa_headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        payload_check = {
            "character_name": character,
            "location": location,
            "start_date": str(start_date),
            "end_date": str(end_date)
        }
        
        check = requests.post(f"{SUPABASE_URL}/rest/v1/timeline", headers=supa_headers, json=payload_check)
        if check.status_code >= 400:
            st.error(f"🛑 PHYSICS ERROR: {check.text}")
            st.stop()
            
        status.success("✅ Physics Check Passed")
        
        # 2. Research (Using the Mission Brief)
        status.info("📚 Researching...")
        search = exa.search_and_contents(mission_brief, type="neural", num_results=1, text=True)
        source = search.results[0].text[:1500]
        
        # 3. Draft
        status.info("✍️ Perplexity is writing...")
        draft_resp = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": f"Write a scene about {topic_label}. Source: {source}"}]
        )
        draft = draft_resp.choices[0].message.content
        
        # 4. Save
        status.info("💾 Saving to Bookshelf...")
        save_payload = {"topic": topic_label, "content": draft}
        requests.post(f"{SUPABASE_URL}/rest/v1/book_chapters", headers=supa_headers, json=save_payload)
        
        status.empty()
        st.balloons()
        st.subheader(f"Chapter: {topic_label}")
        st.write(draft)
        
    except Exception as e:
        st.error("Writer Failed")
        with st.expander("Technical Logs"):
            st.code(traceback.format_exc())
