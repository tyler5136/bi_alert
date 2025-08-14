import requests, hashlib

BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"

# Step 1
r1 = requests.post(f"{BI_HOST}/json", json={"cmd": "login"})
session = r1.json()["session"]

# Step 2
resp = f"{BI_USER}:{session}:{BI_PASS}".encode()
rhash = hashlib.md5(resp).hexdigest()

r2 = requests.post(f"{BI_HOST}/json", json={
    "cmd": "login",
    "session": session,
    "response": rhash
})
print(r2.json())