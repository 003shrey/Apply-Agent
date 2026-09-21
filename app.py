# app.py
import os
import sys
import uuid
import json

# Apply flat-import convention to keep the frontend consistent with tests/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from flask import Flask, render_template, request, redirect, url_for, session, flash
import db
import tailor
import profile_manager
import email_gen
import emailer
import batch_email
import form_filler

app = Flask(__name__)
# Load secrets from environment only
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")

# Global dict to bypass Flask's 4KB signed cookie limit for large resume/JD/draft data.
# This is safe for a local/personal tool and avoids the need for external session stores.
TRANSIENT_STATE = {
    'tailor': {},
    'profile': {},
    'drafts': {}
}

def get_session_id():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    return session['session_id']

@app.route('/')
def dashboard():
    status_filter = request.args.get('status')
    apps = db.list_applications(status_filter)
    return render_template('dashboard.html', applications=apps)

@app.route('/tailor', methods=['GET', 'POST'])
def tailor_route():
    if request.method == 'POST':
        jd_text = request.form['jd_text']
        company = request.form['company']
        role = request.form['role']
        
        resume_json = profile_manager.load_profile()
        tailored, missing = tailor.tailor_resume(resume_json, jd_text)
        
        sid = get_session_id()
        TRANSIENT_STATE['tailor'][sid] = {
            'tailored': tailored,
            'missing': missing,
            'company': company,
            'role': role,
            'jd_text': jd_text
        }
        return redirect(url_for('tailor_review'))
    return render_template('tailor.html')

@app.route('/tailor/review', methods=['GET', 'POST'])
def tailor_review():
    sid = get_session_id()
    state = TRANSIENT_STATE['tailor'].get(sid)
    if not state:
        return redirect(url_for('tailor_route'))
        
    if request.method == 'POST':
        tailor.export_resume(state['tailored'])
        db.log_application(state['company'], state['role'], state['jd_text'], "tailored-version")
        flash("Resume tailored, exported, and application logged.", "success")
        TRANSIENT_STATE['tailor'].pop(sid, None)
        return redirect(url_for('dashboard'))
        
    return render_template('tailor_review.html', state=state)

@app.route('/profile', methods=['GET', 'POST'])
def profile_setup():
    if request.method == 'POST':
        sid = get_session_id()
        if 'file' in request.files and request.files['file'].filename:
            file = request.files['file']
            os.makedirs("data", exist_ok=True)
            path = os.path.join("data", file.filename)
            file.save(path)
            profile_data = profile_manager.build_profile_from_file(path)
            TRANSIENT_STATE['profile'][sid] = profile_data
        else:
            profile_data = profile_manager.build_profile_manually_web(request.form.to_dict())
            TRANSIENT_STATE['profile'][sid] = profile_data
        return redirect(url_for('profile_review'))
    return render_template('profile.html')

@app.route('/profile/review', methods=['GET', 'POST'])
def profile_review():
    sid = get_session_id()
    profile_data = TRANSIENT_STATE['profile'].get(sid)
    if not profile_data:
        return redirect(url_for('profile_setup'))
        
    if request.method == 'POST':
        profile_manager.save_profile(profile_data)
        flash("Profile reviewed and saved successfully.", "success")
        TRANSIENT_STATE['profile'].pop(sid, None)
        return redirect(url_for('dashboard'))
        
    return render_template('profile_review.html', profile=profile_data)

@app.route('/emails', methods=['GET', 'POST'])
def emails():
    if request.method == 'POST':
        action_type = request.form.get('type')
        resume_json = profile_manager.load_profile()
        
        if action_type == 'single':
            jd_text = request.form.get('jd_text', '')
            recruiter_name = request.form.get('recruiter_name', 'Hiring Team')
            to_address = request.form.get('to_address', '')
            company = request.form.get('company', 'Unknown')
            role = request.form.get('role', 'Unknown')
            
            draft_raw = email_gen.generate_cold_email(jd_text, resume_json, recruiter_name)
            
            # Normalize draft structure
            if isinstance(draft_raw, str):
                parts = draft_raw.split('\n', 1)
                subject = parts[0].replace('Subject:', '').strip() if len(parts) > 1 else 'Application'
                body = parts[1].strip() if len(parts) > 1 else draft_raw
            else:
                subject = draft_raw.get('subject', 'Application')
                body = draft_raw.get('body', '')

            app_id = db.log_application(company, role, jd_text, "email-draft")
            db.update_status(app_id, "Draft")
            draft_id = str(uuid.uuid4())
            
            TRANSIENT_STATE['drafts'][draft_id] = {
                'id': draft_id,
                'application_id': app_id,
                'to_address': to_address,
                'subject': subject,
                'body': body,
                'jd_text': jd_text,
                'batch_id': None
            }
            return redirect(url_for('email_review', draft_id=draft_id))
            
        elif action_type == 'batch':
            batch_text = request.form.get('batch_text')
            batch_drafts = batch_email.process_batch_into_drafts_web(batch_text, resume_json)
            batch_id = str(uuid.uuid4())
            
            for d_id, d_data in batch_drafts.items():
                d_data['batch_id'] = batch_id
                TRANSIENT_STATE['drafts'][d_id] = d_data
                
            return redirect(url_for('batch_review', batch_id=batch_id))
            
    return render_template('emails.html')

@app.route('/emails/review/<draft_id>', methods=['GET', 'POST'])
def email_review(draft_id):
    draft = TRANSIENT_STATE['drafts'].get(draft_id)
    if not draft:
        flash("Draft not found.", "error")
        return redirect(url_for('emails'))
        
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'send':
            emailer.send_email(draft['to_address'], draft['subject'], draft['body'])
            db.update_status(draft['application_id'], "Email Sent")
            flash(f"Email sent to {draft['to_address']}.", "success")
            TRANSIENT_STATE['drafts'].pop(draft_id, None)
            
            if draft.get('batch_id'):
                return redirect(url_for('batch_review', batch_id=draft['batch_id']))
            return redirect(url_for('dashboard'))
            
        elif action == 'edit':
            draft['subject'] = request.form.get('subject')
            draft['body'] = request.form.get('body')
            return render_template('email_review.html', draft=draft, editing=True)
            
        elif action == 'rewrite':
            instructions = request.form.get('instructions')
            resume_json = profile_manager.load_profile()
            
            # Note: Adapt this line if generate_email_revision signature differs in your src/
            revised = email_gen.generate_email_revision(draft, instructions, draft['jd_text'], resume_json)
            
            if isinstance(revised, str):
                parts = revised.split('\n', 1)
                draft['subject'] = parts[0].replace('Subject:', '').strip() if len(parts) > 1 else draft['subject']
                draft['body'] = parts[1].strip() if len(parts) > 1 else revised
            else:
                draft['subject'] = revised.get('subject', draft['subject'])
                draft['body'] = revised.get('body', draft['body'])
                
            return render_template('email_review.html', draft=draft)
            
        elif action == 'skip':
            TRANSIENT_STATE['drafts'].pop(draft_id, None)
            flash("Draft skipped.", "info")
            if draft.get('batch_id'):
                return redirect(url_for('batch_review', batch_id=draft['batch_id']))
            return redirect(url_for('dashboard'))
            
    return render_template('email_review.html', draft=draft)

@app.route('/emails/batch/<batch_id>', methods=['GET'])
def batch_review(batch_id):
    batch_drafts = [d for d in TRANSIENT_STATE['drafts'].values() if d.get('batch_id') == batch_id]
    if not batch_drafts:
        flash("No pending drafts remaining for this batch.", "info")
        return redirect(url_for('dashboard'))
        
    return render_template('batch_review.html', drafts=batch_drafts, batch_id=batch_id)

@app.route('/form-fill', methods=['GET', 'POST'])
def form_fill_route():
    if request.method == 'POST':
        job_url = request.form.get('job_url')
        app_id = request.form.get('application_id')
        profile = profile_manager.load_profile()
        
        # Log new application if pasting raw URL
        if not app_id and job_url:
            app_id = db.log_application("Unknown", "Unknown", job_url, "latest")
            
        try:
            form_filler.run_form_fill_web(job_url, profile)
            if app_id:
                db.update_status(app_id, "Ready for review")
            flash("Form fill launched in headed browser. Complete manual review and submit in the spawned window.", "success")
        except Exception as e:
            err_str = str(e).lower()
            if "display" in err_str or "browser" in err_str or "headless" in err_str or "display not found" in err_str:
                flash("Error: No display environment detected. Playwright requires a real or virtual display (like xvfb) to run headed in this container.", "error")
            else:
                flash(f"Form-fill failed: {e}", "error")
                
        return redirect(url_for('form_fill_route'))
        
    apps = db.list_applications()
    return render_template('form_fill.html', applications=apps)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)