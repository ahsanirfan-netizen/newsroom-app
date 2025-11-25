-- 1. The Bookshelf (No changes, but kept for context)
CREATE TABLE IF NOT EXISTS book_chapters (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. The Timeline
CREATE TABLE IF NOT EXISTS timeline (
    id SERIAL PRIMARY KEY,
    character_name TEXT,
    location TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    chapter_id INT
);

-- 3. Dramatis Personae
CREATE TABLE IF NOT EXISTS characters (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    role TEXT,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ==================================================================
-- 🛠️ MIGRATION: ADD GRANULARITY & PHYSICS ENGINE LOGIC
-- ==================================================================

-- A. Add the 'granularity' column to store if a date is 'day' (exact) or 'year' (vague)
ALTER TABLE timeline ADD COLUMN IF NOT EXISTS granularity TEXT DEFAULT 'day';

-- B. The Physics Logic Function
-- This function runs before every save. It checks for conflicts.
CREATE OR REPLACE FUNCTION check_physics_violation()
RETURNS TRIGGER AS $$
BEGIN
    -- PHYSICS RULE:
    -- A conflict ONLY exists if:
    -- 1. Same Character
    -- 2. Different Location
    -- 3. Dates Overlap
    -- 4. AND BOTH entries are 'day' (Exact precision).
    -- If one entry is 'year' (vague), we allow the overlap (assuming the specific event happened during that year).

    IF EXISTS (
        SELECT 1 FROM timeline
        WHERE character_name = NEW.character_name
          AND location <> NEW.location
          AND (start_date, end_date) OVERLAPS (NEW.start_date, NEW.end_date)
          AND id <> NEW.id -- Don't block itself
          AND granularity = 'day'      -- Existing entry is strict
          AND NEW.granularity = 'day'  -- New entry is strict
    ) THEN
        RAISE EXCEPTION 'IMPOSSIBILITY ERROR: % cannot be in % and another location at the same time (Exact Date Conflict).', NEW.character_name, NEW.location USING ERRCODE = 'P0001';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- C. Apply the Trigger
DROP TRIGGER IF EXISTS trigger_physics_check ON timeline;

CREATE TRIGGER trigger_physics_check
BEFORE INSERT OR UPDATE ON timeline
FOR EACH ROW EXECUTE FUNCTION check_physics_violation();
