from flask import Flask, request, jsonify, render_template
import os
from werkzeug.utils import secure_filename
from email_sender import EmailSender
import json
from dotenv import load_dotenv
import redis
import uuid
import threading
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Redis
REDIS_URL = os.getenv('REDIS_URL', 'redis://red-clfmvd6d2npc73dlsq60:6379')
redis_client = redis.from_url(REDIS_URL)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'json'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_emails_task(job_id, file_path, sender_email, sender_name, app_password, email_delay):
    try:
        # Update job status
        redis_client.hset(f"job:{job_id}", "status", "processing")
        
        # Initialize EmailSender
        sender = EmailSender(
            sender_email=sender_email,
            sender_name=sender_name,
            app_password=app_password,
            delay=email_delay
        )

        # Read JSON file
        with open(file_path, 'r') as f:
            companies_data = json.load(f)

        # Process emails
        results = sender.process_companies(companies_data)
        
        # Store results in Redis
        redis_client.hset(f"job:{job_id}", "status", "completed")
        redis_client.hset(f"job:{job_id}", "results", json.dumps(results))
        redis_client.expire(f"job:{job_id}", 86400)  # Expire after 24 hours

    except Exception as e:
        redis_client.hset(f"job:{job_id}", "status", "failed")
        redis_client.hset(f"job:{job_id}", "error", str(e))
        redis_client.expire(f"job:{job_id}", 86400)  # Expire after 24 hours
    finally:
        # Clean up
        if os.path.exists(file_path):
            os.remove(file_path)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/send-emails', methods=['POST'])
def send_emails():
    try:
        # Get form data
        sender_email = request.form.get('senderEmail')
        sender_name = request.form.get('senderName')
        app_password = request.form.get('appPassword')
        email_delay = int(request.form.get('emailDelay', 5))

        # Validate file
        if 'jsonFile' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['jsonFile']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload a JSON file'}), 400

        # Generate unique job ID and filename
        job_id = str(uuid.uuid4())
        unique_filename = f"{job_id}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Save file
        file.save(filepath)

        # Initialize job in Redis
        redis_client.hset(f"job:{job_id}", mapping={
            "status": "queued",
            "created_at": datetime.now().isoformat()
        })

        # Start processing in a thread
        thread = threading.Thread(
            target=process_emails_task,
            args=(job_id, filepath, sender_email, sender_name, app_password, email_delay)
        )
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'message': 'Email sending task has been started',
            'job_id': job_id
        })

    except Exception as e:
        # Clean up file in case of error
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/api/job-status/<job_id>')
def job_status(job_id):
    job_key = f"job:{job_id}"
    if not redis_client.exists(job_key):
        return jsonify({'error': 'Job not found'}), 404

    status = redis_client.hget(job_key, "status").decode('utf-8')
    response = {
        'id': job_id,
        'status': status
    }

    if status == 'completed':
        results = redis_client.hget(job_key, "results")
        response['result'] = json.loads(results.decode('utf-8'))
    elif status == 'failed':
        error = redis_client.hget(job_key, "error")
        response['error'] = error.decode('utf-8')

    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True)