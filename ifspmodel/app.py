from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests, math, threading, time

app = Flask(__name__)
CORS(app)

# ================= CONFIG =================
MAPBOX_TOKEN = "pk.eyJ1IjoibWF5dXJrcyIsImEiOiJjbWpoZmF5cTQwcTZzM2RxdmZkeGc4aXRvIn0.w53nwvcH9lLU_bx9aoiVZw"
PI_URL = "http://10.177.21.229:5000/route"

# ================= STATE =================
current_gps = None
gps_buffer = []
route_geometry = []      # full polyline
active_waypoints = []   # sliced
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

# ================= SNAP =================

def nearest_point_on_route(pos, geometry):
    best = geometry[0]
    best_dist = 1e9
    for p in geometry:
        d = haversine(pos, p)
        if d < best_dist:
            best_dist = d
            best = p
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
                if d > 0: cmds.append(f"tr{int(abs(d))}")
                else: cmds.append(f"tl{int(abs(d))}")
        cmds.append(f"mf{round(dist,1)}")
    return cmds

# ================= UI =================

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
    lng = sum(p[0] for p in gps_buffer)/len(gps_buffer)
    lat = sum(p[1] for p in gps_buffer)/len(gps_buffer)
    current_gps = [lng, lat]
    return "ok"

# ================= ROUTE =================

@app.route("/route", methods=["POST"])
def route():
    global route_geometry, active_waypoints, current_index, current_destination

    data = request.get_json()
    _, end = data["coordinates"]
    current_destination = end

    if not current_gps:
        return jsonify({"error":"GPS not ready"}), 400

    start = current_gps

    url = f"https://api.mapbox.com/directions/v5/mapbox/walking/{start[0]},{start[1]};{end[0]},{end[1]}"
    r = requests.get(url, params={
        "geometries":"geojson",
        "overview":"full",
        "access_token":MAPBOX_TOKEN
    }).json()

    if "routes" not in r:
        return jsonify(r), 500

    route = r["routes"][0]
    route_geometry = route["geometry"]["coordinates"]

    active_waypoints = slice_route(route_geometry)
    current_index = 0

    cmds = generate_commands(active_waypoints)

    print("\nNEW ROUTE:", cmds)

    # Send to Pi
    try:
        requests.post(PI_URL, json={"commands":cmds}, timeout=2)
    except:
        print("Pi not reachable")

    return jsonify({
        "commands":cmds,
        "distance":route["distance"],
        "duration":route["duration"],
        "geometry":route_geometry
    })

# ================= LIVE =================

@app.route("/gps/live")
def live():
    return jsonify({
        "pos": current_gps,
        "target": active_waypoints[current_index] if current_index < len(active_waypoints) else None
    })

# ================= AUTO REROUTER =================

def gps_monitor():
    global current_index, active_waypoints, route_geometry, current_gps, current_destination, last_reroute

    while True:
        time.sleep(1)

        if not current_gps or not route_geometry:
            continue

        # Snap robot to nearest point on route
        nearest, err = nearest_point_on_route(current_gps, route_geometry)

        print("Off route:", round(err,1), "m")

        # Snap progress to nearest waypoint
        if active_waypoints:
            current_index = min(
                range(len(active_waypoints)),
                key=lambda i: haversine(active_waypoints[i], nearest)
            )

        # Only reroute if badly off
        if err > 12 and current_destination:
            if time.time() - last_reroute > 8:
                last_reroute = time.time()

                print("REROUTING FROM NEAREST ROUTE POINT")

                try:
                    # 🔥 use snapped point, not raw GPS
                    requests.post("http://127.0.0.1:5001/route", json={
                        "coordinates":[nearest, current_destination]
                    }, timeout=2)
                except Exception as e:
                    print("Reroute failed:", e)

threading.Thread(target=gps_monitor, daemon=True).start()

# ================= START =================

if __name__ == "__main__":
    print("PC Navigation Brain Running")
    app.run(host="0.0.0.0", port=5001, debug=True)
