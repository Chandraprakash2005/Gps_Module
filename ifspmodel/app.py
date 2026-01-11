from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

# 
# Mapbox token (from the original code)
MAPBOX_TOKEN = "pk.eyJ1IjoibWF5dXJrcyIsImEiOiJjbWpoZmF5cTQwcTZzM2RxdmZkeGc4aXRvIn0.w53nwvcH9lLU_bx9aoiVZw"

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")  

@app.route("/route", methods=["POST"])
def route():
    try:
        data = request.get_json()
        
        if not data or "coordinates" not in data:
            return jsonify({"error": "Missing coordinates"}), 400
        
        coords = data["coordinates"]
        
        if len(coords) != 2:
            return jsonify({"error": "Need exactly 2 coordinates"}), 400

        start = coords[0]  # [lng, lat]
        end = coords[1]    # [lng, lat]
        
        # Mapbox Directions API (walking profile)
        url = f"https://api.mapbox.com/directions/v5/mapbox/walking/{start[0]},{start[1]};{end[0]},{end[1]}"
        
        params = {
            "geometries": "geojson",
            "access_token": MAPBOX_TOKEN
        }
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code != 200:
            return jsonify({
                "error": "Mapbox API error",
                "details": response.text
            }), 500
        
        data = response.json()
        
        # Convert to same format as OpenRouteService (FeatureCollection)
        if "routes" in data and len(data["routes"]) > 0:
            route = data["routes"][0]
            geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "geometry": route["geometry"],
                    "properties": {
                        "distance": route.get("distance", 0),
                        "duration": route.get("duration", 0)
                    }
                }]
            }
            return jsonify(geojson)
        else:
            return jsonify({"error": "No route found"}), 404
    
    except Exception as e:
        return jsonify({
            "error": "Server error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5001, debug=True)
