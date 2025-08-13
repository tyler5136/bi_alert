import os
import json
import requests
from hashlib import md5

BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"
SESSION_FILE = os.path.join(os.path.dirname(__file__), ".bi_session")

def get_bi_session():
    # Try to load existing session
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            session = f.read().strip()
            # Test session
            test_resp = requests.post(f"{BI_HOST}/json", json={"cmd": "status", "session": session})
            if test_resp.ok and test_resp.json().get("result") != "fail":
                return session
            else:
                print("🔁 Session expired. Reauthenticating...")

    # No valid session — do full login
    login_resp = requests.post(f"{BI_HOST}/json", json={"cmd": "login"})
    session = login_resp.json()["session"]
    hashed = md5(f"{BI_USER}:{session}:{BI_PASS}".encode()).hexdigest()
    auth_resp = requests.post(f"{BI_HOST}/json", json={"cmd": "login", "session": session, "response": hashed})
    auth_data = auth_resp.json()

    if auth_data.get("result") == "success":
        session = auth_data["session"]
        with open(SESSION_FILE, "w") as f:
            f.write(session)
        return session
    else:
        raise Exception("❌ Blue Iris login failed")

# Use this in your alert handler
session = get_bi_session()
