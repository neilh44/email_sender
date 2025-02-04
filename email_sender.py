import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import logging
from datetime import datetime

# Set up logging
logging.basicConfig(
    filename=f'email_sender_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class EmailSender:
    def __init__(self, sender_email, sender_name, app_password, delay=5):
        self.sender_email = sender_email
        self.sender_name = sender_name
        self.app_password = app_password
        self.delay = delay
        self.server = None
        self.should_stop = False

    def stop_sending(self):
        self.should_stop = True
        logging.info("Stop signal received")

    def connect_to_smtp(self):
        try:
            self.server = smtplib.SMTP('smtp.gmail.com', 587)
            self.server.starttls()
            self.server.login(self.sender_email, self.app_password)
            logging.info("Successfully connected to SMTP server")
            return True
        except Exception as e:
            logging.error(f"Failed to connect to SMTP server: {str(e)}")
            raise

    def close_connection(self):
        if self.server:
            self.server.quit()
            logging.info("SMTP connection closed")

    def create_email_message(self, recipient_email, company_name, subject, body):
        msg = MIMEMultipart()
        msg['From'] = formataddr((self.sender_name, self.sender_email))
        msg['To'] = formataddr((company_name, recipient_email))
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        return msg

    def send_single_email(self, company_data):
        try:
            if self.should_stop:
                return {
                    'status': 'stopped',
                    'company': company_data.get('company_name', 'Unknown'),
                    'message': 'Email sending was stopped'
                }

            recipient_email = company_data.get('contact_email')
            if not recipient_email:
                logging.error(f"No email found for company {company_data.get('company_name', 'Unknown')}")
                return {
                    'status': 'failed',
                    'company': company_data.get('company_name', 'Unknown'),
                    'error': 'No email address found'
                }

            company_name = company_data['company_name']
            email_template = company_data['analysis']['partnership_email']
            subject = email_template['subject']
            body = email_template['body'].replace("[Your Name]", self.sender_name)
            
            msg = self.create_email_message(recipient_email, company_name, subject, body)
            self.server.send_message(msg)
            
            logging.info(f"Email sent successfully to {company_name} <{recipient_email}>")
            
            return {
                'status': 'success',
                'company': company_name,
                'email': recipient_email
            }
            
        except Exception as e:
            error_msg = f"Failed to send email for company {company_data.get('company_name', 'Unknown')}: {str(e)}"
            logging.error(error_msg)
            return {
                'status': 'failed',
                'company': company_data.get('company_name', 'Unknown'),
                'error': str(e)
            }

    def process_companies(self, companies_data):
        results = {
            'successful': [],
            'failed': [],
            'stopped': False,
            'total': len(companies_data),
            'processed': 0
        }
        
        try:
            self.connect_to_smtp()
            
            for company in companies_data:
                if self.should_stop:
                    results['stopped'] = True
                    break

                result = self.send_single_email(company)
                results['processed'] += 1
                
                if result['status'] == 'success':
                    results['successful'].append(result)
                elif result['status'] == 'failed':
                    results['failed'].append(result)
                
                if not self.should_stop and self.delay > 0 and companies_data.index(company) < len(companies_data) - 1:
                    time.sleep(self.delay)
                    
        except Exception as e:
            logging.error(f"Error in email processing: {str(e)}")
            raise
        finally:
            self.close_connection()
            
        return results