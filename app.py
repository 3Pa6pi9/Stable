import sqlite3
import os
from functools import wraps
from flask import Flask, request, render_template, redirect, url_for, session, flash, g, jsonify

app = Flask(__name__)
app.secret_key = 'super_secret_development_key'

# Vercel needs to write to the /tmp directory for SQLite to work temporarily
DATABASE = '/tmp/users.db' if os.environ.get('VERCEL') else 'users.db'

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
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        admin = db.execute('SELECT * FROM users WHERE username = ?', ('admin',)).fetchone()
        if not admin:
            db.execute('INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                       ('admin', 'adminpass', 1))
            
        app_name = db.execute('SELECT * FROM settings WHERE key = ?', ('app_name',)).fetchone()
        if not app_name:
            db.execute('INSERT INTO settings (key, value) VALUES (?, ?)', ('app_name', 'phyproj'))
            
        db.commit()

def get_app_name():
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = 'app_name'").fetchone()
    return row['value'] if row else 'phyproj'

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or not session.get('is_admin'):
            flash("Administrator access required.")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def login():
    if 'user_id' in session:
        return redirect(url_for('admin') if session.get('is_admin') else url_for('dashboard'))
    return render_template('login.html', app_name=get_app_name())

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '')
    password = data.get('password', '')
    
    user = get_db().execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    
    if user and user['password'] == password:
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['is_admin'] = bool(user['is_admin'])
        return jsonify({'success': True, 'redirect': url_for('admin') if user['is_admin'] else url_for('dashboard')})
    return jsonify({'success': False, 'error': 'Invalid credentials.'})

@app.route('/register')
def register_page():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html', app_name=get_app_name())

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required.'})
    
    db = get_db()
    existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if existing:
        return jsonify({'success': False, 'error': 'Username already exists.'})
    
    db.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, password))
    db.commit()
    return jsonify({'success': True, 'redirect': url_for('login')})

@app.route('/dashboard')
@login_required
def dashboard():
    if session.get('is_admin'):
        return redirect(url_for('admin'))
    return render_template('dashboard.html', username=session['username'], app_name=get_app_name())

@app.route('/admin')
@admin_required
def admin():
    users = get_db().execute('SELECT id, username, password, is_admin FROM users').fetchall()
    flash_message = request.args.get('flash', None)
    return render_template('admin.html', users=users, flash_message=flash_message, app_name=get_app_name())

@app.route('/admin/settings', methods=['POST'])
@admin_required
def update_settings():
    new_name = request.form.get('app_name', '').strip()
    if new_name:
        db = get_db()
        db.execute("UPDATE settings SET value = ? WHERE key = 'app_name'", (new_name,))
        db.commit()
        return redirect(url_for('admin', flash='App name updated successfully.'))
    return redirect(url_for('admin', flash='App name cannot be empty.'))

@app.route('/delete/<int:user_id>', methods=['POST'])
@admin_required
def delete_user(user_id):
    db = get_db()
    if user_id != session['user_id']:
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        return redirect(url_for('admin', flash='User successfully deleted.'))
    return redirect(url_for('admin', flash='Cannot delete your own account.'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Ensure DB is initialized before first request
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)