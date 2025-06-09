from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import secrets
import json
from werkzeug.utils import secure_filename
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import re
import nltk
from email_validator import validate_email, EmailNotValidError
from functools import wraps

nltk.download('punkt')
nltk.download('stopwords')
nltk.download('wordnet')

# Define login_required decorator here
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(16)

# Admin credentials
ADMIN_USERNAME = "Ranjith"
ADMIN_PASSWORD = "Ranjith@123"  # In production, use a strong password
ADMIN_EMAIL = "ranjith@jobboard.com"

# Create Excel files if they don't exist
if not os.path.exists('users.xlsx'):
    pd.DataFrame({
        'id': [1],
        'username': [ADMIN_USERNAME],
        'email': [ADMIN_EMAIL],
        'password_hash': [generate_password_hash(ADMIN_PASSWORD)],
        'is_admin': [True],
        'is_employer': [True],  # Admin can also post jobs
        'created_at': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
        'last_login': [None],
        'is_active': [True]
    }).to_excel('users.xlsx', index=False)

if not os.path.exists('jobs.xlsx'):
    pd.DataFrame({
        'id': pd.Series(dtype='int'),
        'title': pd.Series(dtype='str'),
        'description': pd.Series(dtype='str'),
        'company': pd.Series(dtype='str'),
        'location': pd.Series(dtype='str'),
        'created_at': pd.Series(dtype='str'),
        'salary': pd.Series(dtype='str'),
        'requirements': pd.Series(dtype='str'),
        'employment_type': pd.Series(dtype='str'),
        'experience_level': pd.Series(dtype='str'),
        'status': pd.Series(dtype='str'),  # 'active' or 'closed'
        'posted_by': pd.Series(dtype='int'),  # User ID of who posted the job
        'ai_score_threshold': pd.Series(dtype='float'),  # Minimum AI score required for auto-filtering
        'required_skills': pd.Series(dtype='str'),  # JSON list of required skills
        'interview_rounds': pd.Series(dtype='str'),  # JSON array of interview rounds
        'total_applications': pd.Series(dtype='int'),
        'shortlisted_candidates': pd.Series(dtype='int')
    }).to_excel('jobs.xlsx', index=False)

if not os.path.exists('applications.xlsx'):
    pd.DataFrame({
        'id': pd.Series(dtype='int'),
        'job_id': pd.Series(dtype='int'),
        'user_id': pd.Series(dtype='int'),
        'user_name': pd.Series(dtype='str'),
        'user_email': pd.Series(dtype='str'),
        'resume': pd.Series(dtype='str'),
        'cover_letter': pd.Series(dtype='str'),
        'applied_at': pd.Series(dtype='str'),
        'status': pd.Series(dtype='str'),  # 'pending', 'shortlisted', 'interviewing', 'accepted', 'rejected'
        'ai_score': pd.Series(dtype='float'),  # AI-based score for candidate ranking
        'skills_match': pd.Series(dtype='str'),  # JSON object of matched skills
        'current_interview_round': pd.Series(dtype='int'),  # Current interview stage
        'interview_schedule': pd.Series(dtype='str'),  # JSON object with interview details
        'interview_feedback': pd.Series(dtype='str'),  # JSON array of feedback from each round
        'interview_date': pd.Series(dtype='str'), # Added interview date column
        'interview_type': pd.Series(dtype='str'), # Added interview type column
        'interview_location': pd.Series(dtype='str') # Added interview location column
    }).to_excel('applications.xlsx', index=False)

# Add these configurations after app initialization
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_admin():
    return 'user_id' in session and session.get('is_admin', False)

# Add these validation functions
def validate_username(username):
    """Validate username format and requirements."""
    if len(username) < 3 or len(username) > 20:
        return False, "Username must be between 3 and 20 characters long"
    if not re.match("^[a-zA-Z0-9_]+$", username):
        return False, "Username can only contain letters, numbers, and underscores"
    return True, ""

def validate_password(password):
    """Validate password strength."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character"
    return True, ""

def validate_email_format(email):
    """Validate email format."""
    try:
        validate_email(email)
        return True, ""
    except EmailNotValidError as e:
        return False, str(e)

@app.route('/')
def index():
    try:
        jobs = pd.read_excel('jobs.xlsx')
        jobs = jobs.sort_values(by='created_at', ascending=False)

        # If user is logged in, check which jobs they've already applied to
        applied_jobs = set()
        if 'user_id' in session:
            try:
                applications = pd.read_excel('applications.xlsx')
                user_applications = applications[applications['user_id'] == session['user_id']]
                applied_jobs = set(user_applications['job_id'].tolist())
            except FileNotFoundError:
                pass # No applications yet

        return render_template('index.html',
                             jobs=jobs.to_dict('records'),
                             applied_jobs=applied_jobs,
                             session=session) # Pass session to template to check login status
    except FileNotFoundError:
        return render_template('index.html', jobs=[], applied_jobs=set(), session=session)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm_password = request.form.get('confirm_password', '')
        user_role = request.form['user_role']

        # Validate username
        is_valid_username, username_error = validate_username(username)
        if not is_valid_username:
            flash(username_error, 'error')
            return render_template('register.html')

        # Validate email
        is_valid_email, email_error = validate_email_format(email)
        if not is_valid_email:
            flash(email_error, 'error')
            return render_template('register.html')

        # Validate password
        is_valid_password, password_error = validate_password(password)
        if not is_valid_password:
            flash(password_error, 'error')
            return render_template('register.html')

        # Check password confirmation
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return render_template('register.html')

        # Validate user role
        if user_role not in ['candidate', 'recruiter', 'admin']:
            flash('Invalid user role selected', 'error')
            return render_template('register.html')

        if username.lower() == ADMIN_USERNAME.lower():
            flash('This username is not available', 'error')
            return render_template('register.html')

        try:
            users = pd.read_excel('users.xlsx')
        except FileNotFoundError:
            users = pd.DataFrame({
                'id': pd.Series(dtype='int'),
                'username': pd.Series(dtype='str'),
                'email': pd.Series(dtype='str'),
                'password_hash': pd.Series(dtype='str'),
                'is_admin': pd.Series(dtype='bool'),
                'is_employer': pd.Series(dtype='bool'),
                'created_at': pd.Series(dtype='str'),
                'last_login': pd.Series(dtype='str'),
                'is_active': pd.Series(dtype='bool')
            })

        # Check if username or email already exists
        if username in users['username'].values:
            flash('Username already exists', 'error')
            return render_template('register.html')
        if email in users['email'].values:
            flash('Email already registered', 'error')
            return render_template('register.html')

        # Set user role flags based on selection
        is_admin = user_role == 'admin'
        is_employer = user_role == 'recruiter'

        # Only allow admin registration if no admin exists yet
        if is_admin:
            existing_admins = users[users['is_admin'] == True]
            if not existing_admins.empty:
                flash('Error: Admin account already exists', 'error')
                return render_template('register.html')

        next_user_id = len(users) + 1 if not users.empty else 1

        new_user = pd.DataFrame({
            'id': [next_user_id],
            'username': [username],
            'email': [email],
            'password_hash': [generate_password_hash(password)],
            'is_admin': [is_admin],
            'is_employer': [is_employer],
            'created_at': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            'last_login': [None],
            'is_active': [True]
        })

        users = pd.concat([users, new_user], ignore_index=True) if not users.empty else new_user
        users.to_excel('users.xlsx', index=False)

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        # Basic input validation
        if not username or not password:
            flash('Please enter both username and password', 'error')
            return render_template('login.html')

        try:
            users = pd.read_excel('users.xlsx')
        except FileNotFoundError:
            flash('No users registered yet.', 'error')
            return render_template('login.html')

        user = users[users['username'] == username]

        if user.empty:
            flash('Invalid username or password', 'error')
            return render_template('login.html')

        user_data = user.iloc[0]

        # Check if account is active
        if not user_data.get('is_active', True):
            flash('Your account has been deactivated. Please contact support.', 'error')
            return render_template('login.html')

        # Verify password
        if not check_password_hash(user_data['password_hash'], password):
            # Update failed login attempts (you might want to implement this)
            flash('Invalid username or password', 'error')
            return render_template('login.html')

        # Update last login timestamp
        users.loc[users['username'] == username, 'last_login'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        users.to_excel('users.xlsx', index=False)

        # Set session variables - CORRECTED INDENTATION
        session['user_id'] = int(user_data['id'])
        session['username'] = user_data['username']
        session['is_admin'] = bool(user_data['is_admin'])
        session['is_employer'] = bool(user_data['is_employer'])

        if session['is_admin']:
            flash('Welcome Admin!', 'success')
            return redirect(url_for('admin_dashboard'))
        elif session['is_employer']:
            flash('Welcome Recruiter!', 'success')
            return redirect(url_for('recruiter_dashboard'))
        else:
            flash('Welcome Job Seeker!', 'success')
            return redirect(url_for('candidate_dashboard'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_admin', None)
    session.pop('is_employer', None)
    flash('Logged out successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/post-job', methods=['GET', 'POST'])
@login_required # Ensure only logged-in users can post jobs
def post_job():
    users = pd.read_excel('users.xlsx')
    user = users[users['id'] == session['user_id']].iloc[0]
    
    # Allow both admin and employers to post jobs
    if not (user['is_admin'] or user['is_employer']):
        flash('Only employers and admins can post jobs', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            jobs = pd.read_excel('jobs.xlsx')
        except FileNotFoundError:
            jobs = pd.DataFrame({
                'id': pd.Series(dtype='int'),
                'title': pd.Series(dtype='str'),
                'description': pd.Series(dtype='str'),
                'company': pd.Series(dtype='str'),
                'location': pd.Series(dtype='str'),
                'created_at': pd.Series(dtype='str'),
                'salary': pd.Series(dtype='str'),
                'requirements': pd.Series(dtype='str'),
                'employment_type': pd.Series(dtype='str'),
                'experience_level': pd.Series(dtype='str'),
                'status': pd.Series(dtype='str'),
                'posted_by': pd.Series(dtype='int'),
                'ai_score_threshold': pd.Series(dtype='float'),
                'required_skills': pd.Series(dtype='str'),
                'interview_rounds': pd.Series(dtype='str'),
                'total_applications': pd.Series(dtype='int'),
                'shortlisted_candidates': pd.Series(dtype='int')
            })

        next_job_id = len(jobs) + 1 if not jobs.empty else 1
        
        new_job = pd.DataFrame({
            'id': [next_job_id],
            'title': [request.form['title']],
            'description': [request.form['description']],
            'company': [request.form['company']],
            'location': [request.form['location']],
            'created_at': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            'salary': [request.form['salary']],
            'requirements': [request.form['requirements']],
            'employment_type': [request.form['employment_type']],
            'experience_level': [request.form['experience_level']],
            'posted_by': [session['user_id']],  # Store user ID of poster
            'status': ['active'],
            'ai_score_threshold': [float(request.form.get('ai_score_threshold', 0)) if request.form.get('ai_score_threshold') else 0], # Default to 0 if not provided or empty
            'required_skills': [json.dumps([skill.strip() for skill in request.form.get('required_skills', '').split(',')])], # Store as JSON
            'interview_rounds': [json.dumps([])], # Initialize as empty JSON array
            'total_applications': [0],
            'shortlisted_candidates': [0] # Initialize shortlisted count
        })
        
        jobs = pd.concat([jobs, new_job], ignore_index=True) if not jobs.empty else new_job
        jobs.to_excel('jobs.xlsx', index=False)
        
        flash('Job posted successfully!', 'success')
        if user['is_admin']:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('recruiter_dashboard')) # Recruiters go to their dashboard

    # Fetch users who are recruiters or admins to populate a dropdown or for checks if needed
    try:
        users = pd.read_excel('users.xlsx')
        recruiter_users = users[users['is_employer'] == True].to_dict('records') # This might not be needed in the template but good to have
        admin_users = users[users['is_admin'] == True].to_dict('records') # This might not be needed in the template but good to have
    except FileNotFoundError:
        recruiter_users = []
        admin_users = []

    return render_template('post_job.html') # Need to create this template

@app.route('/manage-jobs')
@login_required
def manage_jobs():
    if not is_admin():
        flash('Access denied. Admin only area.', 'error')
        return redirect(url_for('index'))
    
    try:
        jobs = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        jobs = pd.DataFrame()

    # Join with users to display posted by username
    if not jobs.empty:
        try:
            users_df = pd.read_excel('users.xlsx')
            # Ensure 'posted_by' column in jobs is of the correct type before merge
            jobs['posted_by'] = jobs['posted_by'].astype(int)
            users_df['id'] = users_df['id'].astype(int)
            jobs = pd.merge(jobs, users_df[['id', 'username']], left_on='posted_by', right_on='id', how='left', suffixes=('', '_user'))
            jobs['posted_by_username'] = jobs['username_user'].fillna('Unknown User') # Use a clear column name, handle potential missing users
            jobs = jobs.drop(columns=['id_user', 'username_user']) # Drop merged user id/username
        except FileNotFoundError:
            # If users.xlsx is not found, just use the posted_by ID
            jobs['posted_by_username'] = jobs['posted_by'].astype(str)

    return render_template('manage_jobs.html', jobs=jobs.to_dict('records'))

@app.route('/delete-job/<int:job_id>')
@login_required
def delete_job(job_id):
    if not is_admin():
        flash('Access denied. Admin only area.', 'error')
        return redirect(url_for('index'))
    
    try:
        jobs = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        flash('Jobs data not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    initial_job_count = len(jobs)
    jobs = jobs[jobs['id'] != job_id]
    
    if len(jobs) == initial_job_count:
        flash(f'Job with ID {job_id} not found.', 'error')
    else:
        jobs.to_excel('jobs.xlsx', index=False)
        flash('Job deleted successfully!', 'success')

    return redirect(url_for('admin_dashboard')) # Redirect back to admin dashboard

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not session.get('is_admin'):
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('index'))
    
    # Load data from Excel files
    try:
        users_df = pd.read_excel('users.xlsx')
        # Ensure required columns exist with default values if missing
        required_columns = ['id', 'username', 'email', 'is_admin', 'is_employer', 'created_at', 'last_login', 'is_active']
        for col in required_columns:
            if col not in users_df.columns:
                if col in ['created_at', 'last_login']:
                    users_df[col] = pd.NaT
                elif col in ['is_admin', 'is_employer', 'is_active']:
                    users_df[col] = False
                else:
                    users_df[col] = None
    except FileNotFoundError:
        users_df = pd.DataFrame(columns=['id', 'username', 'email', 'is_admin', 'is_employer', 'created_at', 'last_login', 'is_active'])

    try:
        jobs_df = pd.read_excel('jobs.xlsx')
        # Ensure posted_by is integer type for merging
        if 'posted_by' in jobs_df.columns:
            jobs_df['posted_by'] = pd.to_numeric(jobs_df['posted_by'], errors='coerce').fillna(0).astype(int)
    except FileNotFoundError:
        jobs_df = pd.DataFrame(columns=['id', 'title', 'company', 'location', 'created_at', 'salary', 'requirements', 'employment_type', 'experience_level', 'status', 'posted_by', 'ai_score_threshold', 'required_skills', 'interview_rounds', 'total_applications', 'shortlisted_candidates'])

    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        applications_df = pd.DataFrame(columns=['id', 'job_id', 'user_id', 'user_name', 'user_email', 'resume', 'cover_letter', 'applied_at', 'status', 'ai_score', 'skills_match', 'current_interview_round', 'interview_schedule', 'interview_feedback', 'interview_date', 'interview_type', 'interview_location'])
    
    # Calculate analytics
    total_users = len(users_df)
    candidates = len(users_df[~users_df['is_employer'] & ~users_df['is_admin']])
    recruiters = len(users_df[users_df['is_employer'] & ~users_df['is_admin']])
    admins = len(users_df[users_df['is_admin']])
    
    total_jobs = len(jobs_df)
    active_jobs_count = len(jobs_df[jobs_df['status'] == 'active'])
    
    # Calculate jobs posted by recruiters
    recruiter_users_ids = users_df[users_df['is_employer'] == True]['id'].tolist()
    jobs_posted_by_recruiters = len(jobs_df[jobs_df['posted_by'].isin(recruiter_users_ids)])

    total_applications = len(applications_df)
    pending_applications_count = len(applications_df[applications_df['status'] == 'pending'])
    shortlisted_applications_count = len(applications_df[applications_df['status'] == 'shortlisted'])
    interviewing_applications_count = len(applications_df[applications_df['status'] == 'interviewing'])
    
    analytics = {
        'total_users': total_users,
        'candidates': candidates,
        'recruiters': recruiters,
        'admins': admins,
        'total_jobs': total_jobs,
        'active_jobs': active_jobs_count,
        'jobs_posted_by_recruiters': jobs_posted_by_recruiters,
        'total_applications': total_applications,
        'pending_applications': pending_applications_count,
        'shortlisted_applications': shortlisted_applications_count,
        'interviewing_applications': interviewing_applications_count,
        'accepted_applications': len(applications_df[applications_df['status'] == 'accepted']),
        'rejected_applications': len(applications_df[applications_df['status'] == 'rejected'])
    }
    
    # Get recent jobs with application counts
    recent_jobs = []
    if not jobs_df.empty:
        try:
            # Ensure users_df has required columns for merging
            users_df['id'] = pd.to_numeric(users_df['id'], errors='coerce').fillna(0).astype(int)
            jobs_with_usernames = pd.merge(jobs_df, users_df[['id', 'username']], 
                                         left_on='posted_by', right_on='id', 
                                         how='left', suffixes=('', '_user'))

            for _, job in jobs_with_usernames.sort_values('created_at', ascending=False).head(5).iterrows():
                job_id = int(job['id'])
                job_applications = applications_df[applications_df['job_id'] == job_id]
                recent_jobs.append({
                    'id': job_id,
                    'title': job['title'],
                    'company': job['company'],
                    'posted_by': job.get('username', 'Unknown User'),
                    'total_applications': len(job_applications),
                    'created_at': pd.to_datetime(job['created_at']).strftime('%Y-%m-%d %H:%M:%S') if pd.notna(job['created_at']) else 'N/A'
                })
        except Exception as e:
            print(f"Error processing recent jobs for admin dashboard: {e}")
            recent_jobs = []

    # Get recent applications with user and job details
    recent_applications = []
    if not applications_df.empty:
        try:
            applications_with_details = pd.merge(applications_df, users_df[['id', 'username', 'email']], 
                                              left_on='user_id', right_on='id', 
                                              how='left', suffixes=('', '_user'))
            applications_with_details = pd.merge(applications_with_details, jobs_df[['id', 'title']], 
                                              left_on='job_id', right_on='id', 
                                              how='left', suffixes=('', '_job'))

            for _, app in applications_with_details.sort_values('applied_at', ascending=False).head(5).iterrows():
                recent_applications.append({
                    'id': int(app['id']),
                    'user_name': app.get('username', 'Unknown User'),
                    'user_email': app.get('email', 'N/A'),
                    'job_title': app.get('title', 'Unknown Job'),
                    'status': app.get('status', 'pending'),
                    'ai_score': float(app['ai_score']) if pd.notna(app['ai_score']) else 'N/A',
                    'applied_at': pd.to_datetime(app['applied_at']).strftime('%Y-%m-%d %H:%M:%S') if pd.notna(app['applied_at']) else 'N/A',
                    'resume_filename': app.get('resume', ''),
                    'resume_url': url_for('uploaded_file', filename=app['resume']) if pd.notna(app['resume']) else None
                })
        except Exception as e:
            print(f"Error processing recent applications for admin dashboard: {e}")
            recent_applications = []

    # Get all users for management
    users = []
    if not users_df.empty:
        for _, user in users_df.iterrows():
            users.append({
                'id': int(user['id']),
                'username': str(user['username']),
                'email': str(user['email']),
                'is_admin': bool(user['is_admin']),
                'is_employer': bool(user['is_employer']),
                'created_at': pd.to_datetime(user['created_at']).strftime('%Y-%m-%d %H:%M:%S') if pd.notna(user['created_at']) else 'N/A',
                'last_login': pd.to_datetime(user['last_login']).strftime('%Y-%m-%d %H:%M:%S') if pd.notna(user['last_login']) else 'Never'
            })

    # Get all jobs for management
    jobs = []
    if not jobs_df.empty:
        try:
            jobs_with_usernames = pd.merge(jobs_df, users_df[['id', 'username']], 
                                         left_on='posted_by', right_on='id', 
                                         how='left', suffixes=('', '_user'))

            for _, job in jobs_with_usernames.iterrows():
                job_id = int(job['id'])
                job_applications = applications_df[applications_df['job_id'] == job_id]
                jobs.append({
                    'id': job_id,
                    'title': str(job['title']),
                    'company': str(job['company']),
                    'posted_by': str(job.get('username', 'Unknown User')),
                    'total_applications': len(job_applications),
                    'status': str(job.get('status', 'active'))
                })
        except Exception as e:
            print(f"Error processing jobs for admin management: {e}")
            jobs = []

    return render_template('admin_dashboard.html',
                         analytics=analytics,
                         recent_jobs=recent_jobs,
                         recent_applications=recent_applications,
                         users=users,
                         jobs=jobs)

@app.route('/recruiter/dashboard')
@login_required
def recruiter_dashboard():
    if not session.get('is_employer') and not session.get('is_admin'): # Admins can also view recruiter dashboard
        flash('Access denied. Recruiter or Admin privileges required.', 'error')
        return redirect(url_for('index'))

    # Load data from Excel files
    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        jobs_df = pd.DataFrame(columns=['id', 'title', 'description', 'company', 'location', 'created_at', 'salary', 'requirements', 'employment_type', 'experience_level', 'status', 'posted_by', 'ai_score_threshold', 'required_skills', 'interview_rounds', 'total_applications', 'shortlisted_candidates'])

    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        applications_df = pd.DataFrame(columns=['id', 'job_id', 'user_id', 'user_name', 'user_email', 'resume', 'cover_letter', 'applied_at', 'status', 'ai_score', 'skills_match', 'current_interview_round', 'interview_schedule', 'interview_feedback', 'interview_date', 'interview_type', 'interview_location'])

    try:
        users_df = pd.read_excel('users.xlsx')
    except FileNotFoundError:
        users_df = pd.DataFrame(columns=['id', 'username', 'email', 'is_admin', 'is_employer', 'created_at', 'last_login', 'is_active'])

    # Filter jobs posted by this recruiter or all jobs if admin
    if session.get('is_admin'):
        recruiter_jobs = jobs_df # Admin sees all jobs
    else:
        recruiter_jobs = jobs_df[jobs_df['posted_by'] == session.get('user_id')]

    # Calculate analytics
    analytics = {
        'total_jobs': len(recruiter_jobs),
        'active_jobs': len(recruiter_jobs[recruiter_jobs['status'] == 'active']),
        'closed_jobs': len(recruiter_jobs[recruiter_jobs['status'] == 'closed']),
        'total_applications': len(applications_df[applications_df['job_id'].isin(recruiter_jobs['id'])]), # Total applications for this recruiter's/admin's view jobs
        'pending_applications': len(applications_df[
            (applications_df['job_id'].isin(recruiter_jobs['id'])) &\
            (applications_df['status'] == 'pending')
        ]),
        'shortlisted_applications': len(applications_df[
            (applications_df['job_id'].isin(recruiter_jobs['id'])) &\
            (applications_df['status'] == 'shortlisted')
        ]),
        'interviewing_applications': len(applications_df[
            (applications_df['job_id'].isin(recruiter_jobs['id'])) &\
            (applications_df['status'] == 'interviewing')
        ]) # Count of applications in interviewing status
    }

    # Get active jobs with application counts (include posted by username)
    active_jobs = []
    if not recruiter_jobs[recruiter_jobs['status'] == 'active'].empty:
         # Merge with users_df to get usernames
        recruiter_jobs_with_usernames = pd.merge(recruiter_jobs[recruiter_jobs['status'] == 'active'], users_df[['id', 'username']], left_on='posted_by', right_on='id', how='left', suffixes=('', '_user'))

        for _, job in recruiter_jobs_with_usernames.iterrows():
            # Ensure job['id'] is a scalar before using it for filtering
            job_id_scalar = job['id'].iloc[0] if isinstance(job['id'], pd.Series) else job['id']
            job_applications = applications_df[applications_df['job_id'] == job_id_scalar]
            # Calculate new applications in the last 7 days for this job
            recent_applications_for_job = job_applications[\
                pd.to_datetime(job_applications['applied_at']) > (datetime.now() - timedelta(days=7))\
            ]
            new_applications_count = len(recent_applications_for_job)

            active_jobs.append({
                'id': job_id_scalar,
                'title': job['title'],
                'company': job['company'],
                'location': job['location'],
                'salary': job['salary'],
                'status': job['status'],
                'total_applications': len(job_applications),
                'new_applications': new_applications_count,
                'posted_by': job['username']  # Changed from username_user to username
            })

    # Get recent applications for recruiter's jobs (include user email, resume link, and AI score)
    recent_applications = []
    recruiter_applications = applications_df[applications_df['job_id'].isin(recruiter_jobs['id'])]
    if not recruiter_applications.empty:
        # Merge with users_df and jobs_df to get user and job details
        applications_with_details = pd.merge(recruiter_applications, users_df[['id', 'username', 'email']], left_on='user_id', right_on='id', how='left', suffixes=('', '_user'))
        applications_with_details = pd.merge(applications_with_details, jobs_df[['id', 'title']], left_on='job_id', right_on='id', how='left', suffixes=('', '_job'))

        for _, app in applications_with_details.sort_values('applied_at', ascending=False).head(10).iterrows():
            recent_applications.append({
                'id': app['id'],
                'user_name': app['username_user'],
                'user_email': app['email_user'], # Added user email
                'job_title': app['title_job'],
                'status': app['status'],
                'ai_score': app['ai_score'] if pd.notna(app['ai_score']) else 'N/A', # Handle NaN AI score
                'applied_at': app['applied_at'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(app['applied_at'], datetime) else str(app['applied_at']),
                'resume_filename': app['resume'], # Added resume filename
                'resume_url': url_for('uploaded_file', filename=app['resume']) if pd.notna(app['resume']) else None # Added resume URL
            })

    # Get upcoming interviews for recruiter's jobs (include user email, resume link, and AI score)
    upcoming_interviews = []
    recruiter_interview_applications = recruiter_applications[\
        recruiter_applications['status'] == 'interviewing'\
    ].copy() # Use .copy() to avoid SettingWithCopyWarning

    if not recruiter_interview_applications.empty:
         # Ensure 'interview_date' is datetime objects for comparison
        recruiter_interview_applications['interview_date'] = pd.to_datetime(recruiter_interview_applications['interview_date'], errors='coerce') # Coerce errors to handle invalid dates

        for _, app in recruiter_interview_applications.iterrows():
             # Check if interview_schedule is a valid JSON string before loading
            interview_schedule = json.loads(app['interview_schedule']) if pd.notna(app['interview_schedule']) and isinstance(app['interview_schedule'], str) else None

            if interview_schedule and pd.notna(app['interview_date']) and app['interview_date'] > datetime.now():
                # Merge with users_df and jobs_df to get user and job details
                user = users_df[users_df['id'] == app['user_id']].iloc[0] if app['user_id'] in users_df['id'].values else {'username': 'Unknown User', 'email': 'N/A'}
                job = jobs_df[jobs_df['id'] == app['job_id']].iloc[0] if app['job_id'] in jobs_df['id'].values else {'title': 'Unknown Job'}

                upcoming_interviews.append({
                    'id': app['id'],
                    'applicant_name': user['username'],
                    'applicant_email': user['email'], # Added applicant email
                    'job_title': job['title'],
                    'interview_type': interview_schedule.get('type', 'N/A'),
                    'scheduled_time': app['interview_date'].strftime('%Y-%m-%d %H:%M:%S'),
                    'interviewer': interview_schedule.get('interviewer', 'N/A'),
                    'location': interview_schedule.get('location', 'N/A'),
                    'resume_filename': app['resume'], # Added resume filename
                    'resume_url': url_for('uploaded_file', filename=app['resume']) if pd.notna(app['resume']) else None # Added resume URL
                })

    return render_template('recruiter_dashboard.html',
                         analytics=analytics,
                         active_jobs=active_jobs,
                         recent_applications=recent_applications,
                         upcoming_interviews=upcoming_interviews)

@app.route('/update-application-status/<int:application_id>', methods=['POST'])
@login_required
def update_application_status(application_id):
    if not session.get('is_employer') and not session.get('is_admin'): # Allow admin to update status
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    data = request.get_json()
    new_status = data.get('status')
    interview_details = data.get('interview_details') # Expect interview details for scheduling

    if new_status not in ['pending', 'shortlisted', 'rejected', 'interviewing', 'accepted']:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Applications data not found'}), 404

    application_index = applications_df[applications_df['id'] == application_id].index

    if application_index.empty:
        return jsonify({'success': False, 'error': 'Application not found'}), 404

    application = applications_df.loc[application_index].iloc[0]

    # Verify the job belongs to this recruiter or if user is admin
    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
         return jsonify({'success': False, 'error': 'Jobs data not found'}), 404

    job = jobs_df[jobs_df['id'] == application['job_id'].iloc[0]]

    if job.empty:
         return jsonify({'success': False, 'error': 'Job for this application not found'}), 404

    # Check if the current user is the job poster or an admin
    is_job_poster = job['posted_by'].iloc[0] == session.get('user_id')
    is_admin_user = session.get('is_admin', False)

    if not is_job_poster and not is_admin_user:
         return jsonify({'success': False, 'error': 'Unauthorized to update this application'}), 403

    # Update status
    applications_df.loc[application_index, 'status'] = new_status

    # Handle interview scheduling if status is 'interviewing'
    if new_status == 'interviewing' and interview_details:
        applications_df.loc[application_index, 'interview_schedule'] = json.dumps(interview_details)
        # Convert interview_details['date'] to string if it's a datetime object
        applications_df.loc[application_index, 'interview_date'] = interview_details.get('date') # Store as string
        applications_df.loc[application_index, 'interview_type'] = interview_details.get('type')
        applications_df.loc[application_index, 'interview_location'] = interview_details.get('location')
        applications_df.loc[application_index, 'current_interview_round'] = application['current_interview_round'] + 1 if pd.notna(application['current_interview_round']) else 1
    elif new_status != 'interviewing':
        # Clear interview details if status is not interviewing
        applications_df.loc[application_index, 'interview_schedule'] = None
        applications_df.loc[application_index, 'interview_date'] = None
        applications_df.loc[application_index, 'interview_type'] = None
        applications_df.loc[application_index, 'interview_location'] = None
        applications_df.loc[application_index, 'current_interview_round'] = None

    # Update shortlisted count in jobs_df if status becomes or changes from 'shortlisted'
    if new_status == 'shortlisted' and application['status'] != 'shortlisted':
        job_index = jobs_df[jobs_df['id'] == application['job_id'].iloc[0]].index
        if not job_index.empty:
            jobs_df.loc[job_index, 'shortlisted_candidates'] = jobs_df.loc[job_index, 'shortlisted_candidates'].iloc[0] + 1
            jobs_df.to_excel('jobs.xlsx', index=False) # Save jobs_df after updating count
    elif application['status'] == 'shortlisted' and new_status != 'shortlisted':
         job_index = jobs_df[jobs_df['id'] == application['job_id'].iloc[0]].index
         if not job_index.empty:
            # Ensure count doesn't go below zero
            current_shortlisted = jobs_df.loc[job_index, 'shortlisted_candidates'].iloc[0]
            if current_shortlisted > 0:
                jobs_df.loc[job_index, 'shortlisted_candidates'] = current_shortlisted - 1
                jobs_df.to_excel('jobs.xlsx', index=False) # Save jobs_df after updating count

    applications_df.to_excel('applications.xlsx', index=False)

    return jsonify({'success': True, 'message': f'Application status updated to {new_status}'})

@app.route('/cancel-interview/<int:interview_id>', methods=['POST'])
@login_required
def cancel_interview(interview_id):
    if not session.get('is_employer') and not session.get('is_admin'): # Allow admin to cancel
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Applications data not found'}), 404

    application_index = applications_df[applications_df['id'] == interview_id].index

    if application_index.empty:
        return jsonify({'success': False, 'error': 'Interview not found'}), 404 # It's an application ID, not interview ID

    application = applications_df.loc[application_index].iloc[0]

    # Verify the job belongs to this recruiter or if user is admin
    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
         return jsonify({'success': False, 'error': 'Jobs data not found'}), 404

    job = jobs_df[jobs_df['id'] == application['job_id'].iloc[0]]

    if job.empty:
         return jsonify({'success': False, 'error': 'Job for this application not found'}), 404

    is_job_poster = job['posted_by'].iloc[0] == session.get('user_id')
    is_admin_user = session.get('is_admin', False)

    if not is_job_poster and not is_admin_user:
         return jsonify({'success': False, 'error': 'Unauthorized to cancel this interview'}), 403

    # Update status back to shortlisted and clear interview details
    applications_df.loc[application_index, 'status'] = 'shortlisted'
    applications_df.loc[application_index, 'interview_schedule'] = None
    applications_df.loc[application_index, 'interview_date'] = None
    applications_df.loc[application_index, 'interview_type'] = None
    applications_df.loc[application_index, 'interview_location'] = None
    applications_df.loc[application_index, 'current_interview_round'] = None # Reset interview round

    # Decrease shortlisted count if the application was previously interviewing (and thus shortlisted)
    # This logic depends on how you track 'shortlisted' vs 'interviewing' transitions. Assuming interviewing comes from shortlisted:
    # No change to shortlisted count needed if it moves from interviewing back to shortlisted.

    applications_df.to_excel('applications.xlsx', index=False)

    return jsonify({'success': True, 'message': 'Interview cancelled successfully and status set to shortlisted.'})

@app.route('/close-job/<int:job_id>')
@login_required
def close_job(job_id):
    if not session.get('is_employer') and not session.get('is_admin'): # Allow admin to close
        flash('Access denied. Recruiter or Admin privileges required.', 'error')
        return redirect(url_for('index'))

    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        flash('Jobs data not found.', 'error')
        # Redirect based on role
        if session.get('is_admin'):
             return redirect(url_for('admin_dashboard'))
        elif session.get('is_employer'):
             return redirect(url_for('recruiter_dashboard'))
        else:
            return redirect(url_for('index'))

    job_index = jobs_df[jobs_df['id'] == job_id].index

    if job_index.empty:
        flash('Job not found.', 'error')
        # Redirect based on role
        if session.get('is_admin'):
             return redirect(url_for('admin_dashboard'))
        elif session.get('is_employer'):
             return redirect(url_for('recruiter_dashboard'))
        else:
            return redirect(url_for('index'))

    # Check if the current user is the job poster or an admin
    is_job_poster = jobs_df.loc[job_index, 'posted_by'].iloc[0] == session.get('user_id')
    is_admin_user = session.get('is_admin', False)

    if not is_job_poster and not is_admin_user:
        flash('Unauthorized to close this job.', 'error')
         # Redirect based on role
        if session.get('is_admin'):
             return redirect(url_for('admin_dashboard'))
        elif session.get('is_employer'):
             return redirect(url_for('recruiter_dashboard'))
        else:
            return redirect(url_for('index'))

    jobs_df.loc[job_index, 'status'] = 'closed'
    jobs_df.to_excel('jobs.xlsx', index=False)

    flash('Job closed successfully.', 'success')
    # Redirect based on role
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    elif session.get('is_employer'):
        return redirect(url_for('recruiter_dashboard'))
    else:
        return redirect(url_for('index'))

# Route to serve uploaded files (resumes)
@app.route('/uploads/<filename>')
# @login_required # Restrict access to logged-in users - removed for easier testing, add back for production
def uploaded_file(filename):
    # In a real application, you'd add checks here to ensure the user
    # has permission to view this file (e.g., recruiter for a job,
    # or the candidate who uploaded it, or admin).
    # For simplicity, this example allows any logged-in user to view.
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    except FileNotFoundError:
        flash('File not found.', 'error')
        return redirect(url_for('index')) # Or a more appropriate error page

# AI-based resume analysis function
def analyze_resume(resume_text, required_skills):
    # Convert resume text and required skills to vectors
    vectorizer = TfidfVectorizer(stop_words='english')
    
    # Handle case where required_skills is empty or not a list
    if not required_skills or not isinstance(required_skills, list):
        skills_vector = vectorizer.fit_transform([''])
        processed_required_skills = []
    else:
        # Ensure all required skills are strings
        processed_required_skills = [str(skill) for skill in required_skills]
        skills_vector = vectorizer.fit_transform([' '.join(processed_required_skills)])
        
    resume_vector = vectorizer.transform([resume_text])
    
    # Calculate similarity score
    similarity = cosine_similarity(resume_vector, skills_vector)[0][0]
    
    # Extract skills from resume
    found_skills = [skill for skill in processed_required_skills
                   if re.search(r'\b' + re.escape(skill.lower()) + r'\b', resume_text.lower())]
    
    return {
        'score': float(similarity * 100) if not np.isnan(similarity) else 0.0, # Handle potential NaN
        'matched_skills': found_skills,
        'missing_skills': list(set(processed_required_skills) - set(found_skills))
    }

# Dummy resume text extraction function (replace with actual implementation)
def extract_text_from_pdf(pdf_path):
    # This is a placeholder. In a real app, you'd use a library like PyPDF2 or textract.
    print(f"Attempting to extract text from {pdf_path}")
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ''
            for page_num in range(len(reader.pages)):
                text += reader.pages[page_num].extract_text()
        return text if text else "Could not extract text from PDF."
    except ImportError:
        print("PyPDF2 not installed. Using dummy text extraction.")
        return "Sample resume text mentioning Python, SQL, Flask, and Django."
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return "Error extracting text from PDF."

@app.route('/candidate/dashboard')
@login_required # Ensure only logged-in users can view their dashboard
def candidate_dashboard():
    if session.get('is_employer') or session.get('is_admin'):
        # Redirect recruiters/admins to their respective dashboards
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('recruiter_dashboard'))

    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        applications_df = pd.DataFrame()

    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        jobs_df = pd.DataFrame()
    
    # Get all active jobs that the user has not applied to
    applied_job_ids = applications_df[applications_df['user_id'] == session['user_id']]['job_id'].tolist() if not applications_df.empty else []
    available_jobs = jobs_df[
        (jobs_df['status'] == 'active') & 
        (~jobs_df['id'].isin(applied_job_ids)) # Exclude jobs the user has applied to
    ].to_dict('records') if not jobs_df.empty else []

    # Get all applications by this candidate
    user_applications = applications_df[applications_df['user_id'] == session['user_id']]

    application_status = []
    if not user_applications.empty:
        # Merge with jobs_df to get job titles and companies
        applications_with_job_info = pd.merge(user_applications, jobs_df[['id', 'title', 'company']], left_on='job_id', right_on='id', how='left', suffixes=('', '_job'))

        for _, application in applications_with_job_info.iterrows():
            # CORRECTED try...except block structure
            try:
                interview_schedule_data = json.loads(application['interview_schedule']) if pd.notna(application['interview_schedule']) and isinstance(application['interview_schedule'], str) else None
                feedback_data = json.loads(application['interview_feedback']) if pd.notna(application['interview_feedback']) and isinstance(application['interview_feedback'], str) else None

                status = {
                    'id': application['id'], # Include application ID for potential future use
                    'job_title': application['title_job'],
                    'company': application['company_job'],
                    'applied_at': application['applied_at'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(application['applied_at']) and isinstance(application['applied_at'], (datetime, pd.Timestamp)) else str(application['applied_at']),
                    'status': application['status'],
                    'ai_score': application['ai_score'] if pd.notna(application['ai_score']) else 'N/A',
                    'resume_filename': application['resume'],
                    'resume_url': url_for('uploaded_file', filename=application['resume']) if pd.notna(application['resume']) else None,
                    'cover_letter': application['cover_letter'],
                    'skills_match': application['skills_match'],
                    'current_interview_round': application['current_interview_round'] if pd.notna(application['current_interview_round']) else 'N/A',
                    'interview_schedule': interview_schedule_data,
                    'interview_feedback': feedback_data
                }
                application_status.append(status)
            except Exception as e:
                print(f"Error processing application ID {application['id']}: {e}")
                continue # Skip this application if an error occurs

    # Calculate stats for candidate dashboard
    total_applications_count = len(application_status)
    active_applications_count = sum(1 for app in application_status if app['status'] in ['pending', 'shortlisted', 'interviewing'])
    interviews_scheduled_count = sum(1 for app in application_status if app['status'] == 'interviewing')

    analytics = {
        'total_applications': total_applications_count,
        'active_applications': active_applications_count,
        'interviews_scheduled': interviews_scheduled_count
    }

    return render_template('candidate_dashboard.html',
                           applications=application_status,
                           available_jobs=available_jobs, # Pass available jobs
                           analytics=analytics) # Pass analytics for stats

@app.route('/recruiter/schedule-interview/<int:application_id>', methods=['POST'])
@login_required
def schedule_interview(application_id):
    if not session.get('is_employer') and not session.get('is_admin'): # Allow admin to schedule
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        return jsonify({'error': 'Applications data not found'}), 404

    application_index = applications_df[applications_df['id'] == application_id].index

    if application_index.empty:
         return jsonify({'error': 'Application not found'}), 404

    application = applications_df.loc[application_index].iloc[0]

     # Verify the job belongs to this recruiter or if user is admin
    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
         return jsonify({'success': False, 'error': 'Jobs data not found'}), 404

    job = jobs_df[jobs_df['id'] == application['job_id'].iloc[0]]

    if job.empty:
         return jsonify({'success': False, 'error': 'Job for this application not found'}), 404

    is_job_poster = job['posted_by'].iloc[0] == session.get('user_id')
    is_admin_user = session.get('is_admin', False)

    if not is_job_poster and not is_admin_user:
         return jsonify({'success': False, 'error': 'Unauthorized to schedule interview for this application'}), 403

    interview_date_str = request.form.get('interview_date')
    interview_time_str = request.form.get('interview_time')
    interview_type = request.form.get('interview_type')
    interviewer_name = request.form.get('interviewer_name', session.get('username', 'N/A')) # Default to current user if not provided
    interview_location = request.form.get('interview_location')

    if not interview_date_str or not interview_time_str or not interview_type:
         return jsonify({'success': False, 'error': 'Missing required interview details'}), 400

    try:
        # Combine date and time strings and parse into datetime object
        interview_datetime_str = f"{interview_date_str} {interview_time_str}"
        interview_datetime = datetime.strptime(interview_datetime_str, '%Y-%m-%d %H:%M')
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid date or time format'}), 400
    
    # Update interview schedule
    schedule = {
        'date': interview_date_str,
        'time': interview_time_str,
        'type': interview_type,
        'interviewer': interviewer_name,
        'location': interview_location,
        'round': int(application['current_interview_round']) + 1 if pd.notna(application['current_interview_round']) else 1
    }
    
    applications_df.loc[application_index, 'interview_schedule'] = json.dumps(schedule)
    applications_df.loc[application_index, 'interview_date'] = interview_datetime # Store as datetime object
    applications_df.loc[application_index, 'interview_type'] = interview_type
    applications_df.loc[application_index, 'interview_location'] = interview_location
    applications_df.loc[application_index, 'current_interview_round'] = schedule['round']
    applications_df.loc[application_index, 'status'] = 'interviewing' # Set status to interviewing
    
    applications_df.to_excel('applications.xlsx', index=False)
    
    # Here you would typically send an email notification to the candidate
    
    return jsonify({'success': True, 'message': 'Interview scheduled successfully'})

@app.route('/recruiter/update-feedback/<int:application_id>', methods=['POST'])
@login_required
def update_feedback(application_id):
    if not session.get('is_employer') and not session.get('is_admin'): # Allow admin to update feedback
        return jsonify({'error': 'Unauthorized'}) , 403

    try:
        applications_df = pd.read_excel('applications.xlsx')
    except FileNotFoundError:
        return jsonify({'success': False, 'error': 'Applications data not found'}) , 404

    application_index = applications_df[applications_df['id'] == application_id].index

    if application_index.empty:
         return jsonify({'error': 'Application not found'}) , 404

    application = applications_df.loc[application_index].iloc[0]

    # Verify the job belongs to this recruiter or if user is admin
    try:
        jobs_df = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
         return jsonify({'success': False, 'error': 'Jobs data not found'}) , 404

    job = jobs_df[jobs_df['id'] == application['job_id'].iloc[0]]

    if job.empty:
         return jsonify({'success': False, 'error': 'Job for this application not found'}) , 404

    is_job_poster = job['posted_by'].iloc[0] == session.get('user_id')
    is_admin_user = session.get('is_admin', False)

    if not is_job_poster and not is_admin_user:
         return jsonify({'success': False, 'error': 'Unauthorized to update feedback for this application'}) , 403

    feedback_text = request.form.get('feedback')
    feedback_score = request.form.get('score')
    interview_round = request.form.get('round') # Get the round number from the form

    if not feedback_text or not feedback_score or not interview_round:
         return jsonify({'success': False, 'error': 'Missing feedback details'}) , 400

    try:
        feedback_score = float(feedback_score)
        interview_round = int(interview_round)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid score or round format'}) , 400

    feedback_item = {
        'round': interview_round,
        'feedback': feedback_text,
        'score': feedback_score,
        'interviewer': session.get('username', 'N/A'),
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    current_feedback = applications_df.loc[application_index, 'interview_feedback'].iloc[0]
    if pd.isna(current_feedback):
        feedback_list = [feedback_item]
    else:
        try:
            feedback_list = json.loads(current_feedback)
            if not isinstance(feedback_list, list): # Ensure it's a list
                feedback_list = [feedback_item]
            else:
                 # Check if feedback for this round already exists and update it, or append
                updated = False
                for i, fb in enumerate(feedback_list):
                    if fb.get('round') == interview_round:
                        feedback_list[i] = feedback_item # Update existing feedback for the round
                        updated = True
                        break
                if not updated:
                    feedback_list.append(feedback_item) # Append if no feedback for this round exists

        except json.JSONDecodeError:
            # Handle case where existing feedback is not valid JSON
            feedback_list = [feedback_item]

    applications_df.loc[application_index, 'interview_feedback'] = json.dumps(feedback_list)
    applications_df.to_excel('applications.xlsx', index=False)

    return jsonify({'success': True, 'message': 'Feedback updated successfully'})

@app.route('/apply-job/<int:job_id>', methods=['GET', 'POST'])
@login_required
def apply_job(job_id):
    # Check if the user is a candidate
    if session.get('is_employer') or session.get('is_admin'):
        flash('Only job seekers can apply for jobs.', 'error')
        # Redirect based on role
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('recruiter_dashboard'))

    try:
        jobs = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        flash('Jobs data not found.', 'error')
        return redirect(url_for('candidate_dashboard'))

    job = jobs[jobs['id'] == job_id]

    if job.empty:
        flash('Job not found.', 'error')
        return redirect(url_for('candidate_dashboard'))

    job_data = job.iloc[0]

    if request.method == 'POST':
        try:
            applications = pd.read_excel('applications.xlsx')
        except FileNotFoundError:
            applications = pd.DataFrame({
                'id': pd.Series(dtype='int'),
                'job_id': pd.Series(dtype='int'),
                'user_id': pd.Series(dtype='int'),
                'user_name': pd.Series(dtype='str'),
                'user_email': pd.Series(dtype='str'),
                'resume': pd.Series(dtype='str'),
                'cover_letter': pd.Series(dtype='str'),
                'applied_at': pd.Series(dtype='str'),
                'status': pd.Series(dtype='str'),
                'ai_score': pd.Series(dtype='float'),
                'skills_match': pd.Series(dtype='str'),
                'current_interview_round': pd.Series(dtype='int'),
                'interview_schedule': pd.Series(dtype='str'),
                'interview_feedback': pd.Series(dtype='str'),
                'interview_date': pd.Series(dtype='str'),
                'interview_type': pd.Series(dtype='str'),
                'interview_location': pd.Series(dtype='str')
            })

        users = pd.read_excel('users.xlsx') # Assume users.xlsx always exists after initial creation
        user = users[users['id'] == session['user_id']].iloc[0]

        # Check if the user has already applied for this job
        if not applications[
            (applications['user_id'] == session['user_id']) &
            (applications['job_id'] == job_id)
        ].empty:
            flash('You have already applied for this job.', 'warning')
            return redirect(url_for('candidate_dashboard'))

        # Handle file upload
        if 'resume' not in request.files or request.files['resume'].filename == '':
            flash('Resume file is required.', 'error')
            return render_template('apply_job.html', job=job_data)

        file = request.files['resume']
        if file and allowed_file(file.filename):
            filename = secure_filename(f"{session['user_id']}_{job_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            # Extract text from resume
            resume_text = extract_text_from_pdf(filepath) # Use the actual PDF extraction function

            # Perform AI-based analysis
            required_skills = json.loads(job_data['required_skills']) if pd.notna(job_data['required_skills']) and isinstance(job_data['required_skills'], str) else []
            ai_score_threshold = job_data['ai_score_threshold'] if pd.notna(job_data['ai_score_threshold']) else 0
            analysis_result = analyze_resume(resume_text, required_skills)

            new_application = pd.DataFrame({
                'id': [len(applications) + 1 if not applications.empty else 1],
                'job_id': [job_id],
                'user_id': [session['user_id']],
                'user_name': [user['username']],
                'user_email': [user['email']],
                'resume': [filename],
                'cover_letter': [request.form.get('cover_letter', '')],
                'applied_at': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
                'status': ['shortlisted' if analysis_result['score'] >= ai_score_threshold else 'pending'],
                'ai_score': [analysis_result['score']],
                'skills_match': [json.dumps(analysis_result)],
                'current_interview_round': [None],
                'interview_schedule': [None],
                'interview_feedback': [None],
                'interview_date': [None],
                'interview_type': [None],
                'interview_location': [None]
            })

            applications = pd.concat([applications, new_application], ignore_index=True) if not applications.empty else new_application
            applications.to_excel('applications.xlsx', index=False)

            # Update total applications count in jobs_df
            job_index = jobs[jobs['id'] == job_id].index
            if not job_index.empty:
                jobs.loc[job_index, 'total_applications'] = jobs.loc[job_index, 'total_applications'].iloc[0] + 1
                jobs.to_excel('jobs.xlsx', index=False) # Save jobs_df after updating count

            flash('Application submitted successfully!', 'success')
            return redirect(url_for('candidate_dashboard'))
        else:
            flash('Invalid file type for resume. Please upload a PDF.', 'error')
            return render_template('apply_job.html', job=job_data)

    return render_template('apply_job.html', job=job_data)

@app.route('/edit-job/<int:job_id>', methods=['GET', 'POST'])
@login_required
def edit_job(job_id):
    # Allow both admin and the original job poster to edit the job
    if not session.get('is_admin'):
        try:
            jobs_df = pd.read_excel('jobs.xlsx')
            job = jobs_df[jobs_df['id'] == job_id]
            if job.empty or job.iloc[0]['posted_by'] != session.get('user_id'):
                 flash('Access denied. You can only edit your own jobs.', 'error')
                 return redirect(url_for('recruiter_dashboard')) # Redirect recruiters to their dashboard

        except FileNotFoundError:
             flash('Jobs data not found.', 'error')
             return redirect(url_for('recruiter_dashboard')) # Redirect recruiters to their dashboard

    try:
        jobs = pd.read_excel('jobs.xlsx')
    except FileNotFoundError:
        flash('Jobs data not found.', 'error')
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('recruiter_dashboard'))

    job = jobs[jobs['id'] == job_id]

    if job.empty:
        flash('Job not found', 'error')
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('recruiter_dashboard'))

    if request.method == 'POST':
        jobs.loc[jobs['id'] == job_id, 'title'] = request.form['title']
        jobs.loc[jobs['id'] == job_id, 'company'] = request.form['company']
        jobs.loc[jobs['id'] == job_id, 'location'] = request.form['location']
        jobs.loc[jobs['id'] == job_id, 'salary'] = request.form['salary']
        jobs.loc[jobs['id'] == job_id, 'description'] = request.form['description']
        jobs.loc[jobs['id'] == job_id, 'requirements'] = request.form['requirements']
        jobs.loc[jobs['id'] == job_id, 'employment_type'] = request.form['employment_type']
        jobs.loc[jobs['id'] == job_id, 'experience_level'] = request.form['experience_level']
        jobs.loc[jobs['id'] == job_id, 'status'] = request.form['status']

@app.route('/job_applications/<int:job_id>')
@login_required
def job_applications(job_id):
    # Only admin or the job poster can view
    if not session.get('is_admin') and not session.get('is_employer'):
        flash('Access denied.', 'error')
        return redirect(url_for('index'))

    try:
        applications_df = pd.read_excel('applications.xlsx')
        jobs_df = pd.read_excel('jobs.xlsx')
        users_df = pd.read_excel('users.xlsx')
    except FileNotFoundError:
        flash('Data not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    job = jobs_df[jobs_df['id'] == job_id]
    if job.empty:
        flash('Job not found.', 'error')
        return redirect(url_for('admin_dashboard'))

    job_applications = applications_df[applications_df['job_id'] == job_id]
    # Merge with user info
    job_applications = pd.merge(job_applications, users_df[['id', 'username', 'email']], left_on='user_id', right_on='id', how='left', suffixes=('', '_user'))

    applications = []
    for _, app in job_applications.iterrows():
        applications.append({
            'id': int(app['id']),
            'user_name': app.get('username', 'Unknown'),
            'user_email': app.get('email', 'N/A'),
            'status': app.get('status', 'pending'),
            'ai_score': app.get('ai_score', 'N/A'),
            'applied_at': app.get('applied_at', 'N/A'),
            'resume': app.get('resume', ''),
        })

    return render_template('job_applications.html', job=job.iloc[0], applications=applications)

if __name__ == '__main__':
    app.run(debug=True) 