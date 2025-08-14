import requests, hashlib, time

BI_HOST = "http://127.0.0.1:8191"
BI_USER = "Tyler"
BI_PASS = "Jasper-0518"
clip_length = 10000 #10 Seconds

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

clips = requests.post(f"{BI_HOST}/json", json={
    "cmd": "cliplist",
    "session": session,
    "camera": "FrontYardDW",
    "startdate": (int(time.time()) - 7200)
})

clip_data = clips.json().get("data", [])
if not clip_data:
    raise Exception("No clips returned")

# Get most recent clip
first_clip = clip_data[0]
clip_path = first_clip["path"]
clip_msec = int(first_clip["msec"])  # 👈 You get it right here
print(clip_path)

exp = requests.post(f"{BI_HOST}/json", json={
    "cmd": "export",
    "session": session,
    "path": clip_path,
    "startms": clip_msec - 10000 if clip_msec > 10000 else 0,
    "msec": 10000,
    "timelapse": "3.0@30.0"
})
print(exp.json())

job_id = exp.json()["data"]["path"]

while True:
    status_resp = requests.post(f"{BI_HOST}/json", json={
        "cmd": "status",
        "session": session,
        "jobid": job_id
    })
    status_data = status_resp.json()

    if status_data.get("data", {}).get("done"):
        clip_uri = status_data["data"]["path"]  # This is your .mp4 path
        print(f"✅ Export complete: {clip_uri}")
        break

    time.sleep(0.5)



jobs = requests.post(f"{BI_HOST}/json", json={
    "cmd": "status",
    "session": session
})
print(jobs.json())




delete_exp = requests.post(f"{BI_HOST}/json", json={
    "cmd": "export",
    "session": session,
    "path": clip_path,
    "delete": "true"
})
print(delete_exp.json())