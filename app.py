import psycopg2
from flask import Flask, render_template, request, redirect, url_for
import os 
from dotenv import load_dotenv
import requests
import urllib.parse as up

def fetch_book_info(google_books_id):
    url = f"https://www.googleapis.com/books/v1/volumes/{google_books_id}"
    if GOOGLE_BOOKS_API_KEY:
        url += f"?key={GOOGLE_BOOKS_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    return None

app = Flask(__name__)

load_dotenv()
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")
# In-memory book list to start (we'll use a database later)
books = []

up.uses_netloc.append("postgres")
DATABASE_URL = os.environ.get("DATABASE_URL")
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

@app.route("/")
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, google_books_id, status FROM books ORDER BY id;")
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

@app.route("/add", methods=["POST"])
def add_book():
    google_books_id = request.form["google_books_id"]
    status = request.form["status"]

    conn = get_db_connection()
    cur = conn.cursor()

    # Prevent duplicate entries
    cur.execute("SELECT 1 FROM books WHERE google_books_id = %s", (google_books_id,))
    exists = cur.fetchone()

    if not exists:
        cur.execute("INSERT INTO books (google_books_id, status) VALUES (%s, %s)",
                    (google_books_id, status))
        conn.commit()

    cur.close()
    conn.close()
    return redirect(url_for("index"))

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        status = request.form['status']
        cur.execute("UPDATE books SET status=%s WHERE id=%s;", (status, id))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('index'))

    # Fetch google_books_id from the DB
    cur.execute("SELECT google_books_id, status FROM books WHERE id=%s;", (id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return "Book not found", 404

    google_books_id, status = row

    # Fetch book info from Google Books API
    book_info = fetch_book_info(google_books_id)

    return render_template('edit.html', book=book_info, status=status, id=id)


@app.route('/delete/<int:id>')
def delete(id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM books WHERE id=%s;", (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

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

if __name__ == '__main__':
    app.run(debug=True)