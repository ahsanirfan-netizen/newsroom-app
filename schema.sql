-- 1. The Bookshelf (Where we save chapters)
CREATE TABLE IF NOT EXISTS book_chapters (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. The Timeline (The Physics Engine)
CREATE TABLE IF NOT EXISTS timeline (
    id SERIAL PRIMARY KEY,
    character_name TEXT,
    location TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    chapter_id INT
);

-- 3. NEW TABLE: Dramatis Personae (Character Bios)
CREATE TABLE IF NOT EXISTS characters (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    role TEXT,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
