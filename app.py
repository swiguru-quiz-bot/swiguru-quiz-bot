import json
import io
from flask import Flask, request, render_template
from telegram import Bot
from pypdf import PdfReader

app = Flask(__name__)

# --- APNA BOTFATHER WALA TOKEN YAHAN DALEIN ---
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"

# --- APNA TELEGRAM USER ID YAHAN DALEIN (Security ke liye taaki sirf aap chala sakein) ---
# (Apna User ID nikalne ke liye Telegram par @userinfobot se baat kar sakte hain)
OWNER_TELEGRAM_ID = "7982692248"

bot = Bot(token=TELEGRAM_TOKEN)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/start-quiz', methods=['POST'])
def start_quiz():
    try:
        # Mini App se aane wala data
        admin_id = request.form.get('admin_id', '').strip()
        target_group = request.form.get('group_id', '').strip()
        timer = int(request.form.get('timer', 35))
        
        # 🔒 SECURITY CHECK: Agar koi aur chalaega toh bot mana kar dega
        if admin_id != OWNER_TELEGRAM_ID:
            return "<h2>❌ Access Denied: Aapke paas is bot ko chalane ki permission nahi hai!</h2>"

        file = request.files['file']
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

        # Jis group ka naam aapne Mini App mein dala hai, wahan quiz chali jayegi
        for index, q in enumerate(questions):
            bot.send_poll(
                chat_id=target_group,
                question=f"Q{index+1}: {q['question']}",
                options=q['options'],
                type='quiz',
                correct_option_id=q['correct'],
                open_period=timer if timer > 0 else None,
                is_anonymous=False
            )

        return f"<h2>✅ Success! Quiz '{target_group}' group mein bhej di gayi hai.</h2>"
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