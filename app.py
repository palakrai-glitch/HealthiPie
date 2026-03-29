from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.objectid import ObjectId # Import ObjectId for deletion
import google.generativeai as genai
import json
import os
import requests # For Barcode API
# ... existing imports ...
from dotenv import load_dotenv
load_dotenv() # Load environment variables from .env file


app = Flask(__name__)
app.secret_key = "super_secret_healthify_key"

# Use ONE line to handle both Cloud and Local connections
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/healthify_db")
client = MongoClient(MONGO_URI)
db = client["healthipie"] # Explicitly naming the database fixes the ConfigError

# --- 🔑 GEMINI AI CONFIGURATION ---
"GEMINI_API_KEY"= os.environ.get("GEMINI_API_KEY")
genai.configure(api_key="GEMINI_API_KEY")

# --- 🛠️ SIMPLE AI MODEL SETUP ---
model = genai.GenerativeModel('gemini-flash-latest')

# Add these lines right here! They fix the red errors below.
logs_collection = db['daily_logs']
users_collection = db['users']
weight_collection = db['weight_history']
workouts_collection = db['workouts']
food_collection = db['food_items']

# --- HELPER ---
def calculate_streak(username):
    dates = logs_collection.find({"user": username}).distinct("date")
    if not dates: return 0
    sorted_dates = sorted([datetime.strptime(d, "%Y-%m-%d") for d in dates], reverse=True)
    streak = 0
    today = datetime.now().date()
    if sorted_dates[0].date() != today and sorted_dates[0].date() != (today - timedelta(days=1)):
        return 0
    current_check = sorted_dates[0].date()
    for d in sorted_dates:
        if d.date() == current_check:
            streak += 1
            current_check -= timedelta(days=1)
        else: break
    return streak

# --- ROUTES ---
@app.route('/')
def home():
    return render_template('home.html')

# 👇👇👇 PASTE THE NEW CODE HERE 👇👇👇

@app.route('/about')
def about():
    # Get the user's name if logged in, otherwise 'Guest'
    name = session.get('name', 'Guest')
    # Render the page and pass the current year for the footer
    return render_template('about.html', name=name, now_year=datetime.now().year)

# 👆👆👆 END OF NEW CODE 👆👆👆

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = users_collection.find_one({"username": request.form.get('username'), "password": request.form.get('password')})
        if user:
            session['username'] = user['username']
            session['name'] = user['name']
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid Credentials")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        if users_collection.find_one({"username": username}):
            return render_template('register.html', error="Username taken")
        try: age=int(request.form.get('age')); height=int(request.form.get('height')); weight=int(request.form.get('weight'))
        except: age=25; height=170; weight=60
        
        users_collection.insert_one({
            "username": username, "password": request.form.get('password'), "name": request.form.get('name'),
            "age": age, "height": height, "weight": weight, "goal": request.form.get('goal')
        })
        weight_collection.insert_one({"user": username, "weight": weight, "date": datetime.now().strftime("%Y-%m-%d")})
        session['username'] = username
        session['name'] = request.form.get('name')
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'username' not in session: return redirect(url_for('login'))
    user = users_collection.find_one({"username": session['username']})
    if request.method == 'POST':
        new_w = int(request.form.get('weight'))
        users_collection.update_one({"username": session['username']}, {"$set": {
            "name": request.form.get('name'), "age": int(request.form.get('age')),
            "height": int(request.form.get('height')), "weight": new_w, "goal": request.form.get('goal')
        }})
        weight_collection.update_one({"user": session['username'], "date": datetime.now().strftime("%Y-%m-%d")}, {"$set": {"weight": new_w}}, upsert=True)
        return redirect(url_for('dashboard'))
    return render_template('profile.html', user=user)

@app.route('/dashboard')
def dashboard():
    if 'username' not in session: return redirect(url_for('login'))
    user = users_collection.find_one({"username": session['username']})
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    logs = list(logs_collection.find({"user": session['username'], "date": today_str}))
    intake = sum(i.get('calories', 0) for i in logs if i['type'] == 'meal')
    burned = sum(abs(i.get('calories', 0)) for i in logs if i['type'] == 'workout')
    net = intake - burned
    macros = {k: sum(i.get(k, 0) for i in logs if i['type'] == 'meal') for k in ['protein', 'carbs', 'fat']}
    water = sum(1 for i in logs if i['type'] == 'water')
    
    h_m = float(user.get('height', 170))/100
    bmi = round(float(user.get('weight', 60)) / (h_m * h_m), 1)
    
    dates_label, intake_data, burned_data = [], [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        dates_label.append((datetime.now() - timedelta(days=i)).strftime("%a"))
        d_logs = list(logs_collection.find({"user": session['username'], "date": d}))
        intake_data.append(sum(x.get('calories', 0) for x in d_logs if x['type'] == 'meal'))
        burned_data.append(sum(abs(x.get('calories', 0)) for x in d_logs if x['type'] == 'workout'))

    w_hist = list(weight_collection.find({"user": session['username']}).sort("date", 1))
    weight_dates, weight_values = [], []
    current_w = user.get('weight', 60)
    for i in range(6, -1, -1):
        d_str = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        entry = next((item for item in w_hist if item["date"] == d_str), None)
        if entry: current_w = entry['weight']
        weight_dates.append((datetime.now() - timedelta(days=i)).strftime("%m-%d"))
        weight_values.append(current_w)

    return render_template('dashboard.html', 
        user=user, logs=logs, net=net, intake=intake, burned=burned,
        protein=macros['protein'], carbs=macros['carbs'], fat=macros['fat'],
        water_count=water, bmi=bmi, streak=calculate_streak(session['username']),
        dates_label=dates_label, intake_data=intake_data, burned_data=burned_data,
        weight_dates=weight_dates, weight_values=weight_values,
        min_weight=min(weight_values)-2 if weight_values else 0,
        max_weight=max(weight_values)+2 if weight_values else 100
    )

@app.route('/add', methods=['GET', 'POST'])
def add_entry():
    if 'username' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        t = request.form.get('type')
        try: cals=int(float(request.form.get('calories',0))); prot=int(float(request.form.get('protein',0))); carb=int(float(request.form.get('carbs',0))); fat=int(float(request.form.get('fat',0)))
        except: cals=0; prot=0; carb=0; fat=0
        if t == 'workout': cals = -abs(cals)
        logs_collection.insert_one({
            "user": session['username'], "type": t, "name": request.form.get('name'),
            "calories": cals, "protein": prot, "carbs": carb, "fat": fat,
            "date": datetime.now().strftime("%Y-%m-%d"), "category": request.form.get('category')
        })
        return redirect(url_for('dashboard'))
    return render_template('tracker.html')

@app.route('/add_water')
def add_water():
    if 'username' not in session: return redirect(url_for('login'))
    logs_collection.insert_one({"user": session['username'], "type": "water", "name": "Water (250ml)", "calories": 0, "protein": 0, "carbs": 0, "fat": 0, "date": datetime.now().strftime("%Y-%m-%d"), "category": "Hydration"})
    return redirect(url_for('dashboard'))

# --- DELETE LOG ENTRY ---
@app.route('/delete_log/<log_id>')
def delete_log(log_id):
    if 'username' not in session: return redirect(url_for('login'))
    logs_collection.delete_one({'_id': ObjectId(log_id)})
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/report')
def report_view():
    if 'username' not in session: return redirect(url_for('login'))
    selected_date = request.args.get('date', datetime.now().strftime("%Y-%m-%d"))
    logs = list(logs_collection.find({"user": session['username'], "date": selected_date}))
    user = users_collection.find_one({"username": session['username']})
    totals = {'calories': 0, 'protein': 0, 'carbs': 0, 'fat': 0, 'burned': 0}
    for log in logs:
        if log['type'] == 'meal':
            totals['calories'] += log.get('calories', 0); totals['protein'] += log.get('protein', 0); totals['carbs'] += log.get('carbs', 0); totals['fat'] += log.get('fat', 0)
        elif log['type'] == 'workout': totals['burned'] += abs(log.get('calories', 0))
    totals['net'] = totals['calories'] - totals['burned']
    return render_template('report.html', logs=logs, user=user, date=selected_date, totals=totals)

@app.route('/plan', methods=['GET', 'POST'])
def plan_view():
    if 'username' not in session: return redirect(url_for('login'))
    user = users_collection.find_one({"username": session['username']})
    plan_data = [] 
    
    if request.method == 'POST':
        pref = request.form.get('preference', 'Balanced')
        suggestions = request.form.get('suggestions', '')
        goal = user.get('goal', 'Maintain')
        
        prompt = f"""
        Generate a 7-day meal plan for goal: {goal}, diet: {pref}.
        USER REQUEST: "{suggestions}".
        Return ONLY a valid JSON Array. Format:
        [{{"day": "Monday", "breakfast": "Food", "lunch": "Food", "dinner": "Food", "workout": "Exercise", "calories": 2000, "protein": 100}}, ...]
        """
        try:
            response = model.generate_content(prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            start = text.find('[')
            end = text.rfind(']') + 1
            if start != -1 and end != -1:
                plan_data = json.loads(text[start:end])
        except Exception as e:
            print(f"Plan Error: {e}")
            plan_data = []

    return render_template('plan.html', user=user, plan=plan_data)

@app.route('/ai_estimate', methods=['POST'])
def ai_estimate():
    data = request.json
    query = data.get('query')
    mode = data.get('mode', 'meal')
    
    if mode == 'meal':
        # UPGRADED PROMPT FOR MICRONUTRIENTS
        prompt = f"""
        Identify food: '{query}'. 
        Return ONLY raw JSON: 
        {{
            "name": "Food Name",
            "calories": int, 
            "protein": int, 
            "carbs": int, 
            "fat": int, 
            "iron": int (mg), 
            "vitamin_c": int (mg), 
            "calcium": int (mg),
            "category": "Food"
        }}. 
        No markdown.
        """
    else:
        prompt = f"""Identify exercise: '{query}' (30 mins). Return ONLY raw JSON: {{"calories": int, "category": "Exercise"}}. No markdown."""

    try:
        response = model.generate_content(prompt)
        text = response.text
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != -1:
            result = json.loads(text[start:end])
            return jsonify(result)
        else: return jsonify({"error": "AI could not understand."})
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"error": "AI connection failed."})

# --- 🚀 CHAT API (WITH DASHBOARD AWARENESS) ---
@app.route('/chat_api', methods=['POST'])
def chat_api():
    if 'username' not in session: return jsonify({"reply": "Login first."})
    data = request.json
    user = users_collection.find_one({"username": session['username']})
    
    # 1. Fetch Today's Stats to give AI context
    today_str = datetime.now().strftime("%Y-%m-%d")
    logs = list(logs_collection.find({"user": session['username'], "date": today_str}))
    intake = sum(i.get('calories', 0) for i in logs if i['type'] == 'meal')
    burned = sum(abs(i.get('calories', 0)) for i in logs if i['type'] == 'workout')
    water = sum(1 for i in logs if i['type'] == 'water')
    
    # 2. Build Contextual Prompt
    context_prompt = f"""
    You are HealthBot, a smart health coach. 
    User: {user['name']}. Goal: {user['goal']}.
    TODAY'S DASHBOARD: Eaten: {intake} cals, Burned: {burned} cals, Water: {water} glasses.
    USER QUESTION: "{data.get('message')}"
    Answer the user. You can analyze their dashboard stats if asked, or answer any general health question.
    Keep it helpful and concise.
    """

    try:
        res = model.generate_content(context_prompt)
        return jsonify({"reply": res.text})
    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({"reply": "I'm having trouble thinking right now."})

@app.route('/get_workouts')
def get_w(): return jsonify(list(workouts_collection.find({},{"_id":0})))
@app.route('/get_foods')
def get_f(): return jsonify(list(food_collection.find({},{"_id":0})))
# --- 🆕 PAGE ROUTES ---
@app.route('/medical')
def medical_page():
    if 'username' not in session: return redirect(url_for('login'))
    return render_template('medical.html', user=users_collection.find_one({"username": session['username']}))

@app.route('/fridge')
def fridge_page():
    if 'username' not in session: return redirect(url_for('login'))
    return render_template('fridge.html', user=users_collection.find_one({"username": session['username']}))

# --- 🆕 API: FOOD IMAGE ANALYSIS (For Tracker) ---
@app.route('/analyze_food_image', methods=['POST'])
def analyze_food_image():
    if 'image' not in request.files: return jsonify({"error": "No image"})
    file = request.files['image']
    img_data = file.read()
    
    prompt = """
    Identify the food in this image.
    Return ONLY raw JSON: 
    {
        "name": "Food Name",
        "calories": int, 
        "protein": int, 
        "carbs": int, 
        "fat": int
    }
    """
    try:
        vision_model = genai.GenerativeModel('gemini-1.5-flash')
        response = vision_model.generate_content([prompt, {"mime_type": file.mimetype, "data": img_data}])
        text = response.text.replace("```json", "").replace("```", "").strip()
        return jsonify(json.loads(text))
    except: return jsonify({"error": "Could not identify food"})

if __name__ == '__main__':
    app.run(debug=True, port=5002)