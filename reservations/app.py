#!/usr/bin/env python3
"""
Flask app for Project 3 - Reservations Microservice
"""

import sqlite3
import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
db_name = "reservations.db"
sql_file = "reservations.sql"
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

@app.route('/reserve', methods=['POST'])
def make_reservation():
    """Make a ride sharing reservation"""
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
        if auth.get('is_driver') != 0:
            return jsonify({"status": 3})
        
        username = auth.get('username')
        
        # Get listingid
        listingid = get_post_param('listingid')
        if not listingid:
            return jsonify({"status": 3})
        
        try:
            listingid_int = int(listingid)
        except:
            return jsonify({"status": 3})
        
        # Get listing information from availability service
        try:
            availability_url = os.environ.get('AVAILABILITY_URL', 'http://availability:5000/get_listing')
            listing_response = requests.post(availability_url, data={'listingid': listingid}, timeout=2)
            if listing_response.status_code != 200:
                return jsonify({"status": 3})
            listing_data = listing_response.json()
            if listing_data.get('status') != 1:
                return jsonify({"status": 3})
            
            driver_username = listing_data.get('driver')
            price_str = listing_data.get('price')
            
            if not driver_username or not price_str:
                return jsonify({"status": 3})
            
            price_float = float(price_str)
        except:
            return jsonify({"status": 3})
        
        # Check if passenger has enough balance
        try:
            payments_url = os.environ.get('PAYMENTS_URL', 'http://payments:5000/check_balance')
            balance_response = requests.post(payments_url, data={'username': username, 'amount': price_str}, timeout=2)
            if balance_response.status_code != 200:
                return jsonify({"status": 3})
            balance_data = balance_response.json()
            if balance_data.get('status') != 1 or not balance_data.get('has_enough'):
                return jsonify({"status": 3})
        except:
            return jsonify({"status": 3})
        
        # Transfer money from passenger to driver
        try:
            payments_url = os.environ.get('PAYMENTS_URL', 'http://payments:5000/transfer')
            transfer_response = requests.post(payments_url, 
                data={'from_username': username, 'to_username': driver_username, 'amount': price_str}, 
                timeout=2)
            if transfer_response.status_code != 200 or transfer_response.json().get('status') != 1:
                return jsonify({"status": 3})
        except:
            return jsonify({"status": 3})
        
        # Delete the listing from availability service
        try:
            availability_url = os.environ.get('AVAILABILITY_URL', 'http://availability:5000/delete_listing')
            delete_response = requests.post(availability_url, data={'listingid': listingid}, timeout=2)
            # Continue even if delete fails
        except:
            pass
        
        # Create reservation
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO reservations (listingid, passenger_username, driver_username, price)
            VALUES (?, ?, ?, ?)
        """, (listingid_int, username, driver_username, price_float))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 3})

@app.route('/view', methods=['GET'])
def view_reservation():
    """View latest reservation for driver or passenger"""
    conn = None
    try:
        # Get JWT from Authorization header
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"status": 2, "data": "NULL"})
        
        # Verify JWT by calling user service
        auth = verify_token(token)
        if auth.get('valid') != 1:
            return jsonify({"status": 2, "data": "NULL"})
        
        username = auth.get('username')
        is_driver = auth.get('is_driver')
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get latest reservation
        if is_driver:
            cursor.execute("""
                SELECT listingid, price, passenger_username
                FROM reservations
                WHERE driver_username = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """, (username,))
        else:
            cursor.execute("""
                SELECT listingid, price, driver_username
                FROM reservations
                WHERE passenger_username = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            """, (username,))
        
        reservation_data = cursor.fetchone()
        
        if not reservation_data:
            conn.close()
            return jsonify({"status": 2, "data": "NULL"})
        
        listingid, price, other_username = reservation_data
        
        # Get rating for the other user
        rating = "0.00"
        try:
            user_url = os.environ.get('USER_URL', 'http://user:5000/get_rating')
            rating_response = requests.post(user_url, data={'username': other_username}, timeout=2)
            if rating_response.status_code == 200:
                rating_data = rating_response.json()
                if rating_data.get('status') == 1:
                    rating = rating_data.get('rating', '0.00')
        except:
            pass
        
        conn.close()
        
        return jsonify({
            "status": 1,
            "data": {
                "listingid": listingid,
                "price": f"{price:.2f}",
                "user": other_username,
                "rating": rating
            }
        })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "data": "NULL"})

@app.route('/check_reservation', methods=['POST'])
def check_reservation():
    """Internal endpoint to check if a reservation exists between two users"""
    conn = None
    try:
        rater = get_post_param('rater')
        rated = get_post_param('rated')
        
        if not rater or not rated:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if reservation exists (either direction)
        cursor.execute("""
            SELECT id FROM reservations
            WHERE (passenger_username = ? AND driver_username = ?)
            OR (passenger_username = ? AND driver_username = ?)
            LIMIT 1
        """, (rater, rated, rated, rater))
        
        reservation = cursor.fetchone()
        conn.close()
        
        if reservation:
            return jsonify({"status": 1})
        else:
            return jsonify({"status": 2})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

