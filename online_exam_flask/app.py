from werkzeug.utils import secure_filename
import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import google.generativeai as genai
from dotenv import load_dotenv
import os

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'exam-secret')


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {'pdf'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------------- POSTGRES CONFIG ----------------
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_NAME = os.environ.get('DB_NAME', 'online')
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'Bapun@123')
DB_PORT = os.environ.get('DB_PORT', '5432')

def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        port=DB_PORT
    )

# ---------------- AUTH CHECK ----------------
def login_required(role=None):
    def wrapper(fn):
        def decorated(*args, **kwargs):
            if not session.get('user'):
                flash("Please login", "error")
                return redirect(url_for('login'))
            if role and session['user']['role'] != role:
                flash("Unauthorized access", "error")
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        decorated.__name__ = fn.__name__
        return decorated
    return wrapper

# ---------------- LOGIN ----------------
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password'].strip()

        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user['password'], password):
            session['user'] = user
            return redirect(url_for(f"{user['role']}_dashboard"))

        flash("Invalid email or password", "error")

    return render_template('login.html')


# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        password = generate_password_hash(request.form['password'].strip())
        role = request.form['role']

        conn = get_db_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 🔥 Check if email already exists
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close()
            conn.close()
            flash("Email already registered. Please login.", "error")
            return redirect(url_for('register'))

        manager_id = None
        if role == 'admin':
            manager_id = "ADM-" + uuid.uuid4().hex[:6].upper()

        if role == 'student':
            manager_id = request.form['manager_id'].strip()
            cur.execute(
                "SELECT id FROM users WHERE role='admin' AND manager_id=%s",
                (manager_id,)
            )
            if not cur.fetchone():
                cur.close()
                conn.close()
                flash("Invalid Manager ID", "error")
                return redirect(url_for('register'))

        try:
            cur.execute("""
                INSERT INTO users (username, email, password, role, manager_id)
                VALUES (%s, %s, %s, %s, %s)
            """, (username, email, password, role, manager_id))
            conn.commit()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for('login'))
        except Exception:
            conn.rollback()
            flash("Something went wrong. Try again.", "error")
        finally:
            cur.close()
            conn.close()

    return render_template('register.html')

# ---------------- ADMIN DASHBOARD ----------------
@app.route('/admin')
@login_required(role='admin')
def admin_dashboard():
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("SELECT * FROM exams WHERE manager_id=%s", (user['manager_id'],))
    exams = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*) FROM users
        WHERE role='student' AND manager_id=%s
    """, (user['manager_id'],))
    total_students = cur.fetchone()['count']

    cur.execute("""
        SELECT COUNT(*) FROM results WHERE manager_id=%s
    """, (user['manager_id'],))
    total_results = cur.fetchone()['count']

    cur.close()
    conn.close()

    stats = {
        "total_exams": len(exams),
        "total_students": total_students,
        "total_results": total_results
    }

    return render_template(
        'admin_dashboard.html',
        exams=exams,
        stats=stats,
        manager_id=user['manager_id']
    )

# ---------------- VIEW STUDENTS ----------------
@app.route('/admin/students')
@login_required(role='admin')
def admin_students():
    user = session['user']

    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT username, email, manager_id
        FROM users
        WHERE role='student' AND manager_id=%s
        ORDER BY username
    """, (user['manager_id'],))

    students = cur.fetchall()
    cur.close()
    conn.close()

    return render_template(
        'admin_students.html',
        students=students,
        manager_id=user['manager_id']
    )

@app.route('/admin/results')
@login_required(role='admin')
def admin_results():
    user = session['user']

    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT * FROM results
        WHERE manager_id = %s
        ORDER BY id DESC
    """, (user['manager_id'],))

    results = cur.fetchall()
    cur.close()
    conn.close()

    return render_template('admin_results.html', results=results)

@app.route('/upload_notes/<int:exam_id>', methods=['POST'])
@login_required(role='admin')
def upload_notes(exam_id):
    user = session['user']
    file = request.files.get('notes')

    if not file or not allowed_file(file.filename):
        flash("Only PDF files allowed", "error")
        return redirect(url_for('admin_dashboard'))

    filename = secure_filename(f"{exam_id}_{file.filename}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE exams
        SET notes_file=%s
        WHERE id=%s AND manager_id=%s
    """, (filename, exam_id, user['manager_id']))
    conn.commit()
    cur.close()
    conn.close()

    flash("Notes uploaded successfully", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_notes/<int:exam_id>', methods=['POST'])
@login_required(role='admin')
def delete_notes(exam_id):
    user = session['user']

    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT notes_file FROM exams
        WHERE id=%s AND manager_id=%s
    """, (exam_id, user['manager_id']))
    exam = cur.fetchone()

    if exam and exam['notes_file']:
        path = os.path.join(app.config['UPLOAD_FOLDER'], exam['notes_file'])
        if os.path.exists(path):
            os.remove(path)

        cur.execute("""
            UPDATE exams SET notes_file=NULL
            WHERE id=%s AND manager_id=%s
        """, (exam_id, user['manager_id']))
        conn.commit()

    cur.close()
    conn.close()

    flash("Notes deleted", "success")
    return redirect(url_for('admin_dashboard'))

# ---------------- CREATE EXAM ----------------
@app.route('/create_exam', methods=['GET', 'POST'])
@login_required(role='admin')
def create_exam():
    if request.method == 'POST':
        title = request.form['title'].strip()
        start_time = request.form.get('start_time') or None
        end_time = request.form.get('end_time') or None
        duration = request.form.get('duration_minutes')

        user = session['user']

        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO exams (title, manager_id, start_time, end_time, duration_minutes)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            title,
            user['manager_id'],
            start_time,
            end_time,
            duration
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Exam created successfully", "success")
        return redirect(url_for('admin_dashboard'))

    return render_template('create_exam.html')


# ---------------- ADD QUESTION ----------------
@app.route('/add_question/<int:exam_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def add_question(exam_id):
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 🚫 Block editing if exam already started
    cur.execute("""
        SELECT start_time FROM exams
        WHERE id=%s AND manager_id=%s
    """, (exam_id, user['manager_id']))
    exam = cur.fetchone()

    if exam and exam['start_time'] and exam['start_time'] <= datetime.now():
        flash("Exam already started. Cannot modify questions.", "error")
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        # Delete old questions (edit mode)
        cur.execute("DELETE FROM questions WHERE exam_id=%s", (exam_id,))

        questions = request.form.getlist('question[]')
        option1s = request.form.getlist('option1[]')
        option2s = request.form.getlist('option2[]')
        option3s = request.form.getlist('option3[]')
        option4s = request.form.getlist('option4[]')
        corrects = request.form.getlist('correct[]')

        for i in range(len(questions)):
            cur.execute("""
                INSERT INTO questions
                (exam_id, question, option1, option2, option3, option4, correct)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                exam_id,
                questions[i],
                option1s[i],
                option2s[i],
                option3s[i],
                option4s[i],
                corrects[i]
            ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Questions saved successfully", "success")
        return redirect(url_for('admin_dashboard'))

    # 🔥 Load existing questions
    cur.execute("SELECT * FROM questions WHERE exam_id=%s", (exam_id,))
    questions = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        'add_question.html',
        exam_id=exam_id,
        questions=questions
    )

@app.route('/generate_questions_ai/<int:exam_id>', methods=['POST'])
@login_required(role='admin')
def generate_questions_ai(exam_id):
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # 1️⃣ Fetch exam + PDF (STRICT: only this exam ID)
    cur.execute("""
        SELECT notes_file, title
        FROM exams
        WHERE id=%s AND manager_id=%s
    """, (exam_id, user['manager_id']))
    exam = cur.fetchone()

    if not exam or not exam['notes_file']:
        cur.close()
        conn.close()
        return jsonify({
            "error": "Upload notes before generating questions"
        }), 400

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], exam['notes_file'])

    if not os.path.exists(pdf_path):
        cur.close()
        conn.close()
        return jsonify({"error": "Notes file not found"}), 404

    # 2️⃣ Extract PDF text
    import fitz  # PyMuPDF
    text = ""
    doc = fitz.open(pdf_path)
    for page in doc:
        text += page.get_text()
    doc.close()

    if not text.strip():
        return jsonify({"error": "PDF has no readable text"}), 400

    # 3️⃣ Gemini prompt (strict format)
    prompt = f"""
You are an exam question generator.

From the content below, generate EXACTLY 10 multiple-choice questions.

Each question must include:
- Question
- Option A
- Option B
- Option C
- Option D
- Correct option (A/B/C/D)

FORMAT STRICTLY LIKE THIS (NO EXTRA TEXT):

Q1. Question text
A. Option text
B. Option text
C. Option text
D. Option text
Correct: A

CONTENT:
{text[:12000]}
"""

    try:
        # ✅ USE AVAILABLE MODEL
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        response = model.generate_content(prompt)

        ai_text = response.text.strip()

        if not ai_text:
            raise Exception("Empty response from AI")

    except Exception as e:
        return jsonify({
            "error": f"AI generation failed: {str(e)}"
        }), 500

    cur.close()
    conn.close()

    return jsonify({
        "questions": ai_text
    })



# ---------------- EDIT EXAM ----------------
@app.route('/edit_exam/<int:exam_id>', methods=['GET', 'POST'])
@login_required(role='admin')
def edit_exam(exam_id):
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT * FROM exams
        WHERE id=%s AND manager_id=%s
    """, (exam_id, user['manager_id']))
    exam = cur.fetchone()

    if not exam:
        cur.close()
        conn.close()
        flash("Exam not found or unauthorized", "error")
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        start_time = request.form.get('start_time') or None
        end_time = request.form.get('end_time') or None
        duration = request.form.get('duration_minutes')

        cur.execute("""
            UPDATE exams
            SET title=%s,
                start_time=%s,
                end_time=%s,
                duration_minutes=%s
            WHERE id=%s AND manager_id=%s
        """, (
            title,
            start_time,
            end_time,
            duration,
            exam_id,
            user['manager_id']
        ))

        conn.commit()
        cur.close()
        conn.close()

        flash("Exam updated successfully", "success")
        return redirect(url_for('admin_dashboard'))

    cur.close()
    conn.close()
    return render_template('edit_exam.html', exam=exam)


# ---------------- DELETE EXAM ----------------
@app.route('/delete_exam/<int:exam_id>', methods=['POST'])
@login_required(role='admin')
def delete_exam(exam_id):
    user = session['user']

    conn = get_db_conn()
    cur = conn.cursor()

    # Ensure exam belongs to this admin
    cur.execute("""
        DELETE FROM exams
        WHERE id = %s AND manager_id = %s
    """, (exam_id, user['manager_id']))

    conn.commit()
    cur.close()
    conn.close()

    flash("Exam deleted successfully", "success")
    return redirect(url_for('admin_dashboard'))

# ---------------- STUDENT DASHBOARD ----------------
@app.route('/student')
@login_required(role='student')
def student_dashboard():
    user = session['user']

    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # ---------------- FETCH EXAMS ----------------
    cur.execute(
        "SELECT * FROM exams WHERE manager_id=%s",
        (user['manager_id'],)
    )
    exams = cur.fetchall()

    # ---------------- EXAM AVAILABILITY LOGIC ----------------
    from datetime import datetime
    now = datetime.now()

    for exam in exams:
        exam['can_attempt'] = True
        exam['status'] = "Available"

        # Exam not started yet
        if exam.get('start_time') and now < exam['start_time']:
            exam['can_attempt'] = False
            exam['status'] = exam['start_time'].strftime(
                "Starts %d %b %Y %I:%M %p"
            )

        # Exam expired
        if exam.get('end_time') and now > exam['end_time']:
            exam['can_attempt'] = False
            exam['status'] = "Expired"

        # Already attempted
        cur.execute("""
            SELECT 1 FROM results
            WHERE student=%s AND exam=%s
        """, (user['username'], exam['title']))

        if cur.fetchone():
            exam['can_attempt'] = False
            exam['status'] = "Attempted"

    # ---------------- FETCH STUDENT RESULTS ----------------
    cur.execute(
        "SELECT * FROM results WHERE student=%s",
        (user['username'],)
    )
    results = cur.fetchall()

    # ---------------- FETCH ADMIN NAME ----------------
    cur.execute(
        "SELECT username FROM users WHERE role='admin' AND manager_id=%s",
        (user['manager_id'],)
    )
    admin = cur.fetchone()

    cur.close()
    conn.close()

    admin_username = admin['username'] if admin else "Unknown"

    return render_template(
        'student_dashboard.html',
        exams=exams,
        results=results,
        admin_username=admin_username
    )



# ---------------- TAKE EXAM ----------------
# ---------------- TAKE EXAM ----------------
@app.route('/take_exam/<int:exam_id>', methods=['GET', 'POST'])
@login_required(role='student')
def take_exam(exam_id):
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Fetch exam
    cur.execute("SELECT * FROM exams WHERE id=%s", (exam_id,))
    exam = cur.fetchone()

    # Prevent re-attempt
    cur.execute("""
        SELECT 1 FROM results
        WHERE student=%s AND exam=%s
    """, (user['username'], exam['title']))
    if cur.fetchone():
        cur.close()
        conn.close()
        flash("You already attempted this exam", "error")
        return redirect(url_for('student_dashboard'))

    # Fetch questions
    cur.execute("""
        SELECT * FROM questions
        WHERE exam_id=%s
        ORDER BY id
    """, (exam_id,))
    questions = cur.fetchall()

    if request.method == 'POST':
        score = 0

        for q in questions:
            selected = request.form.get(str(q['id']))

            if not selected:
                continue

            correct_answer = q[q['correct']]

            if selected == correct_answer:
                score += 1

            # ✅ SAVE EACH ANSWER
            cur.execute("""
                INSERT INTO student_answers
                (student, exam_id, question_id, selected_option)
                VALUES (%s, %s, %s, %s)
            """, (
                user['username'],
                exam_id,
                q['id'],
                selected
            ))

        # Save final result
        cur.execute("""
            INSERT INTO results (student, exam, score, manager_id)
            VALUES (%s, %s, %s, %s)
        """, (
            user['username'],
            exam['title'],
            score,
            user['manager_id']
        ))

        conn.commit()
        cur.close()
        conn.close()

        return redirect(url_for('view_exam_result', exam_id=exam_id))

    cur.close()
    conn.close()
    return render_template(
        "take_exam.html",
        exam=exam,
        questions=questions
    )

@app.route('/view_result/<int:exam_id>')
@login_required(role='student')
def view_exam_result(exam_id):
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Fetch exam
    cur.execute("SELECT * FROM exams WHERE id=%s", (exam_id,))
    exam = cur.fetchone()

    # Fetch questions + student answers
    cur.execute("""
        SELECT q.question, q.option1, q.option2, q.option3, q.option4,
               q.correct, sa.selected_option
        FROM questions q
        JOIN student_answers sa
            ON q.id = sa.question_id
        WHERE sa.student=%s AND sa.exam_id=%s
        ORDER BY q.id
    """, (user['username'], exam_id))

    questions = cur.fetchall()

    cur.close()
    conn.close()

    return render_template(
        "view_exam_result.html",
        exam=exam,
        questions=questions
    )



# ---------------- RESULT ----------------
@app.route('/result')
@login_required()
def result():
    user = session['user']
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM results WHERE student=%s", (user['username'],))
    results = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('result.html', results=results)

# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.pop('user', None)
    flash("Logged out", "success")
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(debug=True)
