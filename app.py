import json
import io
import re
import time
import threading
import requests
from flask import Flask, request, render_template
from pypdf import PdfReader

app = Flask(__name__)

# --- Apna BotFather wala token aur Telegram User ID yahan daalein ---
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"
OWNER_TELEGRAM_ID = "7982692248"

@app.route('/')
def home():
    try:
        return render_template('index.html')
    except Exception as e:
        return f"HTML Page Load Error: {str(e)}"

@app.route('/start-quiz', methods=['POST'])
def start_quiz():
    try:
        admin_id = request.form.get('admin_id', '').strip()
        target_group = request.form.get('group_id', '').strip()
        timer_val = request.form.get('timer', '35')
        timer = int(timer_val) if timer_val.isdigit() else 35
        
        if admin_id != OWNER_TELEGRAM_ID:
            return "<h3>❌ Error: Aapka Telegram User ID galat hai!</h3>"

        if not target_group:
            return "<h3>❌ Error: Kripya Telegram Group Username dalein!</h3>"

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

        # Background thread start karenge taaki web request timeout na ho aur live quiz chale
        thread = threading.Thread(target=run_live_quiz, args=(target_group, questions, timer))
        thread.daemon = True
        thread.start()

        return f"<h2>🎉 Live Quiz Shuru Ho Chuki Hai! Total {len(questions)} sawal hain. Bot ek-ek karke group me bhej raha hai aur har 10 sawal par scoreboard aayega.</h2>"
        
    except Exception as e:
        return f"<h3>⚠️ Server Error: {str(e)}</h3>"

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
                # Timer jitna set hai utna wait karenge taaki log vote kar sakein
                wait_time = timer if timer > 0 else 30
                time.sleep(wait_time)
            else:
                time.sleep(2)
        except Exception as e:
            print(f"Error sending poll: {e}")

        # Har 10 sawal ke baad scoreboard message bhejna
        if (index + 1) % 10 == 0:
            send_scoreboard_message(chat_id, index + 1, total_q)

    # Quiz khatam hone par final message
    send_message(chat_id, f"🏆 **Quiz Samapt Hui!** Sabhi 110 sawal poore ho chuke hain.")

def send_scoreboard_message(chat_id, current_q, total_q):
    msg = f"📊 **Scoreboard / Progress Update**\n-----------------------------------\n👉 Abhi tak **{current_q}** sawal poore ho chuke hain (Kul {total_q} me se).\n\nAgલે 10 sawal shuru ho rahe hain, taiyar rahiye!"
    send_message(chat_id, msg)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
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