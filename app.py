import json
import io
import requests
from flask import Flask, request, render_template
from pypdf import PdfReader

app = Flask(__name__)

# --- APNA BOTFATHER WALA TOKEN YAHAN DALEIN ---
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"

# --- APNA TELEGRAM USER ID YAHAN DALEIN (Security ke liye) ---
OWNER_TELEGRAM_ID = "7982692248"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start-quiz', methods=['POST'])
def start_quiz():
    try:
        admin_id = request.form.get('admin_id', '').strip()
        target_group = request.form.get('group_id', '').strip()
        timer = int(request.form.get('timer', 35))
        
        # Security Check
        if admin_id != OWNER_TELEGRAM_ID:
            return "<h2>❌ Access Denied: Aapka Telegram User ID galat hai!</h2>"

        if not target_group:
            return "<h2>❌ Error: Kripya Telegram Group Username dalein (jaise @group)!</h2>"

        file = request.files.get('file')
        if not file:
            return "<h2>❌ Error: Koi bhi file select nahi ki gayi hai!</h2>"

        file_bytes = file.read()
        file_name = file.filename.lower()
        
        questions = []
        
        # 1. JSON File Read
        if file_name.endswith('.json'):
            questions = json.loads(file_bytes.decode('utf-8'))
            
        # 2. PDF ya Text File Read (✅ auto-detect ke sath)
        elif file_name.endswith(('.txt', '.pdf')):
            if file_name.endswith('.pdf'):
                reader = PdfReader(io.BytesIO(file_bytes))
                text_content = "".join([page.extract_text() for page in reader.pages])
            else:
                text_content = file_bytes.decode('utf-8')
            
            questions = parse_text_with_tick(text_content)
            
        if not questions:
            return "<h2>❌ Error: File se sawal nahi mil paye! Format check karein (✅ check karein).</h2>"

        # Telegram Bot API ka use karke group me direct polls bhejna (No timeout error)
        success_count = 0
        for index, q in enumerate(questions):
            # Telegram sendPoll API URL
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
            
            payload = {
                "chat_id": target_group,
                "question": f"Q{index+1}: {q['question']}",
                "options": json.dumps(q['options']),
                "type": "quiz",
                "correct_option_id": q['correct'],
                "is_anonymous": False
            }
            
            if timer > 0:
                payload["open_period"] = timer

            response = requests.post(url, data=payload)
            if response.status_code == 200:
                success_count += 1

        return f"<h2>✅ Success! Total {success_count} Quiz Polls '{target_group}' group mein bhej diye gaye hain!</h2>"
        
    except Exception as e:
        return f"<h2>⚠️ Error aa gaya: {str(e)}</h2>"

def parse_text_with_tick(text):
    parsed_questions = []
    blocks = text.split("Q:")
    for block in blocks:
        if not block.strip():
            continue
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 5:
            continue
        
        q_text = lines[0]
        options = lines[1:5]
        correct_index = 0
        
        cleaned_options = []
        for i, opt in enumerate(options):
            if "✅" in opt:
                correct_index = i
                opt = opt.replace("✅", "").strip()
            cleaned_options.append(opt)
            
        parsed_questions.append({
            "question": q_text,
            "options": cleaned_options,
            "correct": correct_index
        })
    return parsed_questions

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)