-- 1. THE LIBRARY (Books)
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    user_prompt TEXT,
    status TEXT DEFAULT 'planning',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. THE OUTLINE (Table of Contents)
CREATE TABLE IF NOT EXISTS table_of_contents (
    id SERIAL PRIMARY KEY,
    book_id INT REFERENCES books(id),
    chapter_number INT,
    title TEXT,
    summary_goal TEXT,
    status TEXT DEFAULT 'pending'
);

-- 3. THE DRAFTS (Written Chapters)
CREATE TABLE IF NOT EXISTS book_chapters (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. THE CAST (Dramatis Personae)
CREATE TABLE IF NOT EXISTS characters (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    role TEXT,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. THE PHYSICS ENGINE (Timeline)
CREATE TABLE IF NOT EXISTS timeline (
    id SERIAL PRIMARY KEY,
    character_name TEXT,
    location TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    chapter_id INT
);
