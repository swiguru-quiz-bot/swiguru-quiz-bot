import json
import io
import requests
from flask import Flask, request, render_template
from pypdf import PdfReader

app = Flask(__name__)

# --- APNA BOTFATHER WALA TOKEN YAHAN DALEIN ---
TELEGRAM_TOKEN = "8823022165:AAFo6Dq592mRSVP0-MNU646DdrKgprGMXF8"

# --- APNA TELEGRAM USER ID YAHAN DALEIN ---
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
        
        # 1. Check Owner ID
        if admin_id != OWNER_TELEGRAM_ID:
            return "<h2>❌ Error: Aapka Telegram User ID galat dala hai! Sahi ID dalein.</h2>"

        if not target_group:
            return "<h2>❌ Error: Kripya Telegram Group Username dalein (jaise @yourgroup)!</h2>"

        file = request.files.get('file')
        if not file or file.filename == '':
            return "<h2>❌ Error: Aapne koi bhi file select nahi ki hai!</h2>"

        file_bytes = file.read()
        file_name = file.filename.lower()
        
        questions = []
        
        # 2. Read JSON or Text/PDF
        if file_name.endswith('.json'):
            questions = json.loads(file_bytes.decode('utf-8'))
        elif file_name.endswith(('.txt', '.pdf')):
            if file_name.endswith('.pdf'):
                reader = PdfReader(io.BytesIO(file_bytes))
                text_content = "".join([page.extract_text() for page in reader.pages])
            else:
                text_content = file_bytes.decode('utf-8')
            
            questions = parse_text_smart(text_content)
            
        if not questions:
            return "<h2>❌ Error: File se ek bhi sawal nahi padh paye! Check karein ki sawal 'Q:' se shuru ho aur sahi jawab ke aage '✅' laga ho.</h2>"

        # 3. Send Polls to Telegram Group
        sent_count = 0
        failed_msgs = []
        
        for index, q in enumerate(questions):
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPoll"
            
            # Options ko ensure karna ki list hi ho
            opts = q.get('options', [])
            if len(opts) < 2:
                continue
                
            payload = {
                "chat_id": target_group,
                "question": f"Q{index+1}: {q['question']}",
                "options": json.dumps(opts),
                "type": "quiz",
                "correct_option_id": int(q['correct']),
                "is_anonymous": False
            }
            
            if timer > 0:
                payload["open_period"] = timer

            res = requests.post(url, data=payload)
            if res.status_code == 200:
                sent_count += 1
            else:
                failed_msgs.append(res.text)

        if sent_count > 0:
            return f"<h2>🎉 Badhai ho! Total {sent_count} Quiz Polls safaltapoorvak '{target_group}' group mein bhej diye gaye hain!</h2>"
        else:
            return f"<h2>⚠️ Telegram ne poll bhejne se mana kar diya. Wajah: {failed_msgs} (Check karein ki bot group mein Admin hai ya nahi!)</h2>"
            
    except Exception as e:
        return f"<h2>⚠️ Ek technical error aa gaya: {str(e)}</h2>"

def parse_text_smart(text):
    parsed = []
    blocks = text.split("Q:")
    for block in blocks:
        if not block.strip():
            continue
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 5:
            continue
        
        q_text = lines[0]
        options = lines[1:5]
        correct_idx = 0
        
        cleaned_opts = []
        for i, opt in enumerate(options):
            if "✅" in opt:
                correct_idx = i
                opt = opt.replace("✅", "").strip()
            cleaned_opts.append(opt)
            
        parsed.append({
            "question": q_text,
            "options": cleaned_opts,
            "correct": correct_idx
        })
    return parsed