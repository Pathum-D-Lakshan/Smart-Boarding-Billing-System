from flask import Flask, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error, errorcode
from db import get_db_connection
app = Flask(__name__)

@app.route("/")
def home():
 return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            return "Enter your email and password.", 400

        try:
            with get_db_connection() as connection:
                with connection.cursor(dictionary=True) as cursor:
                    cursor.execute(
                        """
                        SELECT password_hash
                        FROM users
                        WHERE email = %s AND is_active = TRUE
                        """,
                        (email,),
                    )
                    user = cursor.fetchone()
        except Error as error:
            app.logger.error("Login database error (%s)", error.errno)
            return "Could not check your login details.", 500

        if user is None or not check_password_hash(user["password_hash"], password):
            return "Invalid email or password.", 400

        return "Login credentials verified."

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email","").strip()
        print("Received email:", email)
        full_name = request.form.get("full_name","").strip()
        role = request.form.get("role")

        print("Received name:", full_name)
        print("Received role:", role)
        if role not in ("student", "owner"):
            return "Choose Student or Boarding Owner.", 400
        if not full_name or not email:
            return "Enter your full name and email.", 400
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password or not confirm_password:
            return "Enter both passwords.", 400

        if password != confirm_password:
            return "Passwords do not match.", 400

        password_hash = generate_password_hash(password)
        try:
            with get_db_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO users (full_name, email, role, password_hash)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (full_name, email, role, password_hash),
                    )
                connection.commit()
        except Error as error:
            if error.errno == errorcode.ER_DUP_ENTRY:
                return "That email is already registered.", 409

            app.logger.error("Registration database error (%s)", error.errno)
            return "Could not create the account.", 500

        return "Account created.", 201
    return render_template("register.html")