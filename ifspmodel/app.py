from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests, math, threading, time

app = Flask(__name__)
CORS(app)

MAPBOX_TOKEN = "pk.eyJ1IjoibWF5dXJrcyIsImEiOiJjbWpoZmF5cTQwcTZzM2RxdmZkeGc4aXRvIn0.w53nwvcH9lLU_bx9aoiVZw"

# ================= STATE =================
current_gps = None
gps_buffer = []
active_waypoints = []
current_index = 0
current_destination = None
last_reroute = 0
obstacle_detected = False

# ================= MATH =================

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

# ================= ROUTE SLICING =================

def slice_route(coords, step=12):
    sliced = [coords[0]]
    dist = 0
    last_bearing = None

    for i in range(len(coords)-1):
        d = haversine(coords[i], coords[i+1])
        b = bearing(coords[i], coords[i+1])

        if last_bearing is None:
            last_bearing = b

        turn = abs(b - last_bearing)
        dist += d

        if dist >= step or turn > 25:
            sliced.append(coords[i+1])
            dist = 0
            last_bearing = b

    sliced.append(coords[-1])
    return sliced

# ================= COMMANDS =================

def generate_commands(points):
    cmds = []
    for i in range(len(points)-1):
        b1 = bearing(points[i], points[i+1])
        dist = haversine(points[i], points[i+1])

        if i > 0:
            b0 = bearing(points[i-1], points[i])
            delta = (b1 - b0 + 540) % 360 - 180

            if abs(delta) > 15:
                if delta > 0:
                    cmds.append(f"tr{int(abs(delta))}")
                else:
                    cmds.append(f"tl{int(abs(delta))}")

        cmds.append(f"mf{round(dist,1)}")
    return cmds

# ================= FRONTEND =================

@app.route("/")
def home():
    return render_template("index.html")

# ================= GPS =================

@app.route("/gps", methods=["POST"])
def gps():
    global current_gps, gps_buffer

    pos = request.json["pos"]
    gps_buffer.append(pos)

    if len(gps_buffer) > 5:
        gps_buffer.pop(0)

    lng = sum(p[0] for p in gps_buffer) / len(gps_buffer)
    lat = sum(p[1] for p in gps_buffer) / len(gps_buffer)

    current_gps = [lng, lat]
    return "ok"

# ================= ROUTE =================

@app.route("/route", methods=["POST"])
def route():
    global active_waypoints, current_index, current_destination

    if not current_gps:
        return jsonify({"error":"GPS not ready"}), 400

    data = request.get_json()
    _, end = data["coordinates"]

    current_destination = end
    start = current_gps

    url = f"https://api.mapbox.com/directions/v5/mapbox/walking/{start[0]},{start[1]};{end[0]},{end[1]}"

    r = requests.get(url, params={
        "geometries":"geojson",
        "overview":"full",
        "access_token":MAPBOX_TOKEN
    })

    mb = r.json()
    route = mb["routes"][0]
    coords = route["geometry"]["coordinates"]

    active_waypoints = slice_route(coords)
    current_index = 0

    cmds = generate_commands(active_waypoints)

    print("\n=== NEW ROUTE ===")
    print(cmds)

    requests.post("http://10.177.21.229:5000/route", json={"commands":cmds})

    return jsonify({"commands":cmds,"distance":route["distance"],"duration":route["duration"]})

# ================= LIVE GPS FOR MAP =================

@app.route("/gps/live")
def gps_live():
    return jsonify({
        "pos": current_gps,
        "target": active_waypoints[current_index] if active_waypoints and current_index < len(active_waypoints) else None
    })

# ================= OBSTACLE =================

@app.route("/obstacle", methods=["POST"])
def obstacle():
    global obstacle_detected
    obstacle_detected = request.json.get("hit", True)
    print("OBSTACLE:", obstacle_detected)
    return "ok"

# ================= GPS MONITOR =================

def gps_monitor():
    global current_index, active_waypoints, current_gps, current_destination, last_reroute, obstacle_detected

    while True:
        time.sleep(1)

        if obstacle_detected:
            print("STOPPED DUE TO OBSTACLE")
            continue

        if not current_gps or not active_waypoints:
            continue

        if current_index >= len(active_waypoints):
            continue

        target = active_waypoints[current_index]
        error = haversine(current_gps, target)

        print("GPS error:", round(error,1),"m")

        if error < 3:
            current_index += 1
            print("Reached waypoint", current_index)

        elif error > 12 and current_destination:
            now = time.time()
            if now - last_reroute > 10:
                last_reroute = now
                print("OFF ROUTE — REROUTING")
                try:
                    requests.post("http://127.0.0.1:5001/route", json={
                        "coordinates":[current_gps, current_destination]
                    })
                except:
                    pass

threading.Thread(target=gps_monitor, daemon=True).start()

# ================= START =================

if __name__ == "__main__":
    print("PC Navigation Brain Running")
    app.run(host="0.0.0.0", port=5001, debug=True)
