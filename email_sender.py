from flask import Flask, request, jsonify, render_template
import os
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
import redis
import uuid
import threading
from datetime import datetime
from email_sender import EmailSender

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Redis
REDIS_URL = os.getenv('REDIS_URL', 'redis://red-clfmvd6d2npc73dlsq60:6379')
redis_client = redis.from_url(REDIS_URL)

# Store active email senders
active_senders = {}

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
        
        # Get the last processed index from Redis
        last_index_key = f"last_index:{job_id}"
        last_processed_index = int(redis_client.get(last_index_key) or 0)
        
        # Read JSON file
        with open(file_path, 'r') as f:
            companies_data = json.load(f)
            
        # Get existing results from Redis or initialize new ones
        results_key = f"results:{job_id}"
        existing_results = redis_client.get(results_key)
        
        if existing_results:
            results = json.loads(existing_results)
        else:
            results = {
                'successful': [],
                'failed': [],
                'stopped': False,
                'total': len(companies_data),
                'processed': last_processed_index
            }

        # Initialize EmailSender
        sender = EmailSender(
            sender_email=sender_email,
            sender_name=sender_name,
            app_password=app_password,
            delay=email_delay
        )
        
        # Store sender instance
        active_senders[job_id] = sender

        try:
            sender.connect_to_smtp()
            
            # Process remaining companies starting from last processed index
            for i in range(last_processed_index, len(companies_data)):
                if sender.should_stop:
                    results['stopped'] = True
                    break

                company = companies_data[i]
                result = sender.send_single_email(company)
                results['processed'] = i + 1
                
                if result['status'] == 'success':
                    results['successful'].append(result)
                elif result['status'] == 'failed':
                    results['failed'].append(result)
                
                # Save progress after each email
                redis_client.set(last_index_key, i)
                redis_client.set(results_key, json.dumps(results))
                
                if not sender.should_stop and i < len(companies_data) - 1:
                    sender.server.noop()  # Keep SMTP connection alive
                    time.sleep(email_delay)
                    
        finally:
            sender.close_connection()
            
        # Update final status
        final_status = "stopped" if sender.should_stop else "completed"
        redis_client.hset(f"job:{job_id}", "status", final_status)
        redis_client.hset(f"job:{job_id}", "results", json.dumps(results))
        
        # Set expiration for cleanup
        redis_client.expire(f"job:{job_id}", 86400)  # 24 hours
        redis_client.expire(last_index_key, 86400)
        redis_client.expire(results_key, 86400)

    except Exception as e:
        redis_client.hset(f"job:{job_id}", "status", "failed")
        redis_client.hset(f"job:{job_id}", "error", str(e))
        redis_client.expire(f"job:{job_id}", 86400)
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        active_senders.pop(job_id, None)

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
            return jsonify({'error': 'Invalid file type'}), 400

        # Generate job ID and save file
        job_id = str(uuid.uuid4())
        unique_filename = f"{job_id}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
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
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': str(e)}), 500

@app.route('/api/stop-job/<job_id>', methods=['POST'])
def stop_job(job_id):
    sender = active_senders.get(job_id)
    if sender:
        sender.stop_sending()
        return jsonify({
            'success': True,
            'message': 'Stop signal sent to job'
        })
    return jsonify({
        'error': 'Job not found or already completed'
    }), 404

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
    
    # Get current progress
    results_key = f"results:{job_id}"
    results = redis_client.get(results_key)
    if results:
        response['result'] = json.loads(results)
    elif status == 'failed':
        error = redis_client.hget(job_key, "error")
        if error:
            response['error'] = error.decode('utf-8')
            
    return jsonify(response)

if __name__ == '__main__':
    app.run(debug=True)