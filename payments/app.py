#!/usr/bin/env python3
"""
Flask app for Project 3 - Payments Microservice
"""

import sqlite3
import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
db_name = "payments.db"
sql_file = "payments.sql"
db_flag = False

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
    return conn

def verify_token(token):
    """Verify JWT token by calling user service"""
    try:
        resp = requests.get('http://user:5000/internal/verify_jwt', params={'token': token}, timeout=2)
        return resp.json()
    except:
        return {"valid": 0}

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

@app.route('/initialize', methods=['POST'])
def initialize():
    """Internal endpoint to initialize user balance (called by user service)"""
    conn = None
    try:
        username = get_post_param('username')
        amount = get_post_param('amount')
        
        if not username or not amount:
            return jsonify({"status": 2})
        
        try:
            amount_float = float(amount)
            if amount_float < 0:
                return jsonify({"status": 2})
        except:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Insert or update balance
        cursor.execute("""
            INSERT OR REPLACE INTO balances (username, balance)
            VALUES (?, ?)
        """, (username, amount_float))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

@app.route('/add', methods=['POST'])
def add_money():
    """Add money to user's account"""
    conn = None
    try:
        # Get JWT from Authorization header
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"status": 2})
        
        # Verify JWT by calling user service
        auth = verify_token(token)
        if auth.get('valid') != 1:
            return jsonify({"status": 2})
        
        username = auth.get('username')
        
        # Get amount
        amount = get_post_param('amount')
        if not amount:
            return jsonify({"status": 2})
        
        try:
            amount_float = float(amount)
            if amount_float < 0:
                return jsonify({"status": 2})
        except:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get current balance
        cursor.execute("SELECT balance FROM balances WHERE username = ?", (username,))
        balance_data = cursor.fetchone()
        
        if balance_data:
            new_balance = balance_data[0] + amount_float
            cursor.execute("UPDATE balances SET balance = ? WHERE username = ?", (new_balance, username))
        else:
            # Initialize balance if doesn't exist
            cursor.execute("INSERT INTO balances (username, balance) VALUES (?, ?)", (username, amount_float))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

@app.route('/view', methods=['GET'])
def view_balance():
    """View user's current balance"""
    conn = None
    try:
        # Get JWT from Authorization header
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"status": 2, "balance": "NULL"})
        
        # Verify JWT by calling user service
        auth = verify_token(token)
        if auth.get('valid') != 1:
            return jsonify({"status": 2, "balance": "NULL"})
        
        username = auth.get('username')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get balance
        cursor.execute("SELECT balance FROM balances WHERE username = ?", (username,))
        balance_data = cursor.fetchone()
        
        if balance_data:
            balance = balance_data[0]
            conn.close()
            return jsonify({
                "status": 1,
                "balance": f"{balance:.2f}"
            })
        else:
            conn.close()
            return jsonify({
                "status": 1,
                "balance": "0.00"
            })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "balance": "NULL"})

@app.route('/check_balance', methods=['POST'])
def check_balance():
    """Internal endpoint to check if user has enough balance"""
    conn = None
    try:
        username = get_post_param('username')
        amount = get_post_param('amount')
        
        if not username or not amount:
            return jsonify({"status": 2, "has_enough": False})
        
        try:
            amount_float = float(amount)
        except:
            return jsonify({"status": 2, "has_enough": False})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get balance
        cursor.execute("SELECT balance FROM balances WHERE username = ?", (username,))
        balance_data = cursor.fetchone()
        
        if not balance_data:
            conn.close()
            return jsonify({"status": 2, "has_enough": False})
        
        balance = balance_data[0]
        has_enough = balance >= amount_float
        
        conn.close()
        return jsonify({
            "status": 1,
            "has_enough": has_enough,
            "balance": balance
        })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "has_enough": False})

@app.route('/transfer', methods=['POST'])
def transfer():
    """Internal endpoint to transfer money from one user to another"""
    conn = None
    try:
        from_username = get_post_param('from_username')
        to_username = get_post_param('to_username')
        amount = get_post_param('amount')
        
        if not from_username or not to_username or not amount:
            return jsonify({"status": 2})
        
        try:
            amount_float = float(amount)
            if amount_float < 0:
                return jsonify({"status": 2})
        except:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get from user balance
        cursor.execute("SELECT balance FROM balances WHERE username = ?", (from_username,))
        from_balance_data = cursor.fetchone()
        
        if not from_balance_data:
            conn.close()
            return jsonify({"status": 2})
        
        from_balance = from_balance_data[0]
        
        if from_balance < amount_float:
            conn.close()
            return jsonify({"status": 2})
        
        # Deduct from sender
        new_from_balance = from_balance - amount_float
        cursor.execute("UPDATE balances SET balance = ? WHERE username = ?", (new_from_balance, from_username))
        
        # Add to receiver
        cursor.execute("SELECT balance FROM balances WHERE username = ?", (to_username,))
        to_balance_data = cursor.fetchone()
        
        if to_balance_data:
            new_to_balance = to_balance_data[0] + amount_float
            cursor.execute("UPDATE balances SET balance = ? WHERE username = ?", (new_to_balance, to_username))
        else:
            cursor.execute("INSERT INTO balances (username, balance) VALUES (?, ?)", (to_username, amount_float))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

