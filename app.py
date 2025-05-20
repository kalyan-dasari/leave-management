from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime
from flask_mail import Mail, Message
from flask import session
from dotenv import load_dotenv
import os
load_dotenv()


app = Flask(__name__)
load_dotenv()

app.secret_key = 'mrce@CSM'  # Replace with a strong secret

# mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')  # Use App Password from Gmail

mail = Mail(app)

# Initialize DB
def init_db():
    conn = sqlite3.connect('leaves.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS leaves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                branch TEXT,
                date TEXT,
                reason TEXT,
                submitted_on TEXT,
                status TEXT DEFAULT 'Pending'
            )''')

    conn.commit()
    conn.close()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    name = request.form['name']
    email = request.form['email']
    branch = request.form['branch']
    date = request.form['date']
    reason = request.form['reason']
    submitted_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect('leaves.db')
    c = conn.cursor()
    c.execute("""
        INSERT INTO leaves (name, email, branch, date, reason, submitted_on)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, email, branch, date, reason, submitted_on))
    conn.commit()
    conn.close()
    return render_template('submit.html', name=name)

@app.route('/admin')
def admin():
    if not session.get('admin'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('leaves.db')
    c = conn.cursor()
    c.execute("SELECT * FROM leaves ORDER BY submitted_on DESC")
    leaves = c.fetchall()
    conn.close()
    return render_template('admin.html', leaves=leaves)


@app.route('/update_status', methods=['POST'])
def update_status():
    leave_id = request.form['id']
    new_status = request.form['status']

    conn = sqlite3.connect('leaves.db')
    c = conn.cursor()
    c.execute("UPDATE leaves SET status = ? WHERE id = ?", (new_status, leave_id))
    conn.commit()

    # Fetch email and name to notify
    c.execute("SELECT name, email FROM leaves WHERE id = ?", (leave_id,))
    result = c.fetchone()
    conn.close()

    name, email = result
    subject = f"Leave Request {new_status}"
    body = f"Hello {name},\n\nYour leave request has been {new_status.lower()} by the class incharge.\n\nThank you."

    msg = Message(subject, recipients=[email], body=body, sender=app.config['MAIL_USERNAME'])
    mail.send(msg)

    return redirect(url_for('admin'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin123':
            session['admin'] = True
            return redirect(url_for('admin'))
        else:
            return "Invalid credentials", 403
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('login'))


@app.route('/status', methods=['GET', 'POST'])
def status():
    leaves = []
    if request.method == 'POST':
        email = request.form['email']
        conn = sqlite3.connect('leaves.db')
        c = conn.cursor()
        c.execute("SELECT * FROM leaves WHERE email = ?", (email,))
        leaves = c.fetchall()
        conn.close()
    return render_template('status.html', leaves=leaves)


# if __name__ == '__main__':
#     init_db()
#     app.run(host='0.0.0.0', port=int(environ.get("PORT", 5000)))
if __name__ == "__main__":
    from os import environ
    app.run(host='0.0.0.0', port=int(environ.get("PORT", 5000)))

