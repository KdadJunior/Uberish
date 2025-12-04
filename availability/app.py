#!/usr/bin/env python3
"""
Flask app for Project 3 - Driver Availability Microservice
"""

import sqlite3
import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
db_name = "listings.db"
sql_file = "listings.sql"
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

@app.route('/listing', methods=['POST'])
def create_listing():
    """Create a driver availability listing"""
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
        if auth.get('is_driver') != 1:
            return jsonify({"status": 2})
        
        username = auth.get('username')
        
        # Get parameters
        day = get_post_param('day')
        price = get_post_param('price')
        listingid = get_post_param('listingid')
        
        if not day or not price or not listingid:
            return jsonify({"status": 2})
        
        # Validate day is a valid day of week
        valid_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        if day not in valid_days:
            return jsonify({"status": 2})
        
        # Validate price
        try:
            price_float = float(price)
            if price_float < 0:
                return jsonify({"status": 2})
        except:
            return jsonify({"status": 2})
        
        # Validate listingid
        try:
            listingid_int = int(listingid)
        except:
            return jsonify({"status": 2})
        
        # Verify user is a driver by calling user service
        try:
            user_url = os.environ.get('USER_URL', 'http://user:5000/get_user_info')
            user_response = requests.post(user_url, data={'username': username}, timeout=2)
            if user_response.status_code != 200:
                return jsonify({"status": 2})
            user_data = user_response.json()
            if user_data.get('status') != 1 or not user_data.get('is_driver'):
                return jsonify({"status": 2})
        except:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Check if listingid already exists
        cursor.execute("SELECT listingid FROM listings WHERE listingid = ?", (listingid_int,))
        if cursor.fetchone():
            conn.close()
            return jsonify({"status": 2})
        
        # Insert listing
        cursor.execute("""
            INSERT INTO listings (listingid, driver_username, day, price)
            VALUES (?, ?, ?, ?)
        """, (listingid_int, username, day, price_float))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

@app.route('/search', methods=['GET'])
def search_listings():
    """Search for driver availabilities by day"""
    conn = None
    try:
        # Get JWT from Authorization header
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"status": 2, "data": []})
        
        # Verify JWT by calling user service
        auth = verify_token(token)
        if auth.get('valid') != 1:
            return jsonify({"status": 2, "data": []})
        if auth.get('is_driver') != 0:
            return jsonify({"status": 2, "data": []})
        
        username = auth.get('username')
        
        # Get day parameter
        day = request.args.get('day')
        if not day:
            return jsonify({"status": 2, "data": []})
        
        # Validate day
        valid_days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        if day not in valid_days:
            return jsonify({"status": 2, "data": []})
        
        conn = get_db()
        cursor = conn.cursor()
        
        # Get all listings for the day
        cursor.execute("""
            SELECT listingid, price, driver_username
            FROM listings
            WHERE day = ?
            ORDER BY listingid
        """, (day,))
        
        listings = cursor.fetchall()
        
        # Build response with ratings
        result_data = []
        for listing in listings:
            listingid, price, driver_username = listing
            
            # Get driver rating from user service
            rating = "0.00"
            try:
                user_url = os.environ.get('USER_URL', 'http://user:5000/get_rating')
                rating_response = requests.post(user_url, data={'username': driver_username}, timeout=2)
                if rating_response.status_code == 200:
                    rating_data = rating_response.json()
                    if rating_data.get('status') == 1:
                        rating = rating_data.get('rating', '0.00')
            except:
                pass
            
            result_data.append({
                "listingid": listingid,
                "price": f"{price:.2f}",
                "driver": driver_username,
                "rating": rating
            })
        
        conn.close()
        
        return jsonify({
            "status": 1,
            "data": result_data
        })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "data": []})

@app.route('/get_listing', methods=['POST'])
def get_listing():
    """Internal endpoint to get listing information"""
    conn = None
    try:
        listingid = get_post_param('listingid')
        if not listingid:
            return jsonify({"status": 2, "day": None, "price": None, "driver": None})
        
        try:
            listingid_int = int(listingid)
        except:
            return jsonify({"status": 2, "day": None, "price": None, "driver": None})
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT day, price, driver_username
            FROM listings
            WHERE listingid = ?
        """, (listingid_int,))
        
        listing_data = cursor.fetchone()
        if not listing_data:
            conn.close()
            return jsonify({"status": 2, "day": None, "price": None, "driver": None})
        
        day, price, driver = listing_data
        conn.close()
        
        return jsonify({
            "status": 1,
            "day": day,
            "price": f"{price:.2f}",
            "driver": driver
        })
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2, "day": None, "price": None, "driver": None})

@app.route('/delete_listing', methods=['POST'])
def delete_listing():
    """Internal endpoint to delete a listing"""
    conn = None
    try:
        listingid = get_post_param('listingid')
        if not listingid:
            return jsonify({"status": 2})
        
        try:
            listingid_int = int(listingid)
        except:
            return jsonify({"status": 2})
        
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM listings WHERE listingid = ?", (listingid_int,))
        
        conn.commit()
        conn.close()
        
        return jsonify({"status": 1})
        
    except Exception as e:
        if conn:
            conn.close()
        return jsonify({"status": 2})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)

