from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_muted = db.Column(db.Boolean, default=False, nullable=False)
    books = db.relationship('Book', backref='owner', lazy=True)
    categories = db.relationship('Category', backref='owner', lazy=True)
    notifications = db.relationship('Notification', backref='recipient', lazy=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class EvaluationTopic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_class = db.Column(db.String(50), default='All', nullable=False)
    is_global = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_read_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='unread')
    current_page = db.Column(db.Integer, default=1)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='received_messages')

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='system_logs')

# Evaluation System Models

class StudentProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    student_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    student_class = db.Column(db.String(50), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    user = db.relationship('User', backref='student_profile')
    attempts = db.relationship('EvaluationAttempt', backref='student_profile', lazy=True)

class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    target_class = db.Column(db.String(50), default='All', nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    total_marks = db.Column(db.Integer, default=100, nullable=False)
    passing_percentage = db.Column(db.Float, default=40.0, nullable=False)
    time_limit_minutes = db.Column(db.Integer, default=60, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)
    source_file = db.Column(db.String(255), nullable=True)  # Path to uploaded notes PDF
    topic_id = db.Column(db.Integer, db.ForeignKey('evaluation_topic.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    topic = db.relationship('EvaluationTopic', backref='evaluations')
    creator = db.relationship('User', backref='evaluations_created')
    questions = db.relationship('Question', backref='evaluation', lazy=True, cascade='all, delete-orphan')
    attempts = db.relationship('EvaluationAttempt', backref='evaluation', lazy=True, cascade='all, delete-orphan')

class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey('evaluation.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(500), nullable=False)
    option_b = db.Column(db.String(500), nullable=False)
    option_c = db.Column(db.String(500), nullable=False)
    option_d = db.Column(db.String(500), nullable=False)
    correct_answer = db.Column(db.String(1), nullable=False)  # a, b, c, or d
    marks = db.Column(db.Integer, default=1, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    responses = db.relationship('StudentResponse', backref='question', lazy=True, cascade='all, delete-orphan')

class EvaluationAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey('evaluation.id'), nullable=False)
    student_profile_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    total_marks_obtained = db.Column(db.Integer, default=0, nullable=False)
    is_submitted = db.Column(db.Boolean, default=False, nullable=False)
    is_graded = db.Column(db.Boolean, default=True, nullable=False)  # Auto-graded for MCQ
    latest_snapshot = db.Column(db.Text, nullable=True)
    last_snapshot_time = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref='evaluation_attempts')
    responses = db.relationship('StudentResponse', backref='attempt', lazy=True, cascade='all, delete-orphan')

class StudentResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('evaluation_attempt.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id'), nullable=False)
    selected_answer = db.Column(db.String(1), nullable=True)  # a, b, c, d, or None if unanswered
    is_correct = db.Column(db.Boolean, default=False, nullable=False)
    marks_obtained = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PlagiarismCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey('evaluation.id'), nullable=True)
    student_profile_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    similarity_percentage = db.Column(db.Float, default=0.0, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, completed, failed
    report_data = db.Column(db.JSON, nullable=True)  # Store detailed report as JSON
    
    student_profile = db.relationship('StudentProfile', backref='plagiarism_checks')

# Assignment System Models

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    target_class = db.Column(db.String(50), default='All', nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)  # deadline
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    file_path = db.Column(db.String(255), nullable=True)  # Instructions file
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    creator = db.relationship('User', backref='assignments_created')
    submissions = db.relationship('AssignmentSubmission', backref='assignment', lazy=True, cascade='all, delete-orphan')

class AssignmentSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    student_profile_id = db.Column(db.Integer, db.ForeignKey('student_profile.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)  # the submitted text
    file_path = db.Column(db.String(255), nullable=True)  # Submitted PDF file
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    plagiarism_checked = db.Column(db.Boolean, default=False, nullable=False)
    grade = db.Column(db.Float, nullable=True)  # Added marks/grade
    feedback = db.Column(db.Text, nullable=True)  # Added teacher feedback
    is_graded = db.Column(db.Boolean, default=False, nullable=False)
    
    user = db.relationship('User', backref='assignment_submissions')
    student_profile = db.relationship('StudentProfile', backref='assignment_submissions')

class AssignmentPlagiarismCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.id'), nullable=False)
    checked_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')  # pending, completed
    
    results = db.relationship('PlagiarismResult', backref='check', lazy=True, cascade='all, delete-orphan')

class PlagiarismResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(db.Integer, db.ForeignKey('assignment_plagiarism_check.id'), nullable=False)
    submission1_id = db.Column(db.Integer, db.ForeignKey('assignment_submission.id'), nullable=False)
    submission2_id = db.Column(db.Integer, db.ForeignKey('assignment_submission.id'), nullable=False)
    similarity_percentage = db.Column(db.Float, default=0.0, nullable=False)
    
    submission1 = db.relationship('AssignmentSubmission', foreign_keys=[submission1_id], backref='plagiarism_results_as_1')
    submission2 = db.relationship('AssignmentSubmission', foreign_keys=[submission2_id], backref='plagiarism_results_as_2')

class AcademicClass(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    course_name = db.Column(db.String(100), nullable=False)
    level = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_name(self):
        if self.level == 'General':
            return self.course_name
        return f"{self.course_name} — {self.level}"
