from flask import Flask, request, jsonify, render_template
import os
from werkzeug.utils import secure_filename
from email_sender import EmailSender
import json
from dotenv import load_dotenv
from rq import Queue
from redis import Redis
import uuid

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Redis
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
redis_conn = Redis.from_url(redis_url)
q = Queue('email_tasks', connection=redis_conn)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'json'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_emails(file_path, sender_email, sender_name, app_password, email_delay):
    try:
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

        # Clean up
        if os.path.exists(file_path):
            os.remove(file_path)

        return results
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise e

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

        # Generate unique filename
        unique_filename = f"{str(uuid.uuid4())}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Save file
        file.save(filepath)

        # Queue the task
        job = q.enqueue(
            process_emails,
            args=(
                filepath,
                sender_email,
                sender_name,
                app_password,
                email_delay
            ),
            job_timeout='30m'  # 30 minutes timeout
        )

        return jsonify({
            'success': True,
            'message': 'Email sending task has been queued',
            'job_id': job.id
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
    job = q.fetch_job(job_id)
    
    if job is None:
        return jsonify({'error': 'Job not found'}), 404

    status = {
        'id': job.id,
        'status': job.get_status(),
        'result': job.result if job.is_finished else None,
        'error': str(job.exc_info) if job.is_failed else None
    }
    
    return jsonify(status)

if __name__ == '__main__':
    app.run(debug=True)