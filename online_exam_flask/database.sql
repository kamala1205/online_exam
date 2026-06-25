CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(150) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role VARCHAR(20) NOT NULL,
    manager_id VARCHAR(50)
);


CREATE TABLE IF NOT EXISTS exams (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200),
    manager_id VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS questions (
    id SERIAL PRIMARY KEY,
    exam_id INTEGER REFERENCES exams(id) ON DELETE CASCADE,
    question VARCHAR(300),
    option1 VARCHAR(100),
    option2 VARCHAR(100),
    option3 VARCHAR(100),
    option4 VARCHAR(100),
    correct VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS results (
    id SERIAL PRIMARY KEY,
    student VARCHAR(150),
    exam VARCHAR(200),
    score INTEGER,
    manager_id VARCHAR(50)
);

ALTER TABLE exams
ADD COLUMN IF NOT EXISTS notes_file VARCHAR(255);

ALTER TABLE exams
ADD COLUMN IF NOT EXISTS start_time TIMESTAMP;

ALTER TABLE exams
ADD COLUMN IF NOT EXISTS end_time TIMESTAMP;

ALTER TABLE exams
ADD COLUMN IF NOT EXISTS duration_minutes INTEGER;

CREATE TABLE IF NOT EXISTS student_answers (
    id SERIAL PRIMARY KEY,
    student VARCHAR(150),
    exam_id INTEGER,
    question_id INTEGER,
    selected_option VARCHAR(200)
);
