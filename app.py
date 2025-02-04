from flask import Flask, request, jsonify, render_template
import os
from werkzeug.utils import secure_filename
from email_sender import EmailSender
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'json'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

        # Check if file was uploaded
        if 'jsonFile' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['jsonFile']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Please upload a JSON file'}), 400

        # Save the file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Initialize EmailSender with provided credentials
        sender = EmailSender(
            sender_email=sender_email,
            sender_name=sender_name,
            app_password=app_password,
            delay=email_delay
        )

        # Process the JSON file
        with open(filepath, 'r') as f:
            companies_data = json.load(f)

        # Start sending emails
        results = sender.process_companies(companies_data)

        # Clean up - remove uploaded file
        os.remove(filepath)

        return jsonify({
            'success': True,
            'message': 'Emails sent successfully',
            'results': results
        })

    except Exception as e:
        return jsonify({
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True)