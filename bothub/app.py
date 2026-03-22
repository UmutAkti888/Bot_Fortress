# app.py — The entry point of our Flask application.

# render_template is a Flask function that:
# 1. Finds the HTML file inside the /templates folder
# 2. Processes any Jinja2 tags ({% %} and {{ }}) in it
# 3. Returns the final HTML string to send to the browser
from flask import Flask, render_template

app = Flask(__name__)


# Route: GET /
# Renders the dashboard homepage (index.html)
@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)
