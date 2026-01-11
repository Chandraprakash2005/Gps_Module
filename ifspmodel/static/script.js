let currentPosition = null;
let sourceMarker = null;
let destMarker = null;
let routeLayer = null;

const map = L.map("map").setView([12.7517, 80.1993], 16);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution: "© OpenStreetMap",
}).addTo(map);

// ================= LIVE GPS =================
navigator.geolocation.watchPosition(
  (pos) => {
    const lat = pos.coords.latitude;
    const lng = pos.coords.longitude;
    currentPosition = [lng, lat];

    if (!sourceMarker) {
      sourceMarker = L.marker([lat, lng])
        .addTo(map)
        .bindPopup("📍 Phone GPS");
    } else {
      sourceMarker.setLatLng([lat, lng]);
    }
  },
  () => alert("GPS error"),
  { enableHighAccuracy: true }
);

// ================= SEND GPS TO PC =================
setInterval(() => {
  if (currentPosition) {
    fetch("/gps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pos: currentPosition }),
    });
  }
}, 1000);

// ================= MAP CLICK =================
map.on("click", (e) => {
  if (!currentPosition) {
    alert("Waiting for GPS...");
    return;
  }

  const dest = [e.latlng.lng, e.latlng.lat];

  if (destMarker) map.removeLayer(destMarker);
  destMarker = L.marker([dest[1], dest[0]])
    .addTo(map)
    .bindPopup("🎯 Destination")
    .openPopup();

  calculateRoute(currentPosition, dest);
});

// ================= REQUEST ROUTE =================
async function calculateRoute(start, end) {
  const res = await fetch("/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ coordinates: [start, end] }),
  });

  const data = await res.json();

  console.log("Commands:", data.commands);
  console.log("Distance:", data.distance);
  console.log("Duration:", data.duration);

  // ===== DRAW BLUE ROUTE =====
  const latlngs = data.geometry.map(p => [p[1], p[0]]);

  if (routeLayer) map.removeLayer(routeLayer);

  routeLayer = L.polyline(latlngs, {
    color: "blue",
    weight: 6
  }).addTo(map);

  map.fitBounds(routeLayer.getBounds());
}

// ================= SEND TO PI =================
async function sendToPi(commands) {
  try {
    const res = await fetch("http://10.177.21.229:5000/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ commands }),
    });

    const data = await res.json();
    console.log("Pi:", data);
  } catch (e) {
    console.error("Pi error", e);
  }
}

// ================= ROBOT TRACKING =================

const robotIcon = L.icon({
  iconUrl: "https://cdn-icons-png.flaticon.com/512/4712/4712035.png",
  iconSize: [45, 45],
  iconAnchor: [22, 22],
});

let robotMarker = null;
let targetMarker = null;
let driftLine = null;

setInterval(async () => {
  try {
    const res = await fetch("/gps/live");
    const data = await res.json();

    if (!data.pos) return;

    const lat = data.pos[1];
    const lng = data.pos[0];

    // Robot marker
    if (!robotMarker) {
      robotMarker = L.marker([lat, lng], { icon: robotIcon })
        .addTo(map)
        .bindPopup("🤖 Robot");
    } else {
      robotMarker.setLatLng([lat, lng]);
    }

    // Target waypoint
    if (data.target) {
      const tlat = data.target[1];
      const tlng = data.target[0];

      if (!targetMarker) {
        targetMarker = L.circleMarker([tlat, tlng], {
          radius: 10,
          color: "red",
        }).addTo(map);
      } else {
        targetMarker.setLatLng([tlat, tlng]);
      }

      drawDrift(data.pos, data.target);
    }
  } catch (e) {}
}, 1000);

// ================= DRIFT LINE =================
function drawDrift(robot, target) {
  if (driftLine) map.removeLayer(driftLine);

  driftLine = L.polyline(
    [
      [robot[1], robot[0]],
      [target[1], target[0]],
    ],
    { color: "red", dashArray: "5,5" }
  ).addTo(map);
}
