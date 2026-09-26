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

        if "message" in data:
            msg = data["message"]
            text = msg.get("text", "").strip().lower()
            chat_id = str(msg["chat"]["id"])
            user_id = str(msg.get("from", {}).get("id", ""))
            
            if text.startswith("/start"):
                welcome_text = (
                    "👋 **ExamGuru Quiz Bot mein aapka swagat hai!**\n\n"
                    "🤖 Yeh bot Telegram groups mein shandar live quizzes chalane ke liye hai."
                )
                send_message(chat_id, welcome_text)

            elif text.startswith("/mystore"):
                # Yahan se storage/website link hatha diya gaya hai taaki kisi ko na dikhe
                store_text = "📂 **Quiz Store:** Sabhi quizzes surakshit roop se admin dashboard par stored hain."
                send_message(chat_id, store_text)

            elif text.startswith("/help"):
                help_text = (
                    "📖 **Sahayata Nirdesh:**\n"
                    "• /stop - Quiz rokne ke liye (Kewal Admin)\n"
                    "• /score - Live leaderboard dekhne ke liye"
                )
                send_message(chat_id, help_text)

            elif text.startswith("/stop"):
                if user_id != OWNER_TELEGRAM_ID:
                    send_message(chat_id, "⚠️ Aapke paas quiz rokne ki anumati nahi hai!")
                else:
                    stop_requested = True
                    send_message(chat_id, "🛑 Quiz ko roka ja raha hai...")
            
            elif text.startswith("/score") or text.startswith("/leaderboard"):
                send_leaderboard(chat_id)

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
            return "<h3>❌ Truti: Telegram User ID galat hai!</h3>"

        file = request.files.get('file')
        if not file or file.filename == '':
            return "<h3>❌ Truti: Koi file chayanit nahi hai!</h3>"

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
            return "<h3>❌ Truti: File se sawal nahi mil paye! Format janchen.</h3>"

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
        return f"<h3>⚠️ Truti: {str(e)}</h3>"

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
    
    input_admin_id = request.form.get('admin_id', '').strip()
    if input_admin_id != OWNER_TELEGRAM_ID:
        return """
        <div style="background: #ffebee; color: #c62828; padding: 25px; border-radius: 10px; font-family: sans-serif; text-align: center; margin: 40px auto; max-width: 500px; border: 2px solid #ef5350;">
            <h3>❌ Anumati Asvikrit</h3>
            <p>Kewal Bot Owner hi group mein quiz shuru kar sakta hai!</p>
            <a href="/" style="display: inline-block; margin-top: 15px; padding: 10px 20px; background: #c62828; color: white; text-decoration: none; border-radius: 5px;">Wapas Jayen</a>
        </div>
        """

    doc = quizzes_collection.find_one({"_id": quiz_id})
    if not doc:
        return "<h3>❌ Quiz nahi mili!</h3>"
        
    target_group = request.form.get('group_id', '').strip()
    timer_val = request.form.get('timer', '35')
    timer = int(timer_val) if timer_val.isdigit() else 35
    
    if not target_group:
        return "<h3>❌ Telegram Group Username darj karein!</h3>"
        
    questions = doc.get('questions', [])
    if not questions:
        return "<h3>❌ Is quiz mein koi sawal nahi hai!</h3>"

    if active_quiz_running:
        return "<h3>⚠️ Ek quiz pehle se chal rahi hai! Kripya /stop ka upyog karein.</h3>"

    stop_requested = False
    current_active_quiz_id = quiz_id
    scores_collection.delete_many({"quiz_id": quiz_id})

    thread = threading.Thread(target=run_live_quiz, args=(target_group, questions, timer, quiz_id))
    thread.daemon = True
    thread.start()

    return f"""
    <!DOCTYPE html>
    <html lang="hi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Quiz Status - ExamGuru</title>
        <style>
            body {{
                background-color: #121212;
                color: #ffffff;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .card {{
                background: #1e1e1e;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 8px 24px rgba(0,0,0,0.5);
                text-align: center;
                max-width: 450px;
                width: 90%;
                border: 1px solid #333;
            }}
            h2 {{
                color: #4caf50;
                font-size: 22px;
                margin-bottom: 15px;
            }}
            p {{
                color: #e0e0e0;
                font-size: 16px;
                line-height: 1.5;
                margin-bottom: 25px;
            }}
            .btn {{
                background-color: #4caf50;
                color: white;
                padding: 12px 25px;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                cursor: pointer;
                text-decoration: none;
                font-weight: bold;
                display: inline-block;
            }}
            .btn:hover {{
                background-color: #43a047;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>🎉 Live Quiz Shuru Ho Chuki Hai!</h2>
            <p>Kul <b>{len(questions)}</b> sawal aapke telegram group <b>'{target_group}'</b> mein bheje ja rahe hain.</p>
            <a href="/" class="btn">Wapas Home Page Par Jayen</a>
        </div>
    </body>
    </html>
    """

def run_live_quiz(chat_id, questions, timer, quiz_id):
    global active_quiz_running, stop_requested
    with quiz_lock:
        active_quiz_running = True
        try:
            total_q = len(questions)
            for index, q in enumerate(questions):
                if stop_requested:
                    send_message(chat_id, "🛑 *Quiz ko beech mein hi rok diya gaya hai!*")
                    break

                raw_opts = q.get('options', [])
                if len(raw_opts) < 2:
                    continue

                q_text = q['question']
                msg_content = f"<b>[Q.{index+1}/{total_q} / प्रश्न {index+1}/{total_q}]</b>\n\n<b>Question / सवाल:</b> {q_text}\n\n<b>Options / विकल्प:</b>\n"
                for i, opt in enumerate(raw_opts):
                    opt_label = chr(65 + i)
                    msg_content += f"<b>{opt_label})</b> {opt}\n"
                
                send_html_message(chat_id, msg_content)
                time.sleep(1)

                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
                poll_opts = ["A", "B", "C", "D"][:len(raw_opts)]
                
                poll_payload = {
                    "chat_id": chat_id,
                    "question": f"Q.{index+1}/{total_q}: Select correct option / सही विकल्प चुनें 👇",
                    "options": json.dumps(poll_opts),
                    "type": "quiz",
                    "correct_option_id": int(q['correct']),
                    "is_anonymous": False
                }
                
                if timer > 0:
                    poll_payload["open_period"] = timer

                sent_success = False
                for attempt in range(3):
                    if stop_requested:
                        break
                    try:
                        res = requests.post(url, data=poll_payload, timeout=10)
                        if res.status_code == 200:
                            sent_success = True
                            res_data = res.json()
                            if "result" in res_data and "poll" in res_data["result"]:
                                p_id = str(res_data["result"]["poll"]["id"])
                                scores_collection.insert_one({
                                    "poll_id": p_id,
                                    "quiz_id": quiz_id,
                                    "correct_opt": int(q['correct'])
                                })
                            break
                        else:
                            time.sleep(2)
                    except Exception:
                        time.sleep(2)

                wait_time = (timer if timer > 0 else 35) + 3
                for _ in range(wait_time):
                    if stop_requested:
                        break
                    time.sleep(1)

                if stop_requested:
                    send_message(chat_id, "🛑 *Quiz ko beech mein hi rok diya gaya hai!*")
                    break

                if (index + 1) % 10 == 0 and (index + 1) < total_q:
                    score_msg = f"📊 *Progress Report / प्रगति रिपोर्ट*\n-----------------------------------\n👉 Abhi tak *{index + 1}* sawal poore ho chuke hain.\n💡 Score ke liye group mein */score* bhejein."
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
        text += f"{medal} *{name}* — Score / स्कोर: *{score:.2f}* (✅ {correct} | ❌ {incorrect})\n"

    send_message(chat_id, text)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Send message error: {e}")

def send_html_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Send HTML message error: {e}")

def parse_text_regex(text):
    parsed = []
    raw_blocks = text.split('\n\n')
    if len(raw_blocks) <= 1:
        raw_blocks = [text]

    for block in raw_blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 5:
            continue
        
        _lines = lines[:-4]
        q_text = " ".join(_lines).strip()
        
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