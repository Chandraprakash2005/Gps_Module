from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests, math, threading, time, pyttsx3

app = Flask(__name__)
CORS(app)

# ================= CONFIG =================
MAPBOX_TOKEN = "pk.eyJ1IjoibWF5dXJrcyIsImEiOiJjbWpoZmF5cTQwcTZzM2RxdmZkeGc4aXRvIn0.w53nwvcH9lLU_bx9aoiVZw"
PI_ROUTE_URL = "http://10.177.21.229:5000/route"
PI_STOP_URL  = "http://10.177.21.229:5000/stop"
PI_SPEED_URL = "http://10.177.21.229:5000/speed"

REROUTE_THRESHOLD = 12   # meters
HEADING_THRESHOLD = 60  # degrees

# ================= VOICE =================
tts = pyttsx3.init()
def speak(txt):
    try:
        tts.say(txt)
        tts.runAndWait()
    except:
        pass

# ================= STATE =================
current_gps = None
last_gps = None
gps_buffer = []

route_geometry = []
active_waypoints = []
current_index = 0
current_destination = None
last_reroute = 0

# ================= GEO =================

def haversine(a, b):
    R = 6371000
    lat1, lon1 = math.radians(a[1]), math.radians(a[0])
    lat2, lon2 = math.radians(b[1]), math.radians(b[0])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    x = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.atan2(math.sqrt(x), math.sqrt(1-x))

def bearing(a, b):
    lat1, lon1 = math.radians(a[1]), math.radians(a[0])
    lat2, lon2 = math.radians(b[1]), math.radians(b[0])
    dlon = lon2 - lon1
    x = math.sin(dlon)*math.cos(lat2)
    y = math.cos(lat1)*math.sin(lat2) - math.sin(lat1)*math.cos(lat2)*math.cos(dlon)
    return (math.degrees(math.atan2(x,y)) + 360) % 360

def heading_error(curr, prev, target):
    if not prev:
        return 0
    move = bearing(prev, curr)
    want = bearing(curr, target)
    diff = (want - move + 540) % 360 - 180
    return abs(diff)

# ================= SNAP =================

def nearest_point(pos, geometry):
    best = geometry[0]
    best_dist = 1e9
    for p in geometry:
        d = haversine(pos, p)
        if d < best_dist:
            best = p
            best_dist = d
    return best, best_dist

# ================= SLICE =================

def slice_route(coords, step=12):
    sliced = [coords[0]]
    acc = 0
    for i in range(len(coords)-1):
        d = haversine(coords[i], coords[i+1])
        acc += d
        if acc >= step:
            sliced.append(coords[i+1])
            acc = 0
    sliced.append(coords[-1])
    return sliced

# ================= COMMANDS =================

def generate_commands(points):
    cmds = []
    for i in range(len(points)-1):
        dist = haversine(points[i], points[i+1])
        if i > 0:
            b0 = bearing(points[i-1], points[i])
            b1 = bearing(points[i], points[i+1])
            d = (b1 - b0 + 540) % 360 - 180
            if abs(d) > 10:
                cmds.append(("tr" if d > 0 else "tl") + str(int(abs(d))))
        cmds.append(f"mf{round(dist,1)}")
    return cmds

# ================= UI =================

@app.route("/")
def home():
    return render_template("index.html")

# ================= GPS =================

@app.route("/gps", methods=["POST"])
def gps():
    global current_gps, last_gps, gps_buffer
    pos = request.json["pos"]
    last_gps = current_gps

    gps_buffer.append(pos)
    if len(gps_buffer) > 5:
        gps_buffer.pop(0)

    lng = sum(p[0] for p in gps_buffer)/len(gps_buffer)
    lat = sum(p[1] for p in gps_buffer)/len(gps_buffer)
    current_gps = [lng, lat]
    return "ok"

# ================= ROUTE CORE =================

def do_route(start, end):
    global route_geometry, active_waypoints, current_index, current_destination

    url = f"https://api.mapbox.com/directions/v5/mapbox/walking/{start[0]},{start[1]};{end[0]},{end[1]}"
    r = requests.get(url, params={
        "geometries":"geojson",
        "overview":"full",
        "access_token":MAPBOX_TOKEN
    }).json()

    route = r["routes"][0]
    route_geometry = route["geometry"]["coordinates"]
    active_waypoints = slice_route(route_geometry)
    current_index = 0
    current_destination = end

    cmds = generate_commands(active_waypoints)

    print("\nNEW ROUTE:", cmds)

    try:
        requests.post(PI_STOP_URL, timeout=1)
        time.sleep(0.3)
        requests.post(PI_ROUTE_URL, json={"commands":cmds}, timeout=2)
    except:
        pass

    return {
        "commands":cmds,
        "distance":route["distance"],
        "duration":route["duration"],
        "geometry":route_geometry
    }

@app.route("/route", methods=["POST"])
def route():
    data = request.get_json()
    _, end = data["coordinates"]
    return jsonify(do_route(current_gps, end))

# ================= LIVE =================

@app.route("/gps/live")
def live():
    target = None
    if current_index < len(active_waypoints):
        target = active_waypoints[current_index]
    return jsonify({"pos":current_gps,"target":target})

# ================= AUTO NAV =================

def monitor():
    global current_index, last_reroute
    while True:
        time.sleep(1)
        if not current_gps or not route_geometry:
            continue

        nearest, err = nearest_point(current_gps, route_geometry)

        if active_waypoints:
            current_index = min(range(len(active_waypoints)), key=lambda i: haversine(active_waypoints[i], nearest))

        target = active_waypoints[current_index]
        dir_err = heading_error(current_gps, last_gps, target)

        print("Deviation:",round(err,1),"Heading:",round(dir_err,1))

        speed = 30
        if err > 3 or dir_err > 20: speed = 20
        if err > 8 or dir_err > 45: speed = 5
        try:
            requests.post(PI_SPEED_URL, json={"speed":speed}, timeout=0.5)
        except:
            pass

        if err > REROUTE_THRESHOLD or dir_err > HEADING_THRESHOLD:
            if time.time()-last_reroute > 10:
                last_reroute = time.time()
                print("AUTO REROUTE")
                speak("Recalculating route")
                do_route(nearest, current_destination)

threading.Thread(target=monitor, daemon=True).start()

# ================= START =================
if __name__ == "__main__":
    print("PC Navigation Brain Running")
    app.run(host="0.0.0.0", port=5001, debug=True)
