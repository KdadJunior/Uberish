#!/usr/bin/env python3
"""
Flask app for Project 3 - User Management Microservice
Based on Project 1/2 code from pro222
"""

import sqlite3
import os
import hashlib
import hmac
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
db_name = "user.db"
sql_file = "user.sql"
db_flag = False

# Read the secret key from key.txt
with open('key.txt', 'r') as f:
    SECRET_KEY = f.read().strip()

def create_db():
    """Create database from SQL file"""
    conn = sqlite3.connect(db_name)
    
    with open(sql_file, 'r') as sql_startup:
        init_db = sql_startup.read()
    cursor = conn.cursor()
    cursor.executescript(init_db)
    conn.commit()
    conn.close()
    global db_flag
    db_flag = True

def get_db():
    """Get database connection, creating if necessary"""
    if not db_flag:
        create_db()
    conn = sqlite3.connect(db_name)
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password, salt):
    """Hash password using HMAC-SHA256 with key (same as sadeghmo)"""
    salted = salt + password  # salt FIRST, then password
    return hmac.new(SECRET_KEY.encode(), salted.encode(), hashlib.sha256).hexdigest()

def generate_jwt(username):
    """Generate JWT token - payload only contains username (same as Project 2)"""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"username": username}
    
    # Encode header and payload
    header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).decode()
    payload_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    
    # Create signature
    message = f"{header_encoded}.{payload_encoded}"
    signature = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
    
    return f"{header_encoded}.{payload_encoded}.{signature}"

def verify_jwt(token):
    """Verify JWT token and return username if valid"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
            
        header_encoded, payload_encoded, signature = parts
        
        # Verify signature
        message = f"{header_encoded}.{payload_encoded}"
        expected_signature = hmac.new(SECRET_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return None
            
        # Decode payload
        payload = json.loads(base64.urlsafe_b64decode(payload_encoded).decode())
        return payload.get('username')
    except:
        return None

def validate_password(password, username, first_name, last_name):
    """Validate password against requirements"""
    # 1. At least 8 characters
    if len(password) < 8:
        return False
    
    # 2. A lowercase letter
    if not any(c.islower() for c in password):
        return False
    
    # 3. An uppercase letter
    if not any(c.isupper() for c in password):
        return False
    
    # 4. A number
    if not any(c.isdigit() for c in password):
        return False
    
    # 5. No parts of your username
    if username.lower() in password.lower():
        return False
    
    # 6. Does not include your first name
    if first_name.lower() in password.lower():
        return False
    
    # 7. Does not include your last name
    if last_name.lower() in password.lower():
        return False
    
    return True

def get_jwt_from_header():
    """Extract JWT from Authorization header"""
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return None
    return auth_header

def get_post_param(param_name):
    """Robustly extract a POST parameter from form, JSON, or raw body."""
    # 1) Standard form field
    value = request.form.get(param_name)
    if value is not None and value != "":
        return value
    # 2) JSON body
    try:
        json_body = request.get_json(silent=True)
        if isinstance(json_body, dict) and param_name in json_body and json_body[param_name] != "":
            return json_body[param_name]
    except:
        pass
    # 3) URL-encoded raw body fallback
    try:
        from urllib.parse import parse_qs
        raw = request.get_data(as_text=True) or ""
        parsed = parse_qs(raw, keep_blank_values=True)
        if param_name in parsed and len(parsed[param_name]) > 0:
            return parsed[param_name][0]
    except:
        pass
    return None

@app.route('/clear', methods=['GET'])
def clear_db():
    """Clear the database and recreate tables"""
    conn = None
    try:
        global db_flag
        db_flag = False
        
        try:
            if os.path.exists(db_name):
                temp_conn = sqlite3.connect(db_name)
                temp_conn.close()
        except:
            pass
        
        if os.path.exists(db_name):
            os.remove(db_name)
        
        create_db()
        return jsonify({"status": 1})
    except Exception as e:
        if conn:
            try:
                conn.close()
            except:
                pass
        try:
            if os.path.exists(db_name):
                os.remove(db_name)
            db_flag = False
            create_db()
        except:
            pass
        return jsonify({"status": 1})

@app.route('/create_user', methods=['POST'])
def create_user():
    """Create a new user"""
    conn = None
    try:
        first_name = get_post_param('first_name')
        last_name = get_post_param('last_name')
        username = get_post_param('username')
        email_address = get_post_param('email_address')
        password = get_post_param('password')
        salt = get_post_param('salt')
        driver = get_post_param('driver')
        deposit = get_post_param('deposit')
        
        # Validate required fields
        if not all([first_name, last_name, username, email_address, password, salt, deposit]):
            return jsonify({"status": 4, "pass_hash": "NULL"})
        
        # Validate field lengths (max 254 characters)
        if len(first_name) > 254 or len(last_name) > 254 or len(username) > 254 or len(email_address) > 254 or len(password) > 254 or len(salt) > 254:
            return jsonify({"status": 4, "pass_hash": "NULL"})
        
        # Validate password requirements
        if not validate_password(password, username, first_name, last_name):
            return jsonify({"status": 4, "pass_hash": "NULL"})
        
        # Parse driver boolean
        is_driver = False
        if driver:
            if isinstance(driver, str):
                is_driver = driver.lower() in ['true', '1', 'yes']
            else:
                is_driver = bool(driver)
        
        # Validate deposit is a valid float
        try:
            deposit_float = float(deposit)
            if deposit_float < 0:
                return jsonify({"status": 4, "pass_hash": "NULL"})
        except:
            return jsonify({"status": 4, "pass_hash": "NULL"})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if username already exists
        cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"status": 2, "pass_hash": "NULL"})
        
        # Check if email already exists
        cursor.execute("SELECT email_address FROM users WHERE email_address = ?", (email_address,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"status": 3, "pass_hash": "NULL"})
        
        # Hash the password
        pass_hash = hash_password(password, salt)
        
        # Insert user
        cursor.execute("""
            INSERT INTO users (first_name, last_name, username, email_address, pass_hash, salt, is_driver)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (first_name, last_name, username, email_address, pass_hash, salt, 1 if is_driver else 0))
        
        # Get the user ID for password history
        user_id = cursor.lastrowid
        
        # Add password to history table
        cursor.execute("""
            INSERT INTO password_history (user_id, pass_hash)
            VALUES (?, ?)
        """, (user_id, pass_hash))
        
        conn.commit()
        conn.close()
        
        # Initialize balance in payments service
        # Note: In docker, use service name 'payments', locally use localhost
        try:
            payments_url = os.environ.get('PAYMENTS_URL', 'http://payments:5000/initialize')
            requests.post(payments_url, data={'username': username, 'amount': deposit}, timeout=2)
        except:
            # If payments service not available, continue anyway
            pass
        
        return jsonify({"status": 1, "pass_hash": pass_hash})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 4, "pass_hash": "NULL"})

@app.route('/login', methods=['POST'])
def login():
    """Authenticate user and return JWT"""
    conn = None
    try:
        username = get_post_param('username')
        password = get_post_param('password')
        
        if not username or not password:
            return jsonify({"status": 2, "jwt": "NULL"})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get user data
        cursor.execute("SELECT pass_hash, salt FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        
        if not user_data:
            conn.close()
            return jsonify({"status": 2, "jwt": "NULL"})
        
        stored_hash, salt = user_data
        
        # Verify password
        computed_hash = hash_password(password, salt)
        
        if computed_hash != stored_hash:
            conn.close()
            return jsonify({"status": 2, "jwt": "NULL"})
        
        # Generate JWT
        jwt_token = generate_jwt(username)
        
        conn.close()
        return jsonify({"status": 1, "jwt": jwt_token})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "jwt": "NULL"})

@app.route('/rate', methods=['POST'])
def rate():
    """Rate a user (passenger rates driver, driver rates passenger)"""
    conn = None
    try:
        # Get JWT from Authorization header
        jwt_token = get_jwt_from_header()
        if not jwt_token:
            return jsonify({"status": 2})
        
        # Verify JWT
        rater_username = verify_jwt(jwt_token)
        if not rater_username:
            return jsonify({"status": 2})
        
        # Get parameters
        rated_username = get_post_param('username')
        rating = get_post_param('rating')
        
        if not rated_username or not rating:
            return jsonify({"status": 2})
        
        try:
            rating_int = int(rating)
            if rating_int < 0 or rating_int > 5:
                return jsonify({"status": 2})
        except:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get rater info
        cursor.execute("SELECT id, is_driver FROM users WHERE username = ?", (rater_username,))
        rater_data = cursor.fetchone()
        if not rater_data:
            conn.close()
            return jsonify({"status": 2})
        
        rater_id, rater_is_driver = rater_data
        
        # Get rated user info
        cursor.execute("SELECT id, is_driver FROM users WHERE username = ?", (rated_username,))
        rated_data = cursor.fetchone()
        if not rated_data:
            conn.close()
            return jsonify({"status": 2})
        
        rated_id, rated_is_driver = rated_data
        
        # Cannot rate yourself
        if rater_id == rated_id:
            conn.close()
            return jsonify({"status": 2})
        
        # Verify rating rules: passenger can only rate driver, driver can only rate passenger
        if rater_is_driver and rated_is_driver:
            # Driver trying to rate another driver
            conn.close()
            return jsonify({"status": 2})
        
        if not rater_is_driver and not rated_is_driver:
            # Passenger trying to rate another passenger
            conn.close()
            return jsonify({"status": 2})
        
        # Verify they have a confirmed reservation
        # Check with reservations service
        try:
            reservations_url = os.environ.get('RESERVATIONS_URL', 'http://reservations:5000/check_reservation')
            check_response = requests.post(reservations_url, 
                data={'rater': rater_username, 'rated': rated_username},
                headers={'Authorization': jwt_token},
                timeout=2)
            if check_response.status_code != 200 or check_response.json().get('status') != 1:
                conn.close()
                return jsonify({"status": 2})
        except:
            conn.close()
            return jsonify({"status": 2})
        
        # Insert rating
        cursor.execute("""
            INSERT INTO ratings (rater_id, rated_id, rating)
            VALUES (?, ?, ?)
        """, (rater_id, rated_id, rating_int))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

@app.route('/get_user_info', methods=['POST'])
def get_user_info():
    """Internal endpoint for other microservices to get user information"""
    conn = None
    try:
        username = get_post_param('username')
        if not username:
            return jsonify({"status": 2, "is_driver": False, "rating": "0.00"})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get user info
        cursor.execute("SELECT id, is_driver FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        if not user_data:
            conn.close()
            return jsonify({"status": 2, "is_driver": False, "rating": "0.00"})
        
        user_id, is_driver = user_data
        
        # Calculate average rating
        cursor.execute("SELECT AVG(rating) FROM ratings WHERE rated_id = ?", (user_id,))
        rating_result = cursor.fetchone()[0]
        if rating_result is None:
            rating_avg = 0.00
        else:
            rating_avg = float(rating_result)
        
        conn.close()
        
        return jsonify({
            "status": 1,
            "is_driver": bool(is_driver),
            "rating": f"{rating_avg:.2f}"
        })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "is_driver": False, "rating": "0.00"})

@app.route('/get_rating', methods=['POST'])
def get_rating():
    """Internal endpoint to get user rating"""
    conn = None
    try:
        username = get_post_param('username')
        if not username:
            return jsonify({"status": 2, "rating": "0.00"})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get user ID
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        if not user_data:
            conn.close()
            return jsonify({"status": 2, "rating": "0.00"})
        
        user_id = user_data[0]
        
        # Calculate average rating
        cursor.execute("SELECT AVG(rating) FROM ratings WHERE rated_id = ?", (user_id,))
        rating_result = cursor.fetchone()[0]
        if rating_result is None:
            rating_avg = 0.00
        else:
            rating_avg = float(rating_result)
        
        conn.close()
        
        return jsonify({
            "status": 1,
            "rating": f"{rating_avg:.2f}"
        })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "rating": "0.00"})

@app.route('/internal/verify_jwt', methods=['GET'])
def internal_verify_jwt():
    """Internal endpoint for other services to verify JWT tokens"""
    token = request.args.get('token')
    if not token:
        return jsonify({"valid": 0})
    
    username = verify_jwt(token)
    if not username:
        return jsonify({"valid": 0})
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, is_driver FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    
    if not user:
        return jsonify({"valid": 0})
    
    return jsonify({"valid": 1, "username": username, "is_driver": user[1], "user_id": user[0]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

