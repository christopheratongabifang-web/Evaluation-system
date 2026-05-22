import os
import re
import io
from difflib import SequenceMatcher
from pypdf import PdfReader
import google.generativeai as genai
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, send_from_directory, session, jsonify, abort
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from sqlalchemy import text, or_, and_
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch
from models import (
    db, User, Book, Category, EvaluationTopic, Notification, Message, 
    StudentProfile, Evaluation, Question, EvaluationAttempt, 
    StudentResponse, PlagiarismCheck, Assignment, 
    AssignmentSubmission, AssignmentPlagiarismCheck, PlagiarismResult, SystemLog,
    AcademicClass
)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_super_secret_key_change_in_production'
#app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://library_user:Abifang@localhost:5432/library_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
app.config['GEMINI_API_KEY'] = os.environ.get('GEMINI_API_KEY', 'AIza...') # Replace with actual key or set env var
genai.configure(api_key=app.config['GEMINI_API_KEY'])

# For password reset tokens
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

PASSWORD_RULES = {
    'uppercase': re.compile(r'[A-Z]'),
    'special': re.compile(r'[!@#$%^&*(),.?"{}|<>\[\]\\/~`_+=;:-]')
}

def is_valid_password(password):
    if not password or len(password) < 8:
        return False
    return bool(PASSWORD_RULES['uppercase'].search(password) and PASSWORD_RULES['special'].search(password))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def log_action(action, details=None):
    try:
        user_id = current_user.id if current_user.is_authenticated else None
        log = SystemLog(user_id=user_id, action=action, details=details)
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"Logging error: {str(e)}")

DEFAULT_CATEGORIES = ['progrmming in python', 'Algorithm','Technology']
CATEGORY_PALETTE = ['#6366F1', '#EC4899', '#14B8A6', '#F97316', '#22C55E', '#EAB308', '#8B5CF6', '#0EA5E9', '#F43F5E', '#10B981']

CATEGORY_PALETTE = ['#6366F1', '#EC4899', '#14B8A6', '#F97316', '#22C55E', '#EAB308', '#8B5CF6', '#0EA5E9', '#F43F5E', '#10B981']

@app.before_request
def require_profile():
    if current_user.is_authenticated and not current_user.is_admin:
        allowed_endpoints = ['student_profile', 'logout', 'static']
        if request.endpoint and request.endpoint not in allowed_endpoints:
            profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
            if not profile or not profile.student_class:
                flash('Please complete your student profile and select your class to access the platform.', 'warning')
                return redirect(url_for('student_profile'))

@app.route('/')
@login_required
def dashboard():
    view_as = request.args.get('view', 'default')
    if current_user.is_admin and view_as != 'student':
        return redirect(url_for('admin_dashboard'))

    sort_by = request.args.get('sort', 'newest')
    
    student_class = None
    if not current_user.is_admin:
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        student_class = profile.student_class if profile else None

    if current_user.is_admin:
        query = Book.query.filter(or_(Book.user_id == current_user.id, Book.is_global == True))
        recent_query = Book.query.filter(or_(Book.user_id == current_user.id, Book.is_global == True), Book.last_read_at != None)
    else:
        query = Book.query.filter(
            or_(
                Book.user_id == current_user.id, 
                and_(Book.is_global == True, or_(Book.target_class == 'All', Book.target_class == student_class))
            )
        )
        recent_query = Book.query.filter(
            or_(
                Book.user_id == current_user.id, 
                and_(Book.is_global == True, or_(Book.target_class == 'All', Book.target_class == student_class))
            ), 
            Book.last_read_at != None
        )

    if sort_by == 'newest':
        query = query.order_by(Book.created_at.desc())
    elif sort_by == 'oldest':
        query = query.order_by(Book.created_at.asc())

    visible_books = query.all()
    recent_books = recent_query.order_by(Book.last_read_at.desc()).limit(5).all()
    
    books_by_category = {}
    for book in visible_books:
        books_by_category.setdefault(book.category, []).append(book)
    books_by_category = {k: v for k, v in books_by_category.items() if v}
    if sort_by == 'category':
        books_by_category = dict(sorted(books_by_category.items()))
    category_colors = {category: CATEGORY_PALETTE[i % len(CATEGORY_PALETTE)] for i, category in enumerate(sorted(books_by_category.keys()))}

    notifications = Notification.query.filter(or_(Notification.user_id == current_user.id, Notification.user_id == None)).order_by(Notification.created_at.desc()).limit(5).all()
    unread_count = Notification.query.filter(or_(Notification.user_id == current_user.id, Notification.user_id == None), Notification.is_read == False).count()
    no_admin_exists = User.query.filter_by(is_admin=True).first() is None
    
    unread_messages = Message.query.filter(Message.recipient_id == current_user.id, Message.is_read == False).count()

    active_evaluations_count = 0
    active_assignments_count = 0
    if student_class:
        active_evaluations_count = Evaluation.query.filter(Evaluation.is_active == True, or_(Evaluation.target_class == 'All', Evaluation.target_class == student_class)).count()
        active_assignments_count = Assignment.query.filter(Assignment.is_active == True, or_(Assignment.target_class == 'All', Assignment.target_class == student_class)).count()
    elif not current_user.is_admin:
        active_evaluations_count = Evaluation.query.filter(Evaluation.is_active == True, Evaluation.target_class == 'All').count()
        active_assignments_count = Assignment.query.filter(Assignment.is_active == True, Assignment.target_class == 'All').count()

    return render_template(
        'dashboard.html',
        books_by_category=books_by_category,
        recent_books=recent_books,
        category_colors=category_colors,
        current_sort=sort_by,
        total_books=len(visible_books),
        notifications=notifications,
        unread_count=unread_count,
        no_admin_exists=no_admin_exists,
        unread_messages=unread_messages,
        active_evaluations_count=active_evaluations_count,
        active_assignments_count=active_assignments_count
    )

@app.route('/mark_notifications_read', methods=['POST'])
@login_required
def mark_notifications_read():
    Notification.query.filter(or_(Notification.user_id == current_user.id, Notification.user_id == None), Notification.is_read == False).update({'is_read': True})
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))

    all_books = Book.query.order_by(Book.created_at.desc()).all()
    global_books = [book for book in all_books if book.is_global]
    students = User.query.filter_by(is_admin=False).order_by(User.username.asc()).all()
    total_students = len(students)
    notifications = Notification.query.order_by(Notification.created_at.desc()).limit(10).all()

    return render_template(
        'admin_dashboard.html',
        all_books=all_books,
        global_books=global_books,
        total_students=total_students,
        students=students,
        notifications=notifications
    )

@app.route('/admin/send_notification', methods=['POST'])
@login_required
def send_notification():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    message = request.form.get('message')
    if message:
        notification = Notification(message=message, user_id=None)
        db.session.add(notification)
        db.session.commit()
        log_action('Broadcast Sent', f'Message: {message}')
        flash('Notification sent to all students!', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete_notification/<int:notification_id>', methods=['POST'])
@login_required
def delete_notification(notification_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    notification = Notification.query.get_or_404(notification_id)
    db.session.delete(notification)
    db.session.commit()
    log_action('Broadcast Deleted', 'A broadcast message was deleted')
    flash('Broadcast message deleted successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/messages')
@login_required
def messages():
    if current_user.is_admin:
        students = User.query.filter_by(is_admin=False).order_by(User.username.asc()).all()
        conversations = {}
        for student in students:
            msgs = Message.query.filter(or_(
                (Message.sender_id == current_user.id) & (Message.recipient_id == student.id),
                (Message.sender_id == student.id) & (Message.recipient_id == current_user.id)
            )).order_by(Message.created_at.desc()).all()
            if msgs:
                conversations[student.id] = (student, msgs)
        return render_template('admin_messages.html', students=students, conversations=conversations)
    else:
        admin = User.query.filter_by(is_admin=True).first()
        if admin:
            msgs = Message.query.filter(or_(
                (Message.sender_id == current_user.id) & (Message.recipient_id == admin.id),
                (Message.sender_id == admin.id) & (Message.recipient_id == current_user.id)
            )).order_by(Message.created_at.asc()).all()
            Message.query.filter(Message.sender_id == admin.id, Message.recipient_id == current_user.id).update({'is_read': True})
            db.session.commit()
            return render_template('student_messages.html', admin=admin, messages=msgs)
        return redirect(url_for('dashboard'))

@app.route('/send_message/<int:recipient_id>', methods=['POST'])
@login_required
def send_message(recipient_id):
    recipient = User.query.get_or_404(recipient_id)
    content = request.form.get('content')
    
    if content:
        msg = Message(sender_id=current_user.id, recipient_id=recipient_id, content=content)
        db.session.add(msg)
        db.session.commit()
        log_action('Message Sent', 'A direct message was sent')
        flash('Message sent!', 'success')
    
    if current_user.is_admin:
        return redirect(url_for('messages'))
    else:
        return redirect(url_for('messages'))

@app.route('/delete_message/<int:msg_id>', methods=['POST'])
@login_required
def delete_message(msg_id):
    msg = Message.query.get_or_404(msg_id)
    if current_user.is_admin or msg.sender_id == current_user.id or msg.recipient_id == current_user.id:
        db.session.delete(msg)
        db.session.commit()
        log_action('Message Deleted', 'A direct message was deleted')
        flash('Message deleted.', 'success')
    return redirect(url_for('messages'))

@app.route('/clear_conversation/<int:student_id>', methods=['POST'])
@login_required
def clear_conversation(student_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    Message.query.filter(or_(
        (Message.sender_id == current_user.id) & (Message.recipient_id == student_id),
        (Message.sender_id == student_id) & (Message.recipient_id == current_user.id)
    )).delete()
    db.session.commit()
    log_action('Conversation Cleared', f'Cleared conversation with student ID {student_id}')
    flash('Conversation cleared.', 'success')
    return redirect(url_for('messages'))

@app.route('/clear_all_messages', methods=['POST'])
@login_required
def clear_all_messages():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    Message.query.delete()
    Notification.query.delete()
    db.session.commit()
    log_action('All Messages Cleared', 'Admin cleared all messages and broadcasts')
    flash('All messages and broadcasts have been successfully cleared.', 'success')
    return redirect(url_for('messages'))

@app.route('/add_category', methods=['GET', 'POST'])
@login_required
def add_category():
    if not current_user.is_admin:
        flash('Only administrators can manage categories.', 'danger')
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        if name:
            existing = Category.query.filter_by(name=name, user_id=current_user.id).first()
            if existing:
                flash('Category already exists!', 'danger')
            else:
                cat = Category(name=name, user_id=current_user.id)
                db.session.add(cat)
                db.session.commit()
                log_action('Category Added', 'Added new book category')
                flash('Category added successfully!', 'success')
                return redirect(url_for('dashboard'))
    return render_template('add_category.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
            
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('register'))

        import re
        EMAIL_REGEX = re.compile(r'^[\w\.-]+@[\w\.-]+\.\w+$')
        if not EMAIL_REGEX.match(email):
            flash('Please provide a valid email address.', 'danger')
            return redirect(url_for('register'))

        if not is_valid_password(password):
            flash('Password must be at least 8 characters long, include at least one uppercase letter and one special character.', 'danger')
            return redirect(url_for('register'))
            
        is_first_admin = User.query.filter_by(is_admin=True).first() is None
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, email=email, password_hash=hashed_password, is_admin=is_first_admin)
        db.session.add(user)
        db.session.commit()
        log_action('User Registration', f'New user registered: {username}')
        
        for cat_name in DEFAULT_CATEGORIES:
            cat = Category(name=cat_name, user_id=user.id)
            db.session.add(cat)
        db.session.commit()
        
        # Log registration (system context if no current user, but here user is created)
        log = SystemLog(user_id=user.id, action="User Registered", details=f"Username: {username}, Email: {email}")
        db.session.add(log)
        db.session.commit()

        if is_first_admin:
            flash('Admin account created successfully! You can now log in.', 'success')
        else:
            flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    username = ''
    remember = False

    login_attempts = session.get('login_attempts', {})
    lockout_until = session.get('lockout_until', {})

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = username.lower()
        password = request.form.get('password', '')
        remember = True if request.form.get('remember') else False
        
        import re
        EMAIL_REGEX = re.compile(r'^[\w\.-]+@[\w\.-]+\.\w+$')
        if not EMAIL_REGEX.match(email):
            flash('Please provide a valid email address.', 'danger')
            return redirect(url_for('login'))

        user = User.query.filter_by(email=email).first()

        locked_until = lockout_until.get(username)
        if locked_until:
            locked_until = datetime.fromtimestamp(locked_until)

        if locked_until and datetime.utcnow() < locked_until:
            wait_minutes = int((locked_until - datetime.utcnow()).total_seconds() // 60) + 1
            flash(f'Too many failed attempts. Please wait {wait_minutes} minute(s) before trying again.', 'danger')
        else:
            if user and bcrypt.check_password_hash(user.password_hash, password):
                login_user(user, remember=remember)
                login_attempts.pop(username, None)
                lockout_until.pop(username, None)
                session['login_attempts'] = login_attempts
                session['lockout_until'] = lockout_until
                
                log_action("User Login", f"Successful login for user: {username}")
                
                if user.is_admin:
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('dashboard'))

            current_attempts = login_attempts.get(username, 0) + 1
            login_attempts[username] = current_attempts
            session['login_attempts'] = login_attempts

            if current_attempts >= 3:
                lockout_until[username] = (datetime.utcnow() + timedelta(minutes=10)).timestamp()
                session['lockout_until'] = lockout_until
                flash('Too many failed attempts. Please wait 10 minutes before trying again.', 'danger')
            else:
                flash('Invalid username or password. Please try again.', 'danger')

    return render_template('login.html', username=username, remember=remember)

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            token = s.dumps(email, salt='password-reset-salt')
            reset_link = url_for('reset_password', token=token, _external=True)
            # MOCK EMAIL: We just print to console and flash a message.
            print(f"\n{'='*50}\nPASSWORD RESET LINK: {reset_link}\n{'='*50}\n")
            flash('A password reset link has been generated. Check the terminal output for the link!', 'success')
        else:
            flash('Email address not found.', 'danger')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except SignatureExpired:
        flash('The password reset link has expired.', 'danger')
        return redirect(url_for('forgot_password'))
    except BadTimeSignature:
        flash('Invalid password reset link.', 'danger')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password')
        if not is_valid_password(password):
            flash('Password must include at least one uppercase letter and one special character.', 'danger')
            return redirect(request.url)

        user = User.query.filter_by(email=email).first()
        if user:
            user.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            db.session.commit()
            flash('Your password has been updated! You can now log in.', 'success')
            return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/api/chat', methods=['POST'])
@login_required
def ai_chat():
    try:
        user_message = request.json.get('message', '').strip()
        if not user_message:
            return jsonify({'error': 'Empty message'}), 400
        
        # Get user's books for context
        user_books = Book.query.filter_by(user_id=current_user.id).all()
        categories = Category.query.filter_by(user_id=current_user.id).all()
        
        # Generate smart response based on user input
        response = generate_ai_response(user_message, user_books, categories)
        
        return jsonify({'success': True, 'message': response})
            
    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500

def generate_ai_response(user_message, books, categories):
    """Generate AI responses using Google Gemini"""
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        # Build context from user's library
        context = "The user has the following books in their library:\n"
        for book in books:
            context += f"- '{book.title}' by {book.author} (Category: {book.category})\n"
        
        prompt = f"""
        You are a helpful library assistant.
        {context}
        
        User's question: {user_message}
        
        Provide a concise, friendly, and helpful response.
        """
        
        response = model.generate_content(prompt)
        return response.text
        
    except Exception as e:
        print(f"Gemini Chat Error: {str(e)}")
        return "I'm having trouble connecting to my brain right now. Please try again later!"
    # Books collection queries
    if any(word in message_lower for word in ['how many books', 'total books', 'book count', 'books do i have']):
        return f"You have {len(books)} books in your collection across {len(categories)} categories."
    
    if any(word in message_lower for word in ['my books', 'what books', 'list books', 'show books']):
        if not books:
            return "You don't have any books yet. Start by adding some books to your collection!"
        books_list = ", ".join([f"{b.title} by {b.author}" for b in books[:5]])
        if len(books) > 5:
            return f"Here are your first 5 books: {books_list}, and {len(books)-5} more."
        return f"Your books: {books_list}"
    
    if any(word in message_lower for word in ['category', 'categories', 'genres']):
        if not categories:
            return "You don't have any categories yet."
        cat_names = ", ".join([c.name for c in categories[:10]])
        return f"Your book categories: {cat_names}"
    
    if any(word in message_lower for word in ['recommend', 'suggestion', 'what should', 'what to read']):
        if not books:
            return "You don't have books yet. I recommend starting with a classic like '1984' or 'Pride and Prejudice'!"
        random_book = books[len(books) // 2] if len(books) > 0 else books[0]
        return f"Based on your collection, you might enjoy reading more in the {random_book.category} category. Try reading '{random_book.title}' by {random_book.author} if you haven't already!"
    
    # General book questions
    if any(word in message_lower for word in ['reading', 'read', 'book tips', 'how to read']):
        tips = [
            "📚 Try reading for at least 20 minutes daily to build a consistent habit.",
            "📖 Join a book club to discuss and share your reading experience.",
            "🎯 Set a reading goal - aim for at least one book per month.",
            "💡 Mix different genres to expand your reading horizons.",
            "📝 Keep notes about your favorite passages and thoughts."
        ]
        return tips[len(books) % len(tips)]
    
    if any(word in message_lower for word in ['author', 'writer', 'literature']):
        return "Authors create wonderful worlds through their words. Is there a particular author you'd like to learn about?"
    
    if any(word in message_lower for word in ['fiction', 'novel', 'story', 'plot']):
        return "Fiction allows us to explore different worlds and perspectives. Do you prefer adventure, mystery, romance, or science fiction?"
    
    # General knowledge
    if any(word in message_lower for word in ['hello', 'hi', 'hey', 'greetings']):
        return "Hello! 👋 I'm your library assistant. I can help you manage your books, get recommendations, or answer questions. What would you like to know?"
    
    if any(word in message_lower for word in ['thank', 'thanks', 'appreciate', 'help']):
        return "You're welcome! I'm here to help you organize and enjoy your book collection. Ask me anything! 😊"
    
    if any(word in message_lower for word in ['help', 'how', 'what can']):
        return """I can help you with:
• 📚 View your books and categories
• 💡 Get book recommendations
• 📖 Book reading tips and advice
• 🎯 Organize your library
• 🤔 Answer questions about books and reading

Just ask me anything!"""
    
    if any(word in message_lower for word in ['time', 'date', 'when']):
        from datetime import datetime
        current_time = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        return f"It's currently {current_time}. Perfect time to read a book! 📚"
    
    # Default response
    default_responses = [
        "That's an interesting question! I'm here to help with your library. Ask me about your books, get recommendations, or share your thoughts on reading! 📚",
        "I'd love to help! You can ask me about your book collection, get reading tips, or discuss your favorite genres. 😊",
        "Great question! While I'm still learning, I'm excellent at helping you organize your books and finding great reads. What would you like to explore? 🔍",
        "I'm your library assistant! Ask me about your books, recommendations, or anything related to reading. 📖",
    ]
    return default_responses[len(user_message) % len(default_responses)]

@app.route('/logout')
@login_required
def logout():
    log_action("User Logout", "User logged out")
    logout_user()
    return redirect(url_for('login'))

@app.route('/add_book', methods=['GET', 'POST'])
@login_required
def add_book():
    if not current_user.is_admin:
        flash('Only administrators can add books to the library.', 'danger')
        return redirect(url_for('dashboard'))
        
    categories = [c.name for c in Category.query.filter_by(user_id=current_user.id).all()]
    if not categories:
        categories = DEFAULT_CATEGORIES

    if request.method == 'POST':
        title = request.form.get('title')
        author = request.form.get('author')
        category = request.form.get('category')
        target_class = request.form.get('target_class', 'All')
        file = request.files.get('file')
        
        if file and file.filename:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            book = Book(
                title=title,
                author=author,
                category=category,
                file_path=filename,
                user_id=current_user.id,
                target_class=target_class,
                is_global=current_user.is_admin
            )
            db.session.add(book)
            db.session.commit()

            if book.is_global:
                notification = Notification(message=f"New book added: {book.title} by {book.author}", user_id=None)
                db.session.add(notification)
                db.session.commit()
                log_action("Book Added", f"Global Book: {book.title} by {book.author}")
                flash('Book added and shared with all users!', 'success')
                return redirect(url_for('admin_dashboard'))

            log_action("Book Added", f"Book: {book.title} by {book.author}")
            flash('Book added successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Please select a file', 'danger')
            return redirect(url_for('add_book'))
            
    return render_template('add_book.html', categories=categories)

@app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
@login_required
def edit_book(book_id):
    if not current_user.is_admin:
        flash('Only administrators can edit books.', 'danger')
        return redirect(url_for('dashboard'))
        
    book = Book.query.get_or_404(book_id)
    if book.user_id != current_user.id and not (current_user.is_admin and book.is_global):
        return redirect(url_for('dashboard'))
        
    categories = [c.name for c in Category.query.filter_by(user_id=current_user.id).all()]
    if not categories:
        categories = DEFAULT_CATEGORIES
        
    if request.method == 'POST':
        book.title = request.form.get('title')
        book.author = request.form.get('author')
        book.category = request.form.get('category')
        book.target_class = request.form.get('target_class', 'All')
        
        file = request.files.get('file')
        if file and file.filename != '':
            old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], book.file_path)
            if os.path.exists(old_file_path):
                os.remove(old_file_path)
            
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            book.file_path = filename
            
        db.session.commit()
        flash('Book updated successfully!', 'success')
        if current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
        
    return render_template('edit_book.html', book=book, categories=categories)

@app.route('/delete_book/<int:book_id>', methods=['POST'])
@login_required
def delete_book(book_id):
    if not current_user.is_admin:
        flash('Only administrators can delete books.', 'danger')
        return redirect(url_for('dashboard'))
        
    book = Book.query.get_or_404(book_id)
    if book.user_id == current_user.id or (current_user.is_admin and book.is_global):
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], book.file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
        db.session.delete(book)
        db.session.commit()
        flash('Book deleted successfully!', 'success')
    if current_user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('dashboard'))

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    # Admin can see everything
    if current_user.is_admin:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Check Book access
    book = Book.query.filter_by(file_path=filename).first()
    if book and (book.user_id == current_user.id or book.is_global):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    
    # Check Assignment Instructions access
    assignment = Assignment.query.filter_by(file_path=filename).first()
    if assignment:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
        
    # Check Submission access (students can see their own)
    submission = AssignmentSubmission.query.filter_by(file_path=filename, user_id=current_user.id).first()
    if submission:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    # Check Evaluation source files (admins covered above, but just in case)
    evaluation = Evaluation.query.filter_by(source_file=filename).first()
    if evaluation and evaluation.created_by == current_user.id:
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

    return redirect(url_for('dashboard'))

@app.route('/book_file/<int:book_id>')
@login_required
def book_file(book_id):
    book = Book.query.get_or_404(book_id)
    if book.user_id != current_user.id and not book.is_global:
        return redirect(url_for('dashboard'))
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], book.file_path)
    if not os.path.exists(file_path):
        abort(404)
    return send_file(file_path, mimetype='application/pdf', as_attachment=False)

@app.route('/read_book/<int:book_id>')
@login_required
def read_book(book_id):
    book = Book.query.get_or_404(book_id)
    if book.user_id != current_user.id and not book.is_global:
        return redirect(url_for('dashboard'))
    
    if book.status == 'unread':
        book.status = 'reading'
    book.last_read_at = datetime.utcnow()
    db.session.commit()
    
    return render_template('read_book.html', book=book)

@app.route('/update_progress/<int:book_id>', methods=['POST'])
@login_required
def update_progress(book_id):
    book = Book.query.get_or_404(book_id)
    if book.user_id != current_user.id and not book.is_global:
        return jsonify({'error': 'Unauthorized'}), 403
        
    data = request.json
    if 'current_page' in data:
        book.current_page = data['current_page']
    if 'status' in data:
        book.status = data['status']
        if book.status in ['reading', 'finished']:
            book.last_read_at = datetime.utcnow()
        
    db.session.commit()
    return jsonify({'success': True, 'current_page': book.current_page, 'status': book.status})

@app.route('/about')
def about():
    return render_template('about.html')

# ============== EVALUATION SYSTEM ROUTES ==============

# Helper function: Simple plagiarism checker using difflib
def calculate_similarity(text1, text2):
    """Calculate similarity percentage between two texts"""
    ratio = SequenceMatcher(None, text1.lower(), text2.lower()).ratio()
    return round(ratio * 100, 2)

# Student Profile Routes
@app.route('/student/profile', methods=['GET', 'POST'])
@login_required
def student_profile():
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    next_url = request.values.get('next')
    
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        full_name = request.form.get('full_name')
        student_class = request.form.get('student_class')
        next_url = request.form.get('next')
        
        student_id = student_id.strip() if student_id else ''
        full_name = full_name.strip() if full_name else ''
        student_class = student_class.strip() if student_class else ''

        if not student_id or not full_name or not student_class:
            flash('Student ID, full name, and class are required.', 'danger')
            return redirect(url_for('student_profile', next=next_url) if next_url else url_for('student_profile'))
        
        # Check if student_id is already in use by another user
        existing = StudentProfile.query.filter(StudentProfile.student_id == student_id, StudentProfile.user_id != current_user.id).first()
        if existing:
            flash('This student ID is already registered!', 'danger')
            return redirect(url_for('student_profile', next=next_url) if next_url else url_for('student_profile'))
        
        # Handle profile picture upload
        profile_pic_filename = profile.profile_picture if profile else None
        pic_file = request.files.get('profile_picture')
        if pic_file and pic_file.filename:
            allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
            ext = pic_file.filename.rsplit('.', 1)[-1].lower() if '.' in pic_file.filename else ''
            if ext in allowed:
                filename = secure_filename(f"profile_{current_user.id}_{int(datetime.utcnow().timestamp())}.{ext}")
                pic_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_pic_filename = filename
            else:
                flash('Only image files (PNG, JPG, JPEG, GIF, WEBP) are allowed for profile picture.', 'warning')
        
        if profile:
            profile.student_id = student_id
            profile.full_name = full_name
            profile.student_class = student_class
            profile.profile_picture = profile_pic_filename
            profile.updated_at = datetime.utcnow()
        else:
            profile = StudentProfile(user_id=current_user.id, student_id=student_id, full_name=full_name, student_class=student_class, profile_picture=profile_pic_filename)
            db.session.add(profile)
        
        db.session.commit()
        log_action('Profile Updated', 'Student updated their profile')
        flash('Profile updated successfully!', 'success')
        return redirect(next_url or url_for('dashboard'))
    
    academic_classes = AcademicClass.query.order_by(AcademicClass.course_name, AcademicClass.level).all()
    return render_template('student_profile.html', profile=profile, next_url=next_url, academic_classes=academic_classes)

@app.route('/admin/students/<int:student_id>/profile')
@login_required
def admin_view_student_profile(student_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    student = StudentProfile.query.get_or_404(student_id)
    attempts = EvaluationAttempt.query.filter_by(student_profile_id=student.id, is_submitted=True).all()
    if attempts:
        avg_eval = sum([(a.total_marks_obtained / a.evaluation.total_marks * 100) if a.evaluation.total_marks > 0 else 0 for a in attempts]) / len(attempts)
    else:
        avg_eval = 0
    submissions = AssignmentSubmission.query.filter_by(student_profile_id=student.id, is_graded=True).all()
    if submissions:
        avg_assign = sum([sub.grade for sub in submissions if sub.grade is not None]) / len(submissions)
    else:
        avg_assign = 0
    return render_template('admin_student_profile.html', student=student, attempts=attempts, submissions=submissions, avg_eval=round(avg_eval, 1), avg_assign=round(avg_assign, 1))

# Admin: Create Evaluation
@app.route('/admin/evaluations', methods=['GET', 'POST'])
@login_required
def admin_evaluations():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluations = Evaluation.query.order_by(Evaluation.created_at.desc()).all()
    return render_template('admin_evaluations.html', evaluations=evaluations)

def generate_questions_from_text(text):
    """
    Generate questions using Google Gemini AI.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Analyze the following educational notes and generate 30 multiple-choice questions.
        For each question, provide 4 options (a, b, c, d) and indicate the correct answer.
        Format the output as a JSON list of objects, each with:
        "question_text", "options" (list of 4 strings), and "correct_answer" (string 'a', 'b', 'c', or 'd').
        
        Notes:
        {text[:60000000000]}  # Limit text to stay within tokens
        """
        
        response = model.generate_content(prompt)
        # Extract JSON from response (handling potential markdown formatting)
        response_text = response.text
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]
            
        import json
        questions_data = json.loads(response_text)
        
        generated_questions = []
        for q in questions_data:
            generated_questions.append({
                'question_text': q['question_text'],
                'options': q['options'],
                'correct_answer': q['correct_answer']
            })
        return generated_questions
        
    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        # Fallback to a very simple heuristic if API fails
        sentences = re.split(r'[.!?]\s+', text)
        return [{
            'question_text': f"Based on the notes, define a key concept mentioned in: '{sentences[0][:50]}...'",
            'options': ["Correct Definition", "Wrong Option 1", "Wrong Option 2", "Wrong Option 3"],
            'correct_answer': 'a'
        }]

@app.route('/admin/evaluations/create', methods=['GET', 'POST'])
@login_required
def create_evaluation():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        total_marks = int(request.form.get('total_marks', 100))
        passing_percentage = float(request.form.get('passing_percentage', 40))
        time_limit_minutes = int(request.form.get('time_limit_minutes', 60))
        target_class = request.form.get('target_class', 'All')
        topic_id = request.form.get('topic_id')
        if topic_id == '': topic_id = None
        
        # Handle PDF Upload
        source_file = None
        pdf_file = request.files.get('notes_pdf')
        generated_questions = []
        
        if pdf_file and pdf_file.filename.endswith('.pdf'):
            filename = secure_filename(f"notes_{datetime.utcnow().timestamp()}_{pdf_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf_file.save(filepath)
            source_file = filename
            
            # Extract text and generate questions
            try:
                reader = PdfReader(filepath)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                
                if text.strip():
                    generated_questions = generate_questions_from_text(text)
            except Exception as e:
                flash(f'Error processing PDF: {str(e)}', 'warning')
        
        evaluation = Evaluation(
            title=title,
            description=description,
            target_class=target_class,
            created_by=current_user.id,
            total_marks=total_marks,
            passing_percentage=passing_percentage,
            time_limit_minutes=time_limit_minutes,
            topic_id=topic_id,
            source_file=source_file,
            is_active=True
        )
        db.session.add(evaluation)
        db.session.commit()
        
        # Add generated questions as drafts
        if generated_questions:
            for i, q_data in enumerate(generated_questions, 1):
                question = Question(
                    evaluation_id=evaluation.id,
                    question_text=q_data['question_text'],
                    option_a=q_data['options'][0],
                    option_b=q_data['options'][1],
                    option_c=q_data['options'][2],
                    option_d=q_data['options'][3],
                    correct_answer=q_data['correct_answer'],
                    marks=int(total_marks / len(generated_questions)) if generated_questions else 1,
                    order=i
                )
                db.session.add(question)
            db.session.commit()
            flash(f'Evaluation created! {len(generated_questions)} questions were generated from your notes for review.', 'success')
        else:
            flash('Evaluation created successfully!', 'success')
            
        return redirect(url_for('edit_evaluation_questions', eval_id=evaluation.id))
    
    topics = EvaluationTopic.query.all()
    return render_template('create_evaluation.html', categories=topics)

@app.route('/admin/evaluations/<int:eval_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_evaluation(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    if evaluation.is_locked:
        flash('This evaluation is locked and cannot be edited after students have started it.', 'danger')
        return redirect(url_for('admin_evaluations'))
    
    if request.method == 'POST':
        evaluation.title = request.form.get('title')
        evaluation.description = request.form.get('description')
        evaluation.total_marks = int(request.form.get('total_marks', 100))
        evaluation.passing_percentage = float(request.form.get('passing_percentage', 40))
        evaluation.time_limit_minutes = int(request.form.get('time_limit_minutes', 60))
        evaluation.target_class = request.form.get('target_class', 'All')
        evaluation.is_active = 'is_active' in request.form
        
        topic_id = request.form.get('topic_id')
        evaluation.topic_id = int(topic_id) if topic_id and topic_id != '' else None
        
        db.session.commit()
        flash('Evaluation updated successfully!', 'success')
        return redirect(url_for('admin_evaluations'))
    
    topics = EvaluationTopic.query.all()
    return render_template('edit_evaluation.html', evaluation=evaluation, categories=topics)

@app.route('/admin/evaluations/<int:eval_id>/questions/generate_ai', methods=['POST'])
@login_required
def generate_ai_questions(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    notes_text = request.form.get('ai_notes')
    pdf_file = request.files.get('ai_pdf')
    use_original = request.form.get('use_original') == 'true'
    
    text_to_process = ""
    if use_original and evaluation.source_file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], evaluation.source_file)
        if os.path.exists(filepath):
            reader = PdfReader(filepath)
            for page in reader.pages:
                text_to_process += page.extract_text()
    elif pdf_file and pdf_file.filename.endswith('.pdf'):
        filename = secure_filename(f"notes_{datetime.utcnow().timestamp()}_{pdf_file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        pdf_file.save(filepath)
        
        # Extract text from PDF
        reader = PdfReader(filepath)
        for page in reader.pages:
            text_to_process += page.extract_text()
    elif notes_text:
        text_to_process = notes_text
    
    if text_to_process:
        try:
            generated_questions = generate_questions_from_text(text_to_process)
            if generated_questions:
                current_count = Question.query.filter_by(evaluation_id=eval_id).count()
                for i, q_data in enumerate(generated_questions, 1):
                    question = Question(
                        evaluation_id=evaluation.id,
                        question_text=q_data['question_text'],
                        option_a=q_data['options'][0],
                        option_b=q_data['options'][1],
                        option_c=q_data['options'][2],
                        option_d=q_data['options'][3],
                        correct_answer=q_data['correct_answer'],
                        marks=5,
                        order=current_count + i
                    )
                    db.session.add(question)
                db.session.commit()
                flash(f'Successfully generated {len(generated_questions)} new questions!', 'success')
            else:
                flash('AI could not generate questions from the content.', 'warning')
        except Exception as e:
            flash(f'AI Generation Error: {str(e)}', 'danger')
    else:
        flash('Please provide either a PDF file or text content.', 'warning')
            
    return redirect(url_for('edit_evaluation_questions', eval_id=eval_id))

@app.route('/admin/evaluations/<int:eval_id>/questions', methods=['GET'])
@login_required
def edit_evaluation_questions(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    questions = Question.query.filter_by(evaluation_id=eval_id).order_by(Question.order).all()
    return render_template('evaluation_questions.html', evaluation=evaluation, questions=questions)

@app.route('/admin/evaluations/<int:eval_id>/questions/add', methods=['GET', 'POST'])
@login_required
def add_question(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    if request.method == 'POST':
        question_text = request.form.get('question_text')
        option_a = request.form.get('option_a')
        option_b = request.form.get('option_b')
        option_c = request.form.get('option_c')
        option_d = request.form.get('option_d')
        correct_answer = request.form.get('correct_answer')
        marks = int(request.form.get('marks', 1))
        
        # Get next order number
        last_question = Question.query.filter_by(evaluation_id=eval_id).order_by(Question.order.desc()).first()
        order = (last_question.order + 1) if last_question else 1
        
        question = Question(
            evaluation_id=eval_id,
            question_text=question_text,
            option_a=option_a,
            option_b=option_b,
            option_c=option_c,
            option_d=option_d,
            correct_answer=correct_answer,
            marks=marks,
            order=order
        )
        db.session.add(question)
        db.session.commit()
        
        flash('Question added successfully!', 'success')
        return redirect(url_for('edit_evaluation_questions', eval_id=eval_id))
    
    return render_template('add_question.html', evaluation=evaluation)

@app.route('/admin/evaluations/<int:eval_id>/questions/<int:q_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_question(eval_id, q_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    question = Question.query.get_or_404(q_id)
    if question.evaluation_id != eval_id:
        return redirect(url_for('admin_evaluations'))
    
    if request.method == 'POST':
        question.question_text = request.form.get('question_text')
        question.option_a = request.form.get('option_a')
        question.option_b = request.form.get('option_b')
        question.option_c = request.form.get('option_c')
        question.option_d = request.form.get('option_d')
        question.correct_answer = request.form.get('correct_answer')
        question.marks = int(request.form.get('marks', 1))
        
        db.session.commit()
        flash('Question updated successfully!', 'success')
        return redirect(url_for('edit_evaluation_questions', eval_id=eval_id))
    
    return render_template('edit_question.html', evaluation=evaluation, question=question)

@app.route('/admin/evaluations/<int:eval_id>/questions/<int:q_id>/delete', methods=['POST'])
@login_required
def delete_question(eval_id, q_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    question = Question.query.get_or_404(q_id)
    if question.evaluation_id != eval_id:
        return redirect(url_for('admin_evaluations'))
    
    db.session.delete(question)
    
    # Reorder remaining questions
    remaining = Question.query.filter_by(evaluation_id=eval_id).order_by(Question.order).all()
    for idx, q in enumerate(remaining, 1):
        q.order = idx
    
    db.session.commit()
    flash('Question deleted successfully!', 'success')
    return redirect(url_for('edit_evaluation_questions', eval_id=eval_id))

@app.route('/admin/evaluations/<int:eval_id>/delete', methods=['POST'])
@login_required
def delete_evaluation(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    
    # Delete associated plagiarism checks
    PlagiarismCheck.query.filter_by(evaluation_id=eval_id).delete()
    
    # Delete all associated attempts and responses
    attempts = EvaluationAttempt.query.filter_by(evaluation_id=eval_id).all()
    for attempt in attempts:
        StudentResponse.query.filter_by(attempt_id=attempt.id).delete()
        db.session.delete(attempt)
        
    Question.query.filter_by(evaluation_id=eval_id).delete()
        
    db.session.delete(evaluation)
    db.session.commit()
    flash('Evaluation deleted successfully!', 'success')
    return redirect(url_for('admin_evaluations'))

# Admin: View Evaluation Responses
@app.route('/admin/evaluations/<int:eval_id>/responses', methods=['GET'])
@login_required
def evaluation_responses(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    attempts = EvaluationAttempt.query.filter_by(evaluation_id=eval_id).order_by(EvaluationAttempt.submitted_at.desc()).all()
    passing_marks = (evaluation.total_marks * evaluation.passing_percentage) / 100
    
    stats = {
        'total_attempts': len(attempts),
        'submitted': len([a for a in attempts if a.is_submitted]),
        'passed': len([a for a in attempts if a.is_submitted and a.total_marks_obtained >= passing_marks]),
        'avg_marks': sum([a.total_marks_obtained for a in attempts if a.is_submitted]) / len([a for a in attempts if a.is_submitted]) if attempts else 0
    }
    
    return render_template('evaluation_responses.html', evaluation=evaluation, attempts=attempts, stats=stats, passing_marks=passing_marks)

@app.route('/admin/evaluations/<int:eval_id>/responses/<int:attempt_id>', methods=['GET'])
@login_required
def view_student_response(eval_id, attempt_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('admin_evaluations'))
    
    attempt = EvaluationAttempt.query.get_or_404(attempt_id)
    if attempt.evaluation_id != eval_id:
        return redirect(url_for('admin_evaluations'))
    
    responses = StudentResponse.query.filter_by(attempt_id=attempt_id).all()
    questions = Question.query.filter_by(evaluation_id=eval_id).order_by(Question.order).all()
    
    response_dict = {r.question_id: r for r in responses}
    
    return render_template('view_student_response.html', evaluation=evaluation, attempt=attempt, questions=questions, response_dict=response_dict)

# Admin: Generate PDF Report
@app.route('/admin/evaluations/<int:eval_id>/report/pdf', methods=['GET'])
@login_required
def generate_evaluation_report_pdf(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    if evaluation.created_by != current_user.id:
        return redirect(url_for('dashboard'))
    
    attempts = EvaluationAttempt.query.filter_by(evaluation_id=eval_id).filter(EvaluationAttempt.is_submitted == True).all()
    passing_marks = (evaluation.total_marks * evaluation.passing_percentage) / 100
    
    # Create PDF
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    
    story = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=12,
        alignment=1  # Center
    )
    
    story.append(Paragraph(f"Evaluation Report: {evaluation.title}", title_style))
    story.append(Spacer(1, 0.2*inch))
    
    # Report Info
    info_data = [
        ['Total Questions', str(len(evaluation.questions))],
        ['Total Marks', str(evaluation.total_marks)],
        ['Passing Percentage', f"{evaluation.passing_percentage}%"],
        ['Passing Marks', f"{passing_marks:.1f}"],
        ['Total Submissions', str(len(attempts))],
    ]
    info_table = Table(info_data, colWidths=[3*inch, 2*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f4f8')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.3*inch))
    
    # Student Results Table
    story.append(Paragraph("Student Results", styles['Heading2']))
    story.append(Spacer(1, 0.1*inch))
    
    results_data = [['Student ID', 'Student Name', 'Email', 'Marks Obtained', 'Percentage', 'Status']]
    
    for attempt in attempts:
        percentage = (attempt.total_marks_obtained / evaluation.total_marks * 100) if evaluation.total_marks > 0 else 0
        status = 'PASSED' if attempt.total_marks_obtained >= passing_marks else 'FAILED'
        student_email = attempt.student_profile.user.email if attempt.student_profile and attempt.student_profile.user else ''
        
        results_data.append([
            attempt.student_profile.student_id,
            attempt.student_profile.full_name,
            student_email,
            str(attempt.total_marks_obtained),
            f"{percentage:.2f}%",
            status
        ])
    
    results_table = Table(results_data, colWidths=[1.3*inch, 1.8*inch, 2.2*inch, 1.1*inch, 1*inch, 1*inch])
    results_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
    ]))
    story.append(results_table)
    
    # Build PDF
    doc.build(story)
    pdf_buffer.seek(0)
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"evaluation_report_{evaluation.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    )


# Admin: Plagiarism Check
@app.route('/admin/plagiarism/check', methods=['GET', 'POST'])
@login_required
def plagiarism_check():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    checks = AssignmentPlagiarismCheck.query.order_by(AssignmentPlagiarismCheck.checked_at.desc()).limit(20).all()
    assignments = Assignment.query.filter_by(created_by=current_user.id).all()
    
    if request.method == 'POST':
        assignment_id = request.form.get('assignment_id')
        if assignment_id:
            check = AssignmentPlagiarismCheck.query.filter_by(assignment_id=assignment_id).order_by(AssignmentPlagiarismCheck.checked_at.desc()).first()
            comparisons = []
            if check and check.status == 'completed':
                results = PlagiarismResult.query.filter_by(check_id=check.id).all()
                for r in results:
                    comparisons.append({
                        'student1': r.submission1.student_profile.full_name,
                        'student2': r.submission2.student_profile.full_name,
                        'similarity': r.similarity_percentage
                    })
                flash(f'Found {len(comparisons)} comparison results for this assignment.', 'success')
            else:
                flash('No plagiarism checks have been completed for this assignment yet. Please run the check from the assignment submissions page.', 'warning')
            return render_template('plagiarism_check.html', checks=checks, comparisons=comparisons, assignments=assignments)
    
    return render_template('plagiarism_check.html', checks=checks, comparisons=[], assignments=assignments)

# Admin: Manage Students
@app.route('/admin/students', methods=['GET'])
@login_required
def manage_students():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    students = StudentProfile.query.all()
    return render_template('manage_students.html', students=students)

@app.route('/admin/students/<int:student_id>/report_card', methods=['GET'])
@login_required
def generate_student_report_card(student_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    student = StudentProfile.query.get_or_404(student_id)
    user = User.query.get(student.user_id)
    
    eval_attempts = EvaluationAttempt.query.filter_by(student_profile_id=student.id, is_submitted=True).order_by(EvaluationAttempt.submitted_at.desc()).all()
    assign_submissions = AssignmentSubmission.query.filter_by(student_profile_id=student.id).order_by(AssignmentSubmission.submitted_at.desc()).all()
    
    total_evals = len(eval_attempts)
    avg_eval_percentage = 0
    if total_evals > 0:
        percentages = [(a.total_marks_obtained / a.evaluation.total_marks * 100) if a.evaluation.total_marks > 0 else 0 for a in eval_attempts]
        avg_eval_percentage = sum(percentages) / total_evals
        
    total_assigns = len(assign_submissions)
    graded_assigns = [s for s in assign_submissions if s.is_graded and s.grade is not None]
    avg_assign_grade = 0
    if graded_assigns:
        avg_assign_grade = sum([s.grade for s in graded_assigns]) / len(graded_assigns)
        
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=6,
        alignment=1
    )
    subtitle_style = ParagraphStyle(
        'ReportSubTitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#6B7280'),
        spaceAfter=20,
        alignment=1
    )
    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#1F2937'),
        spaceBefore=15,
        spaceAfter=10,
        borderPadding=(0, 0, 2, 0),
        borderColor=colors.HexColor('#3B82F6'),
        borderWidth=1
    )
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontSize=9,
        leading=11
    )
    cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        fontName='Helvetica-Bold'
    )
    
    story.append(Paragraph("ACADEMIC REPORT CARD", title_style))
    story.append(Paragraph(f"Generated on {datetime.utcnow().strftime('%B %d, %Y')}", subtitle_style))
    
    info_data = [
        [Paragraph("<b>Student Name:</b>", cell_bold), Paragraph(student.full_name, cell_style), Paragraph("<b>Student ID:</b>", cell_bold), Paragraph(student.student_id, cell_style)],
        [Paragraph("<b>Class / Grade:</b>", cell_bold), Paragraph(student.student_class or 'Unassigned', cell_style), Paragraph("<b>Email:</b>", cell_bold), Paragraph(user.email if user else 'N/A', cell_style)]
    ]
    info_table = Table(info_data, colWidths=[1.5*inch, 2.25*inch, 1.25*inch, 2.5*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F3F4F6')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 15))
    
    summary_data = [
        [Paragraph("<b>Evaluations Completed</b>", cell_bold), Paragraph("<b>Avg Evaluation Score</b>", cell_bold), Paragraph("<b>Assignments Graded</b>", cell_bold), Paragraph("<b>Avg Assignment Grade</b>", cell_bold)],
        [Paragraph(f"{total_evals}", cell_style), Paragraph(f"{avg_eval_percentage:.1f}%", cell_style), Paragraph(f"{len(graded_assigns)}/{total_assigns}", cell_style), Paragraph(f"{avg_assign_grade:.1f}/100" if graded_assigns else "N/A", cell_style)]
    ]
    summary_table = Table(summary_data, colWidths=[1.875*inch, 1.875*inch, 1.875*inch, 1.875*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DBEAFE')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#93C5FD')),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("Evaluation Performance", section_heading))
    if eval_attempts:
        eval_headers = ["Evaluation Title", "Date Taken", "Score", "Percentage", "Status"]
        eval_table_data = [[Paragraph(f"<b>{h}</b>", cell_bold) for h in eval_headers]]
        for a in eval_attempts:
            perc = (a.total_marks_obtained / a.evaluation.total_marks * 100) if a.evaluation.total_marks > 0 else 0
            passing = (a.evaluation.total_marks * a.evaluation.passing_percentage) / 100
            status_text = "<font color='#10B981'><b>PASSED</b></font>" if a.total_marks_obtained >= passing else "<font color='#EF4444'><b>FAILED</b></font>"
            eval_table_data.append([
                Paragraph(a.evaluation.title, cell_style),
                Paragraph(a.submitted_at.strftime('%Y-%m-%d') if a.submitted_at else 'N/A', cell_style),
                Paragraph(f"{a.total_marks_obtained}/{a.evaluation.total_marks}", cell_style),
                Paragraph(f"{perc:.1f}%", cell_style),
                Paragraph(status_text, cell_style)
            ])
        et = Table(eval_table_data, colWidths=[2.5*inch, 1.25*inch, 1.25*inch, 1.25*inch, 1.25*inch])
        et.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(et)
    else:
        story.append(Paragraph("<i>No evaluations completed yet.</i>", cell_style))
        
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("Assignment Performance & Feedback", section_heading))
    if assign_submissions:
        assign_headers = ["Assignment Title", "Submitted", "Grade", "Teacher Feedback"]
        assign_table_data = [[Paragraph(f"<b>{h}</b>", cell_bold) for h in assign_headers]]
        for s in assign_submissions:
            grade_text = f"<b>{s.grade}/100</b>" if s.is_graded and s.grade is not None else "<font color='#D97706'>Pending</font>"
            assign_table_data.append([
                Paragraph(s.assignment.title, cell_style),
                Paragraph(s.submitted_at.strftime('%Y-%m-%d'), cell_style),
                Paragraph(grade_text, cell_style),
                Paragraph(s.feedback or '<i>No feedback recorded.</i>', cell_style)
            ])
        at = Table(assign_table_data, colWidths=[2.2*inch, 1.1*inch, 1.1*inch, 3.1*inch])
        at.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#047857')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D1D5DB')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(at)
    else:
        story.append(Paragraph("<i>No assignments submitted yet.</i>", cell_style))
        
    doc.build(story)
    pdf_buffer.seek(0)
    
    sanitized_name = secure_filename(student.full_name.lower().replace(' ', '_'))
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"report_card_{sanitized_name}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    )

@app.route('/admin/students/<int:user_id>/toggle_mute', methods=['POST'])
@login_required
def toggle_mute_student(user_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(user_id)
    user.is_muted = not user.is_muted
    db.session.commit()
    
    status = "muted" if user.is_muted else "unmuted"
    flash(f'Student {user.username} has been {status}.', 'success')
    return redirect(url_for('manage_students'))

@app.route('/admin/students/<int:student_id>/remove', methods=['POST'])
@login_required
def remove_student(student_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    student = StudentProfile.query.get_or_404(student_id)
    user = User.query.get(student.user_id)
    
    if user:
        if user.is_admin:
            flash('Cannot remove admin accounts.', 'danger')
            return redirect(url_for('manage_students'))
            
        name = student.full_name
        try:
            # Delete associated records to prevent foreign key constraint errors
            Book.query.filter_by(user_id=user.id).delete()
            Category.query.filter_by(user_id=user.id).delete()
            AssignmentSubmission.query.filter_by(user_id=user.id).delete()
            Notification.query.filter_by(user_id=user.id).delete()
            Message.query.filter((Message.sender_id == user.id) | (Message.recipient_id == user.id)).delete()
            SystemLog.query.filter_by(user_id=user.id).delete()
            
            attempts = EvaluationAttempt.query.filter_by(user_id=user.id).all()
            for attempt in attempts:
                StudentResponse.query.filter_by(attempt_id=attempt.id).delete()
                db.session.delete(attempt)
                
            db.session.delete(student)
            db.session.delete(user)
            db.session.commit()
            
            flash(f'Student {name} has been permanently removed from the platform.', 'success')
            log_action("Student Removed", f"Permanently removed student: {name}")
        except Exception as e:
            db.session.rollback()
            flash(f'Error removing student. Please try again.', 'danger')
            print(f"Error removing student: {str(e)}")
            
    return redirect(url_for('manage_students'))

@app.route('/admin/students/delete_all', methods=['POST'])
@login_required
def delete_all_students():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    try:
        users = User.query.filter_by(is_admin=False).all()
        count = 0
        for user in users:
            # Delete associated records
            Book.query.filter_by(user_id=user.id).delete()
            Category.query.filter_by(user_id=user.id).delete()
            AssignmentSubmission.query.filter_by(user_id=user.id).delete()
            Notification.query.filter_by(user_id=user.id).delete()
            Message.query.filter((Message.sender_id == user.id) | (Message.recipient_id == user.id)).delete()
            SystemLog.query.filter_by(user_id=user.id).delete()
            
            attempts = EvaluationAttempt.query.filter_by(user_id=user.id).all()
            for attempt in attempts:
                StudentResponse.query.filter_by(attempt_id=attempt.id).delete()
                db.session.delete(attempt)
                
            student_profile = StudentProfile.query.filter_by(user_id=user.id).first()
            if student_profile:
                db.session.delete(student_profile)
                
            db.session.delete(user)
            count += 1
                
        db.session.commit()
        flash(f'Successfully deleted {count} users and all their associated data.', 'success')
        log_action("Bulk Student Deletion", f"Permanently deleted all ({count}) users.")
    except Exception as e:
        db.session.rollback()
        flash('An error occurred while trying to delete all students.', 'danger')
        print(f"Error deleting all students: {str(e)}")
        
    return redirect(url_for('manage_students'))

# Admin: Manage Classes
@app.route('/admin/classes', methods=['GET', 'POST'])
@login_required
def admin_classes():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        class_name = request.form.get('class_name', '').strip()
        if class_name:
            if ' - ' in class_name:
                parts = class_name.split(' - ', 1)
                course_name = parts[0].strip()
                level = parts[1].strip()
            elif ' — ' in class_name:
                parts = class_name.split(' — ', 1)
                course_name = parts[0].strip()
                level = parts[1].strip()
            elif '-' in class_name:
                parts = class_name.split('-', 1)
                course_name = parts[0].strip()
                level = parts[1].strip()
            else:
                course_name = class_name
                level = 'General'
                
            full_name = f"{course_name} — {level}" if level != 'General' else course_name
            if full_name.lower() == 'unassigned':
                flash("Cannot create a course named 'Unassigned' as it is a reserved system label.", 'warning')
            elif AcademicClass.query.filter(AcademicClass.name.ilike(full_name)).first():
                flash(f"Course '{full_name}' already exists.", 'warning')
            else:
                new_class = AcademicClass(name=full_name, course_name=course_name, level=level)
                db.session.add(new_class)
                db.session.commit()
                flash(f"Course '{full_name}' successfully added!", 'success')
                log_action("Course Added", f"Added academic course: {full_name}")
        return redirect(url_for('admin_classes'))
        
    classes = AcademicClass.query.order_by(AcademicClass.course_name, AcademicClass.level).all()
    class_counts = {}
    for c in classes:
        count = StudentProfile.query.filter_by(student_class=c.name).count()
        class_counts[c.name] = {
            'id': c.id, 
            'count': count, 
            'course_name': c.course_name, 
            'level': c.level
        }
        
    return render_template('admin_classes_overview.html', class_counts=class_counts)

@app.route('/admin/classes/<int:class_id>/delete', methods=['POST'])
@login_required
def delete_academic_class(class_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    target_class = AcademicClass.query.get_or_404(class_id)
    class_name = target_class.name
    
    students = StudentProfile.query.filter_by(student_class=class_name).all()
    for s in students:
        s.student_class = ''
        
    db.session.delete(target_class)
    db.session.commit()
    
    flash(f"Class '{class_name}' has been deleted. Enrolled students have been moved to Unassigned.", 'success')
    log_action("Class Deleted", f"Deleted academic class: {class_name}")
    return redirect(url_for('admin_classes'))

@app.route('/admin/classes/delete_all', methods=['POST'])
@login_required
def delete_all_academic_classes():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    classes = AcademicClass.query.all()
    count = len(classes)
    for c in classes:
        students = StudentProfile.query.filter_by(student_class=c.name).all()
        for s in students:
            s.student_class = ''
        db.session.delete(c)
        
    db.session.commit()
    flash(f"Successfully deleted all {count} classes. All students are now Unassigned.", 'success')
    log_action("Bulk Class Deletion", f"Deleted all {count} academic classes.")
    return redirect(url_for('admin_classes'))

@app.route('/admin/classes/<class_name>', methods=['GET'])
@login_required
def admin_class_detail(class_name):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    if class_name == 'Unassigned':
        students = StudentProfile.query.filter((StudentProfile.student_class == None) | (StudentProfile.student_class == '')).all()
    else:
        students = StudentProfile.query.filter_by(student_class=class_name).all()
        
    evaluations = Evaluation.query.filter((Evaluation.target_class == class_name) | (Evaluation.target_class == 'All')).all()
    assignments = Assignment.query.filter((Assignment.target_class == class_name) | (Assignment.target_class == 'All')).all()
    
    # Calculate quick stats for display
    student_stats = []
    for s in students:
        attempts = EvaluationAttempt.query.filter_by(student_profile_id=s.id, is_submitted=True).all()
        if attempts:
            avg_eval = sum([(a.total_marks_obtained / a.evaluation.total_marks * 100) if a.evaluation.total_marks > 0 else 0 for a in attempts]) / len(attempts)
        else:
            avg_eval = 0
            
        submissions = AssignmentSubmission.query.filter_by(student_profile_id=s.id, is_graded=True).all()
        if submissions:
            avg_assign = sum([sub.grade for sub in submissions if sub.grade is not None]) / len(submissions)
        else:
            avg_assign = 0
            
        student_stats.append({
            'student': s,
            'avg_eval': round(avg_eval, 1),
            'avg_assign': round(avg_assign, 1),
            'eval_count': len(attempts),
            'passed': avg_eval >= 50.0
        })
        
    return render_template('admin_class_detail.html', class_name=class_name, student_stats=student_stats, evaluations=evaluations, assignments=assignments)

@app.route('/admin/classes/<class_name>/report_pdf', methods=['GET'])
@login_required
def generate_class_report_pdf(class_name):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    if class_name == 'Unassigned':
        students = StudentProfile.query.filter((StudentProfile.student_class == None) | (StudentProfile.student_class == '')).all()
    else:
        students = StudentProfile.query.filter_by(student_class=class_name).all()
        
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, leftMargin=0.5*inch, rightMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('ReportTitle', parent=styles['Heading1'], fontSize=22, textColor=colors.HexColor('#1E3A8A'), spaceAfter=6, alignment=1)
    subtitle_style = ParagraphStyle('ReportSubTitle', parent=styles['Normal'], fontSize=12, textColor=colors.HexColor('#6B7280'), spaceAfter=25, alignment=1)
    section_heading = ParagraphStyle('SectionHeading', parent=styles['Heading2'], fontSize=16, textColor=colors.HexColor('#1F2937'), spaceBefore=15, spaceAfter=10)
    cell_style = ParagraphStyle('TableCell', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#374151'), alignment=0)
    cell_header = ParagraphStyle('TableHeader', parent=styles['Normal'], fontSize=10, textColor=colors.white, fontName='Helvetica-Bold', alignment=0)
    cell_bold = ParagraphStyle('TableCellBold', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#111827'), fontName='Helvetica-Bold', alignment=0)
    
    pass_badge = ParagraphStyle('PassBadge', parent=styles['Normal'], fontName='Helvetica-Bold', textColor=colors.HexColor('#047857'), alignment=1)
    fail_badge = ParagraphStyle('FailBadge', parent=styles['Normal'], fontName='Helvetica-Bold', textColor=colors.HexColor('#DC2626'), alignment=1)
    
    story.append(Paragraph(f"Academic Performance Master Report", title_style))
    story.append(Paragraph(f"Class: {class_name} | Generated: {datetime.utcnow().strftime('%B %d, %Y')}", subtitle_style))
    
    story.append(Paragraph("Student Performance Roster", section_heading))
    
    table_data = [[
        Paragraph("Student ID", cell_header),
        Paragraph("Full Name", cell_header),
        Paragraph("Email", cell_header),
        Paragraph("Eval Avg (%)", cell_header),
        Paragraph("Assign Avg", cell_header),
        Paragraph("Status", cell_header)
    ]]
    
    num_pass = 0
    num_fail = 0
    total_class_eval_percentage = 0
    students_with_evals = 0
    
    for s in students:
        attempts = EvaluationAttempt.query.filter_by(student_profile_id=s.id, is_submitted=True).all()
        if attempts:
            avg_eval = sum([(a.total_marks_obtained / a.evaluation.total_marks * 100) if a.evaluation.total_marks > 0 else 0 for a in attempts]) / len(attempts)
            total_class_eval_percentage += avg_eval
            students_with_evals += 1
        else:
            avg_eval = 0
            
        submissions = AssignmentSubmission.query.filter_by(student_profile_id=s.id, is_graded=True).all()
        if submissions:
            avg_assign = sum([sub.grade for sub in submissions if sub.grade is not None]) / len(submissions)
        else:
            avg_assign = 0
            
        if attempts:
            passed = avg_eval >= 50.0
        else:
            # If no evaluations taken yet, default to needs evaluation
            passed = False
            
        if attempts and passed:
            num_pass += 1
            status_para = Paragraph("PASS", pass_badge)
        elif attempts and not passed:
            num_fail += 1
            status_para = Paragraph("FAIL", fail_badge)
        else:
            status_para = Paragraph("NO ATTEMPTS", cell_style)
            
        table_data.append([
            Paragraph(s.student_id, cell_bold),
            Paragraph(s.full_name, cell_style),
            Paragraph(s.user.email, cell_style),
            Paragraph(f"{avg_eval:.1f}%" if attempts else "-", cell_style),
            Paragraph(f"{avg_assign:.1f}/100" if submissions else "-", cell_style),
            status_para
        ])
        
    roster_table = Table(table_data, colWidths=[1.1*inch, 1.8*inch, 2.0*inch, 1.0*inch, 1.0*inch, 1.1*inch])
    roster_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E3A8A')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9FAFB')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(roster_table)
    story.append(Spacer(1, 30))
    
    # Class Statistics Box
    story.append(Paragraph("Class Performance Statistics", section_heading))
    class_avg = (total_class_eval_percentage / students_with_evals) if students_with_evals > 0 else 0
    total_evaluated = num_pass + num_fail
    pass_rate = (num_pass / total_evaluated * 100) if total_evaluated > 0 else 0
    
    stat_label = ParagraphStyle('StatLabel', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor('#4B5563'), alignment=0)
    stat_val_pass = ParagraphStyle('StatValPass', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#047857'), alignment=1)
    stat_val_fail = ParagraphStyle('StatValFail', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#DC2626'), alignment=1)
    stat_val_avg = ParagraphStyle('StatValAvg', parent=styles['Normal'], fontSize=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#1E3A8A'), alignment=1)
    
    stats_data = [
        [Paragraph("<b>Metric</b>", cell_header), Paragraph("<b>Value / Statistic</b>", cell_header)],
        [Paragraph("Total Registered Students", stat_label), Paragraph(str(len(students)), stat_val_avg)],
        [Paragraph("Number of Students Passed", stat_label), Paragraph(str(num_pass), stat_val_pass)],
        [Paragraph("Number of Students Failed", stat_label), Paragraph(str(num_fail), stat_val_fail)],
        [Paragraph("Overall Passing Rate (%)", stat_label), Paragraph(f"{pass_rate:.1f}%", stat_val_pass if pass_rate >= 50 else stat_val_fail)],
        [Paragraph("Class Evaluation Average (%)", stat_label), Paragraph(f"{class_avg:.1f}%", stat_val_avg)],
    ]
    
    stats_table = Table(stats_data, colWidths=[4.0*inch, 3.5*inch])
    stats_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#374151')),
        ('PADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#D1D5DB')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F3F4F6')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(stats_table)
    
    doc.build(story)
    pdf_buffer.seek(0)
    
    sanitized_class = secure_filename(class_name.lower().replace(' ', '_'))
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"class_master_report_{sanitized_class}_{datetime.utcnow().strftime('%Y%m%d')}.pdf"
    )

# Helper for muted check
def check_muted(func):
    from functools import wraps
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_muted:
            flash('Your account has been restricted. You cannot access evaluations or submit assignments at this time.', 'danger')
            return redirect(url_for('dashboard'))
        return func(*args, **kwargs)
    return decorated_function

# Student: Take Evaluation
@app.route('/evaluation/<int:eval_id>/start', methods=['GET', 'POST'])
@login_required
@check_muted
def start_evaluation(eval_id):
    evaluation = Evaluation.query.get_or_404(eval_id)
    
    if not evaluation.is_active:
        flash('This evaluation is not active.', 'danger')
        return redirect(url_for('dashboard'))
    
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    if not profile or not profile.student_id or not profile.full_name:
        flash('Please complete your profile before starting the evaluation.', 'danger')
        return redirect(url_for('student_profile', next=url_for('start_evaluation', eval_id=eval_id)))
    
    if request.method == 'POST':
        # Check if already attempted
        existing_attempt = EvaluationAttempt.query.filter_by(
            evaluation_id=eval_id,
            user_id=current_user.id,
            is_submitted=True
        ).first()
        
        if existing_attempt:
            flash('You have already completed this evaluation!', 'warning')
            return redirect(url_for('evaluation_result', eval_id=eval_id, attempt_id=existing_attempt.id))
        
        # Create new attempt
        attempt = EvaluationAttempt(
            evaluation_id=eval_id,
            student_profile_id=profile.id,
            user_id=current_user.id,
            start_time=datetime.utcnow()
        )
        db.session.add(attempt)
        db.session.commit()
        
        return redirect(url_for('take_evaluation', eval_id=eval_id, attempt_id=attempt.id))
    
    return render_template('start_evaluation.html', evaluation=evaluation, profile=profile)

@app.route('/evaluation/<int:eval_id>/attempt/<int:attempt_id>', methods=['GET', 'POST'])
@login_required
def take_evaluation(eval_id, attempt_id):
    evaluation = Evaluation.query.get_or_404(eval_id)
    attempt = EvaluationAttempt.query.get_or_404(attempt_id)
    
    if attempt.user_id != current_user.id or attempt.evaluation_id != eval_id:
        return redirect(url_for('dashboard'))
    
    if attempt.is_submitted:
        flash('You have already submitted this evaluation!', 'warning')
        return redirect(url_for('evaluation_result', eval_id=eval_id, attempt_id=attempt_id))
    
    # Check time limit
    elapsed_minutes = (datetime.utcnow() - attempt.start_time).total_seconds() / 60
    if elapsed_minutes > evaluation.time_limit_minutes:
        # Auto-submit
        return redirect(url_for('submit_evaluation', eval_id=eval_id, attempt_id=attempt_id))
    
    remaining_minutes = evaluation.time_limit_minutes - int(elapsed_minutes)
    
    if request.method == 'POST':
        # Save answers
        questions = Question.query.filter_by(evaluation_id=eval_id).all()
        total_marks = 0
        
        for question in questions:
            selected_answer = request.form.get(f'question_{question.id}')
            is_correct = selected_answer == question.correct_answer
            marks_obtained = question.marks if is_correct else 0
            total_marks += marks_obtained
            
            response = StudentResponse(
                attempt_id=attempt_id,
                question_id=question.id,
                selected_answer=selected_answer,
                is_correct=is_correct,
                marks_obtained=marks_obtained
            )
            db.session.add(response)
        
        attempt.total_marks_obtained = total_marks
        attempt.submitted_at = datetime.utcnow()
        attempt.is_submitted = True
        attempt.end_time = datetime.utcnow()
        
        # Lock evaluation if first submission
        if not evaluation.is_locked:
            evaluation.is_locked = True
        
        db.session.commit()
        
        log_action("Evaluation Submitted", f"Submitted evaluation: {evaluation.title} (Score: {total_marks}/{evaluation.total_marks})")
        
        flash('Evaluation submitted successfully!', 'success')
        return redirect(url_for('evaluation_result', eval_id=eval_id, attempt_id=attempt_id))
    
    questions = Question.query.filter_by(evaluation_id=eval_id).order_by(Question.order).all()
    
    # Get existing responses if any
    existing_responses = StudentResponse.query.filter_by(attempt_id=attempt_id).all()
    response_dict = {r.question_id: r.selected_answer for r in existing_responses}
    
    return render_template('take_evaluation.html', 
                          evaluation=evaluation, 
                          attempt=attempt, 
                          questions=questions,
                          remaining_minutes=remaining_minutes,
                          response_dict=response_dict)

@app.route('/evaluation/<int:eval_id>/submit/<int:attempt_id>', methods=['POST'])
@login_required
def submit_evaluation(eval_id, attempt_id):
    evaluation = Evaluation.query.get_or_404(eval_id)
    attempt = EvaluationAttempt.query.get_or_404(attempt_id)
    
    if attempt.user_id != current_user.id or attempt.evaluation_id != eval_id:
        return redirect(url_for('dashboard'))
    
    if attempt.is_submitted:
        flash('You have already submitted this evaluation!', 'warning')
        return redirect(url_for('evaluation_result', eval_id=eval_id, attempt_id=attempt_id))
    
    # Save any pending answers
    questions = Question.query.filter_by(evaluation_id=eval_id).all()
    total_marks = 0
    
    for question in questions:
        selected_answer = request.form.get(f'question_{question.id}')
        
        # Check if response already exists
        existing = StudentResponse.query.filter_by(attempt_id=attempt_id, question_id=question.id).first()
        if existing:
            existing.selected_answer = selected_answer
            existing.is_correct = selected_answer == question.correct_answer
            existing.marks_obtained = question.marks if existing.is_correct else 0
        else:
            is_correct = selected_answer == question.correct_answer
            marks_obtained = question.marks if is_correct else 0
            response = StudentResponse(
                attempt_id=attempt_id,
                question_id=question.id,
                selected_answer=selected_answer,
                is_correct=is_correct,
                marks_obtained=marks_obtained
            )
            db.session.add(response)
        
        total_marks += question.marks if (existing.is_correct if existing else False) else 0
    
    attempt.total_marks_obtained = total_marks
    attempt.submitted_at = datetime.utcnow()
    attempt.is_submitted = True
    attempt.end_time = datetime.utcnow()
    
    # Lock evaluation if first submission
    if not evaluation.is_locked:
        evaluation.is_locked = True
    
    db.session.commit()
    
    log_action("Evaluation Submitted", f"Submitted evaluation: {evaluation.title} (Score: {total_marks}/{evaluation.total_marks})")
    
    flash('Evaluation submitted successfully!', 'success')
    return redirect(url_for('evaluation_result', eval_id=eval_id, attempt_id=attempt_id))

# Student: View Results
@app.route('/evaluation/<int:eval_id>/result/<int:attempt_id>', methods=['GET'])
@login_required
def evaluation_result(eval_id, attempt_id):
    evaluation = Evaluation.query.get_or_404(eval_id)
    attempt = EvaluationAttempt.query.get_or_404(attempt_id)
    
    if attempt.user_id != current_user.id or attempt.evaluation_id != eval_id:
        return redirect(url_for('dashboard'))
    
    if not attempt.is_submitted:
        flash('You have not submitted this evaluation yet!', 'warning')
        return redirect(url_for('take_evaluation', eval_id=eval_id, attempt_id=attempt_id))
    
    responses = StudentResponse.query.filter_by(attempt_id=attempt_id).all()
    questions = Question.query.filter_by(evaluation_id=eval_id).order_by(Question.order).all()
    
    response_dict = {r.question_id: r for r in responses}
    
    passing_marks = (evaluation.total_marks * evaluation.passing_percentage) / 100
    percentage = (attempt.total_marks_obtained / evaluation.total_marks * 100) if evaluation.total_marks > 0 else 0
    is_passed = attempt.total_marks_obtained >= passing_marks
    
    return render_template('evaluation_result.html',
                          evaluation=evaluation,
                          attempt=attempt,
                          questions=questions,
                          response_dict=response_dict,
                          percentage=percentage,
                          is_passed=is_passed,
                          passing_marks=passing_marks)

@app.route('/api/evaluation/<int:attempt_id>/snapshot', methods=['POST'])
@login_required
def save_snapshot(attempt_id):
    attempt = EvaluationAttempt.query.get_or_404(attempt_id)
    if attempt.user_id != current_user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json
    if data and 'image' in data:
        attempt.latest_snapshot = data['image']
        attempt.last_snapshot_time = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'No image data'}), 400

@app.route('/admin/evaluations/<int:eval_id>/monitor', methods=['GET'])
@login_required
def admin_monitor(eval_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    evaluation = Evaluation.query.get_or_404(eval_id)
    active_attempts = EvaluationAttempt.query.filter_by(evaluation_id=eval_id, is_submitted=False).all()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        attempts_data = []
        for attempt in active_attempts:
            time_since = None
            if attempt.last_snapshot_time:
                time_since = (datetime.utcnow() - attempt.last_snapshot_time).total_seconds()
                
            attempts_data.append({
                'id': attempt.id,
                'student_name': attempt.student_profile.full_name,
                'image': attempt.latest_snapshot,
                'time_since': time_since
            })
        return jsonify(attempts_data)
        
    return render_template('admin_monitor.html', evaluation=evaluation, active_attempts=active_attempts)

# List available evaluations for students
@app.route('/admin/evaluation-topics', methods=['GET'])
@login_required
def manage_evaluation_topics():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    topics = EvaluationTopic.query.order_by(EvaluationTopic.name).all()
    return render_template('manage_evaluation_topics.html', topics=topics)

@app.route('/admin/evaluation-topics/add', methods=['POST'])
@login_required
def add_evaluation_topic():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    name = request.form.get('name')
    if name:
        existing = EvaluationTopic.query.filter_by(name=name).first()
        if not existing:
            topic = EvaluationTopic(name=name)
            db.session.add(topic)
            db.session.commit()
            flash(f'Topic "{name}" added successfully!', 'success')
        else:
            flash(f'Topic "{name}" already exists.', 'warning')
    return redirect(url_for('manage_evaluation_topics'))

@app.route('/admin/evaluation-topics/delete/<int:topic_id>', methods=['POST'])
@login_required
def delete_evaluation_topic(topic_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    topic = EvaluationTopic.query.get_or_404(topic_id)
    # Nullify references in evaluations
    Evaluation.query.filter_by(topic_id=topic_id).update({Evaluation.topic_id: None})
    db.session.delete(topic)
    db.session.commit()
    flash(f'Topic "{topic.name}" deleted.', 'info')
    return redirect(url_for('manage_evaluation_topics'))

@app.route('/evaluations', methods=['GET'])
@login_required
@check_muted
def list_evaluations():
    if current_user.is_admin:
        return redirect(url_for('admin_evaluations'))
    
    topic_id = request.args.get('topic_id')
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    student_class = profile.student_class if profile else None
    
    query = Evaluation.query.filter(
        Evaluation.is_active == True,
        or_(Evaluation.target_class == 'All', Evaluation.target_class == student_class)
    )
    if topic_id:
        query = query.filter_by(topic_id=topic_id)
    
    evaluations = query.order_by(Evaluation.created_at.desc()).all()
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    topics = EvaluationTopic.query.all()
    
    # Get student's attempts
    attempts = EvaluationAttempt.query.filter_by(user_id=current_user.id).all()
    attempt_dict = {a.evaluation_id: a for a in attempts if a.is_submitted}
    
    # Calculate Stats for the selected topic or overall
    total_taken = len([a for a in attempts if a.is_submitted and (not topic_id or a.evaluation.topic_id == int(topic_id))])
    avg_score = 0
    if total_taken > 0:
        scores = [a.total_marks_obtained / a.evaluation.total_marks for a in attempts if a.is_submitted and (not topic_id or a.evaluation.topic_id == int(topic_id))]
        avg_score = sum(scores) / total_taken * 100
        
    stats = {
        'total_taken': total_taken,
        'avg_score': round(avg_score, 1),
        'category_name': EvaluationTopic.query.get(topic_id).name if topic_id else "All Subjects"
    }
    
    return render_template('list_evaluations.html', 
                           evaluations=evaluations, 
                           attempt_dict=attempt_dict, 
                           profile=profile, 
                           categories=topics,  # Template uses 'categories' variable name
                           selected_category=topic_id,
                           stats=stats)

# ============== ASSIGNMENT SYSTEM ROUTES ==============

# Admin: List Assignments
@app.route('/admin/assignments', methods=['GET'])
@login_required
def admin_assignments():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    assignments = Assignment.query.order_by(Assignment.created_at.desc()).all()
    return render_template('admin_assignments.html', assignments=assignments)

@app.route('/admin/assignments/<int:assignment_id>/delete', methods=['POST'])
@login_required
def delete_assignment(assignment_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
        
    assignment = Assignment.query.get_or_404(assignment_id)
    
    checks = AssignmentPlagiarismCheck.query.filter_by(assignment_id=assignment_id).all()
    for check in checks:
        PlagiarismResult.query.filter_by(check_id=check.id).delete()
        db.session.delete(check)
        
    AssignmentSubmission.query.filter_by(assignment_id=assignment_id).delete()
    
    db.session.delete(assignment)
    db.session.commit()
    log_action('Assignment Deleted', 'An assignment was deleted')
    flash('Assignment deleted successfully!', 'success')
    return redirect(url_for('admin_assignments'))

# Admin: Create Assignment
@app.route('/admin/assignments/create', methods=['GET', 'POST'])
@login_required
def create_assignment():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        target_class = request.form.get('target_class', 'All')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        
        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('create_assignment'))
        
        start_date = None
        end_date = None
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Invalid start date format.', 'danger')
                return redirect(url_for('create_assignment'))
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Invalid end date format.', 'danger')
                return redirect(url_for('create_assignment'))
        
        # Handle PDF Upload
        file_path = None
        pdf_file = request.files.get('instructions_pdf')
        if pdf_file and pdf_file.filename.endswith('.pdf'):
            filename = secure_filename(f"assign_{datetime.utcnow().timestamp()}_{pdf_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf_file.save(filepath)
            file_path = filename

        assignment = Assignment(
            title=title,
            description=description,
            target_class=target_class,
            created_by=current_user.id,
            start_date=start_date,
            end_date=end_date,
            file_path=file_path
        )
        db.session.add(assignment)
        db.session.commit()
        
        log_action("Assignment Created", f"Title: {title}")
        
        flash('Assignment created successfully!', 'success')
        return redirect(url_for('admin_assignments'))
    
    return render_template('create_assignment.html')

# Admin: View Assignment Submissions
@app.route('/admin/assignments/<int:assignment_id>/submissions', methods=['GET'])
@login_required
def admin_assignment_submissions(assignment_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.created_by != current_user.id:
        return redirect(url_for('admin_assignments'))
    
    submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment_id).order_by(AssignmentSubmission.submitted_at.desc()).all()
    
    # Get plagiarism check if exists
    plagiarism_check = AssignmentPlagiarismCheck.query.filter_by(assignment_id=assignment_id).first()
    results = []
    if plagiarism_check and plagiarism_check.status == 'completed':
        results = PlagiarismResult.query.filter_by(check_id=plagiarism_check.id).all()
    
    return render_template('admin_assignment_submissions.html', 
                          assignment=assignment, 
                          submissions=submissions, 
                          plagiarism_check=plagiarism_check,
                          results=results)

@app.route('/admin/assignments/grade/<int:submission_id>', methods=['POST'])
@login_required
def grade_submission(submission_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    submission = AssignmentSubmission.query.get_or_404(submission_id)
    grade = request.form.get('grade')
    feedback = request.form.get('feedback')
    
    submission.grade = float(grade) if grade else None
    submission.feedback = feedback
    submission.is_graded = True
    
    db.session.commit()
    log_action('Submission Graded', f'Graded submission with score: {grade}%')
    flash('Submission graded successfully!', 'success')
    return redirect(url_for('admin_assignment_submissions', assignment_id=submission.assignment_id))

# Admin: Check Plagiarism for Assignment
@app.route('/admin/assignments/<int:assignment_id>/check_plagiarism', methods=['POST'])
@login_required
def check_assignment_plagiarism(assignment_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    if assignment.created_by != current_user.id:
        return redirect(url_for('admin_assignments'))
    
    submissions = AssignmentSubmission.query.filter_by(assignment_id=assignment_id).all()
    if len(submissions) < 2:
        flash('Need at least 2 submissions to check plagiarism.', 'warning')
        return redirect(url_for('admin_assignment_submissions', assignment_id=assignment_id))
    
    # Create plagiarism check
    check = AssignmentPlagiarismCheck(assignment_id=assignment_id)
    db.session.add(check)
    db.session.commit()
    
    # Compare all pairs
    for i in range(len(submissions)):
        for j in range(i+1, len(submissions)):
            sub1 = submissions[i]
            sub2 = submissions[j]
            similarity = calculate_similarity(sub1.content, sub2.content)
            
            result = PlagiarismResult(
                check_id=check.id,
                submission1_id=sub1.id,
                submission2_id=sub2.id,
                similarity_percentage=similarity
            )
            db.session.add(result)
    
    check.status = 'completed'
    db.session.commit()
    
    flash('Plagiarism check completed!', 'success')
    return redirect(url_for('admin_assignment_submissions', assignment_id=assignment_id))

# Student: List Assignments
@app.route('/assignments', methods=['GET'])
@login_required
@check_muted
def list_assignments():
    if current_user.is_admin:
        return redirect(url_for('admin_assignments'))
    
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    student_class = profile.student_class if profile else None
    
    assignments = Assignment.query.filter(
        Assignment.is_active == True,
        or_(Assignment.target_class == 'All', Assignment.target_class == student_class)
    ).order_by(Assignment.created_at.desc()).all()
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    
    # Get student's submissions
    submissions = AssignmentSubmission.query.filter_by(user_id=current_user.id).all()
    submission_dict = {s.assignment_id: s for s in submissions}
    
    return render_template('list_assignments.html', assignments=assignments, submission_dict=submission_dict, profile=profile)

@app.route('/assignments/<int:assignment_id>/view', methods=['GET'])
@login_required
def view_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    if not current_user.is_admin and not assignment.is_active:
        flash('This assignment is not active.', 'danger')
        return redirect(url_for('list_assignments'))
    return render_template('view_assignment.html', assignment=assignment)

# Student: Submit Assignment
@app.route('/assignments/<int:assignment_id>/submit', methods=['GET', 'POST'])
@login_required
@check_muted
def submit_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    
    if not assignment.is_active:
        flash('This assignment is not active.', 'danger')
        return redirect(url_for('list_assignments'))
    
    profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
    if not profile or not profile.student_id or not profile.full_name:
        flash('Please complete your profile before submitting assignments.', 'danger')
        return redirect(url_for('student_profile', next=url_for('submit_assignment', assignment_id=assignment_id)))
    
    # Check deadline
    now = datetime.utcnow()
    if assignment.end_date and now > assignment.end_date:
        flash('The submission deadline has passed.', 'danger')
        return redirect(url_for('list_assignments'))
    
    # Check if already submitted
    existing = AssignmentSubmission.query.filter_by(assignment_id=assignment_id, user_id=current_user.id).first()
    if existing:
        flash('You have already submitted this assignment.', 'warning')
        return redirect(url_for('list_assignments'))
    
    if request.method == 'POST':
        content = request.form.get('content', '')
        
        # Handle PDF Upload
        file_path = None
        pdf_file = request.files.get('submission_pdf')
        
        if pdf_file and pdf_file.filename.endswith('.pdf'):
            filename = secure_filename(f"sub_{current_user.id}_{datetime.utcnow().timestamp()}_{pdf_file.filename}")
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            pdf_file.save(filepath)
            file_path = filename
            
            # Extract text for plagiarism check
            try:
                reader = PdfReader(filepath)
                pdf_text = ""
                for page in reader.pages:
                    pdf_text += page.extract_text() + "\n"
                
                if pdf_text.strip():
                    content = pdf_text.strip()
            except Exception as e:
                flash(f'Error extracting text from PDF: {str(e)}', 'warning')
        
        if not content or not content.strip():
            flash('Please provide either text content or a PDF file.', 'danger')
            return redirect(url_for('submit_assignment', assignment_id=assignment_id))
        
        submission = AssignmentSubmission(
            assignment_id=assignment_id,
            student_profile_id=profile.id,
            user_id=current_user.id,
            content=content.strip(),
            file_path=file_path
        )
        db.session.add(submission)
        db.session.commit()
        
        log_action("Assignment Submitted", f"Submitted assignment: {assignment.title}")
        
        flash('Assignment submitted successfully!', 'success')
        return redirect(url_for('list_assignments'))
    
    return render_template('submit_assignment.html', assignment=assignment)

@app.context_processor
def inject_academic_classes():
    try:
        classes = AcademicClass.query.order_by(AcademicClass.name).all()
        return dict(academic_classes=classes)
    except:
        return dict(academic_classes=[])

def ensure_db_schema():
    with app.app_context():
        db.create_all()
        if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite'):
            with db.engine.connect() as conn:
                result = conn.execute(text("PRAGMA table_info(book)"))
                existing_columns = [row[1] for row in result]
                if 'last_read_at' not in existing_columns:
                    conn.execute(text("ALTER TABLE book ADD COLUMN last_read_at DATETIME"))
                if 'is_global' not in existing_columns:
                    conn.execute(text("ALTER TABLE book ADD COLUMN is_global BOOLEAN DEFAULT 0 NOT NULL"))

                result = conn.execute(text("PRAGMA table_info(user)"))
                user_columns = [row[1] for row in result]
                if 'is_admin' not in user_columns:
                    conn.execute(text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"))

                result = conn.execute(text("PRAGMA table_info(evaluation)"))
                eval_columns = [row[1] for row in result]
                if 'source_file' not in eval_columns:
                    conn.execute(text("ALTER TABLE evaluation ADD COLUMN source_file VARCHAR(255)"))

                result = conn.execute(text("PRAGMA table_info(assignment)"))
                assign_columns = [row[1] for row in result]
                if 'file_path' not in assign_columns:
                    conn.execute(text("ALTER TABLE assignment ADD COLUMN file_path VARCHAR(255)"))

                result = conn.execute(text("PRAGMA table_info(assignment_submission)"))
                sub_columns = [row[1] for row in result]
                if 'file_path' not in sub_columns:
                    conn.execute(text("ALTER TABLE assignment_submission ADD COLUMN file_path VARCHAR(255)"))

                result = conn.execute(text("PRAGMA table_info(evaluation_attempt)"))
                attempt_columns = [row[1] for row in result]
                if 'latest_snapshot' not in attempt_columns:
                    conn.execute(text("ALTER TABLE evaluation_attempt ADD COLUMN latest_snapshot TEXT"))
                if 'last_snapshot_time' not in attempt_columns:
                    conn.execute(text("ALTER TABLE evaluation_attempt ADD COLUMN last_snapshot_time DATETIME"))

                result = conn.execute(text("PRAGMA table_info(student_profile)"))
                profile_columns = [row[1] for row in result]
                if 'student_class' not in profile_columns:
                    conn.execute(text("ALTER TABLE student_profile ADD COLUMN student_class VARCHAR(50)"))

                result = conn.execute(text("PRAGMA table_info(book)"))
                book_columns = [row[1] for row in result]
                if 'target_class' not in book_columns:
                    conn.execute(text("ALTER TABLE book ADD COLUMN target_class VARCHAR(50) DEFAULT 'All' NOT NULL"))

                result = conn.execute(text("PRAGMA table_info(evaluation)"))
                eval_cols = [row[1] for row in result]
                if 'target_class' not in eval_cols:
                    conn.execute(text("ALTER TABLE evaluation ADD COLUMN target_class VARCHAR(50) DEFAULT 'All' NOT NULL"))

                result = conn.execute(text("PRAGMA table_info(assignment)"))
                assign_cols = [row[1] for row in result]
                if 'target_class' not in assign_cols:
                    conn.execute(text("ALTER TABLE assignment ADD COLUMN target_class VARCHAR(50) DEFAULT 'All' NOT NULL"))
        else:
            # PostgreSQL fallback
            try:
                db.session.execute(text("ALTER TABLE student_profile ADD COLUMN IF NOT EXISTS student_class VARCHAR(50);"))
            except:
                db.session.rollback()
            try:
                db.session.execute(text("ALTER TABLE book ADD COLUMN IF NOT EXISTS target_class VARCHAR(50) DEFAULT 'All' NOT NULL;"))
            except:
                db.session.rollback()
            try:
                db.session.execute(text("ALTER TABLE evaluation ADD COLUMN IF NOT EXISTS target_class VARCHAR(50) DEFAULT 'All' NOT NULL;"))
            except:
                db.session.rollback()
            try:
                db.session.execute(text("ALTER TABLE assignment ADD COLUMN IF NOT EXISTS target_class VARCHAR(50) DEFAULT 'All' NOT NULL;"))
            except:
                db.session.rollback()
            try:
                db.session.execute(text("ALTER TABLE academic_class ADD COLUMN IF NOT EXISTS course_name VARCHAR(100) DEFAULT 'General' NOT NULL;"))
            except:
                db.session.rollback()
            try:
                db.session.execute(text("ALTER TABLE academic_class ADD COLUMN IF NOT EXISTS level VARCHAR(50) DEFAULT 'General' NOT NULL;"))
            except:
                db.session.rollback()
            db.session.commit()

@app.route('/admin/system_logs')
@login_required
def system_logs():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    logs = SystemLog.query.order_by(SystemLog.created_at.desc()).limit(100).all()
    return render_template('admin_system_logs.html', logs=logs)

if __name__ == '__main__':
    ensure_db_schema()
    app.run(host='127.0.0.1', port=5000, debug=False)