import os 
import psycopg2
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from dotenv import load_dotenv
import urllib.parse as up
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_bcrypt import Bcrypt

app = Flask(__name__)
load_dotenv()
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

bcrypt = Bcrypt(app)
app.secret_key = 'your_secret_key_here'  # Replace with a secure key
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

def fetch_book_info(google_books_id):
    url = f"https://www.googleapis.com/books/v1/volumes/{google_books_id}"
    if GOOGLE_BOOKS_API_KEY:
        url += f"?key={GOOGLE_BOOKS_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

up.uses_netloc.append("postgres")
DATABASE_URL = os.environ.get("DATABASE_URL")
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

@app.route("/")
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, google_books_id, status FROM books WHERE user_id = %s ORDER BY id;", (session['user_id'],))
    raw_books = cur.fetchall()
    cur.close()
    conn.close()

    books = []
    for id, google_books_id, status in raw_books:
        book_info = fetch_book_info(google_books_id)
        if book_info:
            volume = book_info.get("volumeInfo", {})
            books.append({
                "id": id,
                "google_books_id": google_books_id,
                "status": status,
                "title": volume.get("title", "Unknown Title"),
                "author": ", ".join(volume.get("authors", [])) if volume.get("authors") else "Unknown Author",
            })
    return render_template("index.html", books=books)

@app.route('/book/<google_books_id>')
def book_details(google_books_id):
    book_info = fetch_book_info(google_books_id)
    if not book_info:
        return "Book not found", 404

    volume = book_info.get("volumeInfo", {})
    return render_template("book_details.html", book=volume, id=google_books_id)

@app.route('/save/<google_books_id>', methods=['POST'])
def save_book(google_books_id):
    if 'user_id' not in session:
        flash("You must be logged in to save books.", "warning")
        return redirect(url_for('login'))

    status = request.form.get("status", "to-read")  # Default status
    user_id = session['user_id']

    conn = get_db_connection()
    cur = conn.cursor()

    # Prevent duplicate entries per user
    cur.execute("SELECT 1 FROM books WHERE google_books_id = %s AND user_id = %s", (google_books_id, user_id))
    exists = cur.fetchone()

    if not exists:
        cur.execute(
            "INSERT INTO books (google_books_id, status, user_id) VALUES (%s, %s, %s)",
            (google_books_id, status, user_id)
        )
        conn.commit()

    cur.close()
    conn.close()
    flash("Book saved to your reading list!", "success")
    return redirect(url_for("home"))

@app.route("/add", methods=["POST"])
def add_book():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    google_books_id = request.form["google_books_id"]
    status = request.form["status"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM books WHERE google_books_id = %s AND user_id = %s", (google_books_id, session['user_id']))
    exists = cur.fetchone()

    if not exists:
        cur.execute("INSERT INTO books (google_books_id, status, user_id) VALUES (%s, %s, %s)",
                    (google_books_id, status, session['user_id']))
        conn.commit()

    cur.close()
    conn.close()
    return redirect(url_for("home"))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        status = request.form['status']
        cur.execute("UPDATE books SET status=%s WHERE id=%s AND user_id=%s;", (status, id, session['user_id']))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('home'))

    cur.execute("SELECT google_books_id, status FROM books WHERE id=%s AND user_id=%s;", (id, session['user_id']))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return "Book not found", 404

    google_books_id, status = row
    book_info = fetch_book_info(google_books_id)
    return render_template('edit.html', book=book_info, status=status, id=id)

@app.route('/delete/<int:id>')
def delete(id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM books WHERE id=%s AND user_id=%s;", (id, session['user_id']))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('home'))

@app.route("/search")
def search_books():
    query = request.args.get("query")
    if not query:
        return "No search query provided.", 400

    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": query}
    if GOOGLE_BOOKS_API_KEY:
        params["key"] = GOOGLE_BOOKS_API_KEY

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return f"API Error: {response.status_code}", 500

    data = response.json()
    books = data.get("items", [])
    return render_template("search_results.html", books=books, query=query)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            return 'Username already exists'

        new_user = User(username=username)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            return redirect(url_for('home'))

        return 'Invalid credentials'

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)