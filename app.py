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

# --- Telegram & Database Credentials ---
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"
OWNER_TELEGRAM_ID = "7982692248"

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://singhritesh194_db_user:0j802ayQz30qJqX@cluster0.p83irh9.mongodb.net/?appName=Cluster0")
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client["swiguru_quiz_db"]
quizzes_collection = db["quizzes"]
scores_collection = db["quiz_scores"]

quiz_lock = threading.Lock()
active_quiz_running = False
stop_requested = False
current_active_quiz_id = None

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

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    global stop_requested
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return "OK", 200

        # Handle Commands (/stop, /score, /leaderboard)
        if "message" in data:
            msg = data["message"]
            text = msg.get("text", "").strip().lower()
            chat_id = str(msg["chat"]["id"])
            
            if text.startswith("/stop"):
                stop_requested = True
                send_message(chat_id, "🛑 *Quiz roki ja rahi hai... Kripya intezaar karein.*")
            
            elif text.startswith("/score") or text.startswith("/leaderboard"):
                send_leaderboard(chat_id)

        # Handle Live Poll Answers
        elif "poll_answer" in data:
            answer = data["poll_answer"]
            poll_id = str(answer.get("poll_id"))
            user = answer.get("user", {})
            user_id = str(user.get("id"))
            user_name = user.get("first_name", "User")
            if user.get("last_name"):
                user_name += f" {user.get('last_name')}"
            
            option_ids = answer.get("option_ids", [])
            if option_ids:
                selected_opt = option_ids[0]
                doc = scores_collection.find_one({"poll_id": poll_id})
                if doc:
                    correct_opt = doc.get("correct_opt")
                    is_correct = (selected_opt == correct_opt)
                    
                    scores_collection.update_one(
                        {"user_id": user_id, "quiz_id": doc.get("quiz_id")},
                        {
                            "$set": {"user_name": user_name},
                            "$inc": {
                                "correct": 1 if is_correct else 0,
                                "incorrect": 0 if is_correct else 1,
                                "score": 1.0 if is_correct else -0.33
                            }
                        },
                        upsert=True
                    )
    except Exception as e:
        print(f"Webhook Exception: {e}")
    return "OK", 200

@app.route('/upload-quiz', methods=['POST'])
def upload_quiz():
    try:
        admin_id = request.form.get('admin_id', '').strip()
        quiz_title = request.form.get('quiz_title', 'Untitled Quiz').strip()
        
        if admin_id != OWNER_TELEGRAM_ID:
            return "<h3>❌ Error: Telegram User ID galat hai!</h3>"

        file = request.files.get('file')
        if not file or file.filename == '':
            return "<h3>❌ Error: File select nahi ki gayi!</h3>"

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
    global active_quiz_running, stop_requested, current_active_quiz_id
    doc = quizzes_collection.find_one({"_id": quiz_id})
    if not doc:
        return "<h3>❌ Quiz nahi mili!</h3>"
        
    target_group = request.form.get('group_id', '').strip()
    timer_val = request.form.get('timer', '35')
    timer = int(timer_val) if timer_val.isdigit() else 35
    
    if not target_group:
        return "<h3>❌ Telegram Group Username dalein!</h3>"
        
    questions = doc.get('questions', [])
    if not questions:
        return "<h3>❌ Is quiz me sawal nahi hain!</h3>"

    if active_quiz_running:
        return "<h3>⚠️ Ek quiz chal rahi hai! Kripya /stop karein ya intezaar karein.</h3>"

    stop_requested = False
    current_active_quiz_id = quiz_id
    scores_collection.delete_many({"quiz_id": quiz_id})

    thread = threading.Thread(target=run_live_quiz, args=(target_group, questions, timer, quiz_id))
    thread.daemon = True
    thread.start()

    return f"<h2>🎉 Live Quiz Shuru! Total {len(questions)} sawal '{target_group}' me bheje ja rahe hain. Stop karne ke liye /stop aur score dekhne ke liye /score type karein.</h2>"

def run_live_quiz(chat_id, questions, timer, quiz_id):
    global active_quiz_running, stop_requested
    with quiz_lock:
        active_quiz_running = True
        try:
            total_q = len(questions)
            for index, q in enumerate(questions):
                if stop_requested:
                    send_message(chat_id, "🛑 *Quiz roak di gayi hai!*")
                    break

                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
                opts = q.get('options', [])
                if len(opts) < 2:
                    continue
                
                q_text = q['question']
                prefix = f"Q{index+1}/{total_q}: "
                max_len = 300 - len(prefix)
                formatted_q = prefix + (q_text[:max_len] if len(q_text) > max_len else q_text)
                    
                poll_payload = {
                    "chat_id": chat_id,
                    "question": formatted_q,
                    "options": json.dumps(opts),
                    "type": "quiz",
                    "correct_option_id": int(q['correct']),
                    "is_anonymous": False
                }
                
                if timer > 0:
                    poll_payload["open_period"] = timer

                try:
                    res = requests.post(url, data=poll_payload, timeout=10)
                    if res.status_code == 200:
                        res_data = res.json()
                        if "result" in res_data and "poll" in res_data["result"]:
                            p_id = str(res_data["result"]["poll"]["id"])
                            scores_collection.insert_one({
                                "poll_id": p_id,
                                "quiz_id": quiz_id,
                                "correct_opt": int(q['correct'])
                            })
                    else:
                        print(f"Telegram Poll Error: {res.text}")
                except Exception as e:
                    print(f"Error sending poll: {e}")

                wait_time = (timer if timer > 0 else 35) + 2
                for _ in range(wait_time):
                    if stop_requested:
                        break
                    time.sleep(1)

                if stop_requested:
                    send_message(chat_id, "🛑 *Quiz roak di gayi hai!*")
                    break

                if (index + 1) % 10 == 0 and (index + 1) < total_q:
                    score_msg = f"📊 *Scoreboard / Progress Update*\n-----------------------------------\n👉 Abhi tak *{index + 1}* sawal poore ho chuke hain (Kul {total_q} me se).\n💡 Score ke liye */score* bhejein."
                    send_message(chat_id, score_msg)
                    time.sleep(3)

            if not stop_requested:
                send_message(chat_id, f"🏆 *Quiz Samapt Hui!* Sabhi {total_q} sawal poore ho chuke hain.")
                time.sleep(2)
                send_leaderboard(chat_id)
        finally:
            active_quiz_running = False
            stop_requested = False

def send_leaderboard(chat_id):
    global current_active_quiz_id
    if not current_active_quiz_id:
        send_message(chat_id, "⚠️ Abhi koi active quiz record nahi hai!")
        return

    top_users = list(scores_collection.find({"quiz_id": current_active_quiz_id, "score": {"$exists": True}}).sort("score", -1).limit(10))
    if not top_users:
        send_message(chat_id, "📊 Abhi tak kisi bhi sadasya ne uttar nahi diya hai!")
        return

    text = "🏆 *QUIZ LEADERBOARD (Negative Marking: -0.33)*\n-----------------------------------\n"
    for rank, user in enumerate(top_users, 1):
        name = user.get("user_name", "User")
        score = user.get("score", 0.0)
        correct = user.get("correct", 0)
        incorrect = user.get("incorrect", 0)
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
        text += f"{medal} *{name}* — Score: *{score:.2f}* (✅ {correct} | ❌ {incorrect})\n"

    send_message(chat_id, text)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Send message error: {e}")

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