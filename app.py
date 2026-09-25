import json
import io
import re
import time
import threading
import os
import requests
from flask import Flask, request, render_template, redirect, url_for
from pypdf import PdfReader

app = Flask(__name__)

# Yahan apna BotFather wala token aur apna Telegram User ID daalein
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"
OWNER_TELEGRAM_ID = "7982692248"

QUIZ_FILE_STORE = "quizzes.json"

def load_quizzes():
    if os.path.exists(QUIZ_FILE_STORE):
        try:
            with open(QUIZ_FILE_STORE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_quizzes(quizzes):
    with open(QUIZ_FILE_STORE, 'w', encoding='utf-8') as f:
        json.dump(quizzes, f, ensure_ascii=False, indent=4)

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
            return "<h3>❌ Error: File se sawal nahi mil paye! Format check karein (Q1:, ✅ zaroor ho).</h3>"

        quizzes = load_quizzes()
        quiz_id = str(int(time.time()))
        quizzes[quiz_id] = {
            "title": quiz_title,
            "questions": questions,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_quizzes(quizzes)
        
        return redirect(url_for('preview_quiz', quiz_id=quiz_id))
        
    except Exception as e:
        return f"<h3>⚠️ Error: {str(e)}</h3>"

@app.route('/preview/<quiz_id>')
def preview_quiz(quiz_id):
    quizzes = load_quizzes()
    if quiz_id not in quizzes:
        return "<h3>❌ Quiz nahi mili!</h3>"
    quiz = quizzes[quiz_id]
    return render_template('preview.html', quiz_id=quiz_id, quiz=quiz, owner_id=OWNER_TELEGRAM_ID)

@app.route('/update-question/<quiz_id>/<int:q_index>', methods=['POST'])
def update_question(quiz_id, q_index):
    quizzes = load_quizzes()
    if quiz_id in quizzes and 0 <= q_index < len(quizzes[quiz_id]['questions']):
        data = request.form
        quizzes[quiz_id]['questions'][q_index]['question'] = data.get('question')
        quizzes[quiz_id]['questions'][q_index]['options'] = [
            data.get('opt0'), data.get('opt1'), data.get('opt2'), data.get('opt3')
        ]
        quizzes[quiz_id]['questions'][q_index]['correct'] = int(data.get('correct'))
        save_quizzes(quizzes)
    return redirect(url_for('preview_quiz', quiz_id=quiz_id))

@app.route('/delete-question/<quiz_id>/<int:q_index>', methods=['POST'])
def delete_question(quiz_id, q_index):
    quizzes = load_quizzes()
    if quiz_id in quizzes and 0 <= q_index < len(quizzes[quiz_id]['questions']):
        quizzes[quiz_id]['questions'].pop(q_index)
        save_quizzes(quizzes)
    return redirect(url_for('preview_quiz', quiz_id=quiz_id))

@app.route('/play-group/<quiz_id>', methods=['POST'])
def play_group(quiz_id):
    quizzes = load_quizzes()
    if quiz_id not in quizzes:
        return "<h3>❌ Quiz nahi mili!</h3>"
        
    target_group = request.form.get('group_id', '').strip()
    timer_val = request.form.get('timer', '35')
    timer = int(timer_val) if timer_val.isdigit() else 35
    
    if not target_group:
        return "<h3>❌ Kripya Telegram Group Username dalein (jaise @Swiquiz)!</h3>"
        
    questions = quizzes[quiz_id]['questions']
    if not questions:
        return "<h3>❌ Is quiz me ek bhi sawal nahi hai!</h3>"

    thread = threading.Thread(target=run_live_quiz, args=(target_group, questions, timer))
    thread.daemon = True
    thread.start()

    return f"<h2>🎉 Live Quiz Shuru Ho Chuki Hai! Total {len(questions)} sawal '{target_group}' group me bheje ja rahe hain.</h2>"

def run_live_quiz(chat_id, questions, timer):
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

        try:
            res = requests.post(url, data=payload)
            if res.status_code == 200:
                wait_time = timer if timer > 0 else 30
                time.sleep(wait_time)
            else:
                time.sleep(2)
        except Exception as e:
            print(f"Error sending poll: {e}")

        if (index + 1) % 10 == 0:
            send_message(chat_id, f"📊 **Scoreboard / Progress Update**\n-----------------------------------\n👉 Abhi tak **{index + 1}** sawal poore ho chuke hain (Kul {total_q} me se).\n\nAgle 10 sawal shuru ho rahe hain!")

    send_message(chat_id, f"🏆 **Quiz Samapt Hui!** Sabhi {total_q} sawal poore ho chuke hain.")

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

def parse_text_regex(text):
    parsed = []
    raw_blocks = re.split(r'\n\s*(?=Q\d+[:\.])', text)
    if len(raw_blocks) <= 1:
        raw_blocks = [text]

    for block in raw_blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 5:
            continue
        q_line = lines[0]
        q_text = re.sub(r'^Q\d+[:\.]\s*', '', q_line).strip()
        options = lines[1:5]
        correct_idx = 0
        cleaned_opts = []
        for i, opt in enumerate(options):
            if "✅" in opt:
                correct_idx = i
                opt = opt.replace("✅", "").strip()
            cleaned_opts.append(opt)
            
        if len(cleaned_opts) >= 2:
            parsed.append({
                "question": q_text,
                "options": cleaned_opts,
                "correct": correct_idx
            })
    return parsed

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)