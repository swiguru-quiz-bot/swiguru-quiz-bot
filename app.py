import json
import io
import re
import time
import threading
import os
import requests
from flask import Flask, request, render_template, redirect, url_for
from pypdf import PdfReader
from pymongo import MongoClient

app = Flask(__name__)

# --- अपनी डिटेल्स यहाँ भरें ---
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"
OWNER_TELEGRAM_ID = "7982692248"

# MongoDB Connection (Safe Lazy Initialization with timeout)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://singhritesh194_db_user:0j802ayQz30qJqX@cluster0.p83irh9.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["swiguru_quiz_db"]
quizzes_collection = db["quizzes"]

# Lock variable taaki ek sath multiple quizzes run na ho sakein aur skip hone ki problem na aaye
quiz_lock = threading.Lock()
active_quiz_running = False

def load_quizzes():
    try:
        quizzes = {}
        for doc in quizzes_collection.find():
            q_id = str(doc["_id"])
            quizzes[q_id] = {
                "title": doc.get("title", "Untitled"),
                "questions": doc.get("questions", []),
                "created_at": doc.get("created_at", "")
            }
        return quizzes
    except Exception as e:
        print(f"DB Load Error: {e}")
        return {}

@app.route('/')
def home():
    quizzes = load_quizzes()
    return render_template('index.html', quizzes=quizzes, owner_id=OWNER_TELEGRAM_ID)

@app.route('/upload-quiz', methods=['POST'])
def upload_quiz():
    try:
        admin_id = request.form.get('admin_id', '').strip()
        quiz_title = request.form.get('quiz_title', 'Untitled Quiz').strip()
        
        if admin_id != OWNER_TELEGRAM_ID:
            return "<h3>❌ Error: Aapka Telegram User ID galat hai!</h3>"

        file = request.files.get('file')
        if not file or file.filename == '':
            return "<h3>❌ Error: Koi bhi file select nahi ki gayi hai!</h3>"

        file_bytes = file.read()
        file_name = file.filename.lower()
        
        questions = []
        if file_name.endswith('.json'):
            questions = json.loads(file_bytes.decode('utf-8'))
        elif file_name.endswith(('.txt', '.pdf')):
            if file_name.endswith('.pdf'):
                reader = PdfReader(io.BytesIO(file_bytes))
                text_content = "".join([page.extract_text() for page in reader.pages])
            else:
                text_content = file_bytes.decode('utf-8')
            questions = parse_text_regex(text_content)
            
        if not questions:
            return "<h3>❌ Error: File se sawal nahi mil paye! Format check karein.</h3>"

        quiz_id = str(int(time.time()))
        quiz_data = {
            "_id": quiz_id,
            "title": quiz_title,
            "questions": questions,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        quizzes_collection.insert_one(quiz_data)
        
        return redirect(url_for('preview_quiz', quiz_id=quiz_id))
        
    except Exception as e:
        return f"<h3>⚠️ Error: {str(e)}</h3>"

@app.route('/preview/<quiz_id>')
def preview_quiz(quiz_id):
    doc = quizzes_collection.find_one({"_id": quiz_id})
    if not doc:
        return "<h3>❌ Quiz nahi mili!</h3>"
    quiz = {
        "title": doc.get("title"),
        "questions": doc.get("questions"),
        "created_at": doc.get("created_at")
    }
    return render_template('preview.html', quiz_id=quiz_id, quiz=quiz, owner_id=OWNER_TELEGRAM_ID)

@app.route('/update-question/<quiz_id>/<int:q_index>', methods=['POST'])
def update_question(quiz_id, q_index):
    doc = quizzes_collection.find_one({"_id": quiz_id})
    if doc:
        questions = doc.get("questions", [])
        if 0 <= q_index < len(questions):
            data = request.form
            questions[q_index]['question'] = data.get('question')
            questions[q_index]['options'] = [
                data.get('opt0'), data.get('opt1'), data.get('opt2'), data.get('opt3')
            ]
            questions[q_index]['correct'] = int(data.get('correct'))
            quizzes_collection.update_one({"_id": quiz_id}, {"$set": {"questions": questions}})
    return redirect(url_for('preview_quiz', quiz_id=quiz_id))

@app.route('/add-question/<quiz_id>', methods=['POST'])
def add_question(quiz_id):
    doc = quizzes_collection.find_one({"_id": quiz_id})
    if doc:
        questions = doc.get("questions", [])
        data = request.form
        new_q = {
            "question": data.get('question'),
            "options": [data.get('opt0'), data.get('opt1'), data.get('opt2'), data.get('opt3')],
            "correct": int(data.get('correct'))
        }
        questions.append(new_q)
        quizzes_collection.update_one({"_id": quiz_id}, {"$set": {"questions": questions}})
    return redirect(url_for('preview_quiz', quiz_id=quiz_id))

@app.route('/delete-question/<quiz_id>/<int:q_index>', methods=['POST'])
def delete_question(quiz_id, q_index):
    doc = quizzes_collection.find_one({"_id": quiz_id})
    if doc:
        questions = doc.get("questions", [])
        if 0 <= q_index < len(questions):
            questions.pop(q_index)
            quizzes_collection.update_one({"_id": quiz_id}, {"$set": {"questions": questions}})
    return redirect(url_for('preview_quiz', quiz_id=quiz_id))

@app.route('/delete-quiz/<quiz_id>', methods=['POST'])
def delete_quiz(quiz_id):
    quizzes_collection.delete_one({"_id": quiz_id})
    return redirect(url_for('home'))

@app.route('/play-group/<quiz_id>', methods=['POST'])
def play_group(quiz_id):
    global active_quiz_running
    doc = quizzes_collection.find_one({"_id": quiz_id})
    if not doc:
        return "<h3>❌ Quiz nahi mili!</h3>"
        
    target_group = request.form.get('group_id', '').strip()
    timer_val = request.form.get('timer', '35')
    timer = int(timer_val) if timer_val.isdigit() else 35
    
    if not target_group:
        return "<h3>❌ Kripya Telegram Group Username dalein!</h3>"
        
    questions = doc.get('questions', [])
    if not questions:
        return "<h3>❌ Is quiz me ek bhi sawal nahi hai!</h3>"

    if active_quiz_running:
        return "<h3>⚠️ Ek quiz pehle se chal rahi hai! Kripya uske samapt hone ka intezaar karein.</h3>"

    thread = threading.Thread(target=run_live_quiz, args=(target_group, questions, timer))
    thread.daemon = True
    thread.start()

    return f"<h2>🎉 Live Quiz Shuru Ho Chuki Hai! Total {len(questions)} sawal '{target_group}' group me ek-ek karke bheje ja rahe hain.</h2>"

def run_live_quiz(chat_id, questions, timer):
    global active_quiz_running
    with quiz_lock:
        active_quiz_running = True
        try:
            total_q = len(questions)
            for index, q in enumerate(questions):
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
                opts = q.get('options', [])
                if len(opts) < 2:
                    continue
                    
                payload = {
                    "chat_id": chat_id,
                    "question": f"Q{index+1}/{total_q}: {q['question']}",
                    "options": json.dumps(opts),
                    "type": "quiz",
                    "correct_option_id": int(q['correct']),
                    "is_anonymous": False
                }
                
                if timer > 0:
                    payload["open_period"] = timer

                success = False
                for attempt in range(3): # Agar network error ho toh 3 baar try karega
                    try:
                        res = requests.post(url, data=payload, timeout=10)
                        if res.status_code == 200:
                            success = True
                            break
                        else:
                            time.sleep(2)
                    except Exception:
                        time.sleep(2)

                # Timer jitna set hai, utni der exact rukna taaki koi sawal skip na ho
                wait_time = (timer if timer > 0 else 35) + 2
                time.sleep(wait_time)

                if (index + 1) % 10 == 0 and (index + 1) < total_q:
                    score_msg = f"📊 *Scoreboard / Progress Update*\n-----------------------------------\n👉 Abhi tak *{index + 1}* sawal poore ho chuke hain (Kul {total_q} me se).\n\nAgle 10 sawal shuru ho rahe hain!"
                    send_message(chat_id, score_msg)
                    time.sleep(4)

            send_message(chat_id, f"🏆 *Quiz Samapt Hui!* Sabhi {total_q} sawal poore ho chuke hain.")
        finally:
            active_quiz_running = False

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Error message error: {e}")

def parse_text_regex(text):
    parsed = []
    raw_blocks = text.split('\n\n')
    if len(raw_blocks) <= 1:
        raw_blocks = [text]

    for block in raw_blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 5:
            continue
        
        q_lines = lines[:-4]
        q_text = " ".join(q_lines).strip()
        
        options = lines[-4:]
        correct_idx = 0
        cleaned_opts = []
        
        for i, opt in enumerate(options):
            if "✅" in opt or "✔" in opt:
                correct_idx = i
                opt = opt.replace("✅", "").replace("✔", "").strip()
            cleaned_opts.append(opt)
            
        if len(cleaned_opts) >= 2:
            parsed.append({
                "question": q_text,
                "options": cleaned_opts,
                "correct": correct_idx
            })
    return parsed

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)