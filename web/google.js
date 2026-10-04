const SITE_LABELS = { none: "Χωρίς website", social_only: "Μόνο social", has_site: "Έχει website" };
const BADGE_CLASS = { none: "none", social_only: "social_only", has_site: "alive" };
const MARKER_COLORS = { none: "#dc2626", social_only: "#d97706", has_site: "#16a34a" };
const CONTACT_LABELS = {
  new: "Νέο", called: "Κλήθηκε", interested: "Ενδιαφέρεται", not_interested: "Δεν ενδιαφέρεται", do_not_call: "Να μην καλεστεί",
};
const CHIPS = ["φαρμακεία", "καφετέριες", "σούπερ μάρκετ", "κομμωτήρια", "φούρνοι", "εστιατόρια", "γυμναστήρια", "βιβλιοπωλεία", "οδοντίατροι", "ηλεκτρολόγοι"];
function ensureMapSoon() { addEventListener('DOMContentLoaded', () => ensureMap()); if (document.readyState !== 'loading') ensureMap(); }
const GRID_CALLS = { 1: 3, 2: 12, 3: 27 };

const $ = (id) => document.getElementById(id);
let results = [];
let status = { calls_this_month: 0, limit: 900 };
let map, markerLayer;

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);   // textContent/href only: never innerHTML with data
  node.append(...children);
  return node;
}

async function api(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `Σφάλμα ${res.status}`);
  }
  return res.json();
}

const setStatus = (text) => { $("status").textContent = text; };
const phoneOf = (r) => r.manual_phone || r.phone || "";
const showUsage = () => {
  $("usage").textContent = `Κλήσεις Google αυτόν τον μήνα: ${status.calls_this_month} από ${status.limit} (σκληρό όριο του εργαλείου).`;
};

function safeHttpUrl(url) {
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(url) ? url : "https://" + url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch { return null; }
}

const googleUrl = (r) =>
  "https://www.google.com/search?q=" + encodeURIComponent([r.name, r.address].filter(Boolean).join(" "));

async function save(r, body, box) {
  try {
    await api(`/api/google/leads/${encodeURIComponent(r.place_id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch (e) { alert("Η αποθήκευση απέτυχε: " + e.message); return; }
  Object.assign(r, body);
  box.classList.add("saved");
  setTimeout(() => box.classList.remove("saved"), 800);
  if (body.contact_status === "do_not_call") { results = results.filter((x) => x !== r); render(); }
}

const cardsByPlace = new Map();
const markersByPlace = new Map();
let selectedId = null;

function phoneBlock(r) {
  const box = el("div", { className: "phone-block" });
  const phone = phoneOf(r);
  if (phone) box.append(el("a", { className: "phone-link", href: "tel:" + phone.replace(/[^\d+]/g, ""), textContent: phone }));
  const input = el("input", { type: "text", className: "phone-input", maxLength: 40, value: r.manual_phone || "",
    placeholder: phone ? "άλλο τηλέφωνο" : "πρόσθεσε τηλέφωνο" });
  input.onblur = () => {
    if (input.value.trim() !== (r.manual_phone || "")) save(r, { manual_phone: input.value }, input).then(render);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") input.blur(); };
  box.append(input);
  return box;
}

function selectPlace(r, fromMap) {
  selectedId = r.place_id;
  cardsByPlace.forEach((card, id) => card.classList.toggle("selected", id === r.place_id));
  const marker = markersByPlace.get(r.place_id);
  if (marker) { if (!fromMap) map.setView([r.lat, r.lon], Math.max(map.getZoom(), 16)); marker.openPopup(); }
  if (fromMap) cardsByPlace.get(r.place_id)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function card(r) {
  const href = r.website_url && safeHttpUrl(r.website_url);
  const rating = r.rating ? `★ ${r.rating.toFixed(1)} (${r.rating_count || 0})` : "";

  const checkbox = el("input", { type: "checkbox", checked: !!r.no_site_verified });
  checkbox.onchange = () => save(r, { no_site_verified: checkbox.checked }, checkbox.closest(".card-item"));
  const contact = el("select");
  for (const [value, label] of Object.entries(CONTACT_LABELS)) {
    contact.append(el("option", { value, textContent: label, selected: value === r.contact_status }));
  }
  contact.onchange = () => save(r, { contact_status: contact.value }, contact).then(() => {
    const item = cardsByPlace.get(r.place_id);   // restyle in place: a full render would close the open card
    if (item) item.className = item.className.replace(/s-\w+/, "s-" + r.contact_status);
  });
  const notes = el("textarea", { value: r.notes || "", placeholder: "σημειώσεις κλήσης", rows: 3 });
  notes.onblur = () => { if (notes.value !== (r.notes || "")) save(r, { notes: notes.value }, notes); };

  const more = el("details", { className: "card-more" },
    el("summary", { textContent: r.no_site_verified ? "Επιβεβαιωμένο ✓ · σημειώσεις και επαφή" : "Επιβεβαίωση, σημειώσεις και επαφή" }),
    el("div", { className: "more-body" },
      el("a", { href: googleUrl(r), target: "_blank", rel: "noopener noreferrer", textContent: "Αναζήτηση στο Google για επιβεβαίωση ↗" }),
      el("label", { className: "check" }, checkbox, " Έλεγξα: δεν έχει website"),
      contact, notes));
  more.addEventListener("click", (e) => e.stopPropagation());

  const item = el("article", { className: "card-item s-" + r.contact_status + (r.place_id === selectedId ? " selected" : "") },
    el("div", { className: "card-title" }, el("span", { textContent: r.name }),
      el("span", { className: "badge " + BADGE_CLASS[r.site_status], textContent: SITE_LABELS[r.site_status] })),
    el("div", { className: "card-meta", textContent: [rating, r.address].filter(Boolean).join(" · ") }),
    phoneBlock(r));
  if (href) item.append(el("a", { href, target: "_blank", rel: "noopener noreferrer", className: "card-meta", textContent: r.website_url }));
  item.append(more);
  item.onclick = (e) => { if (!e.target.closest("a,input,select,textarea,button,summary")) selectPlace(r, false); };
  cardsByPlace.set(r.place_id, item);
  return item;
}

function visible() {
  const text = $("text-filter").value.trim().toLowerCase();
  return results.filter((r) =>
    (!$("only-no-site").checked || r.site_status !== "has_site") &&
    (!$("only-phone").checked || phoneOf(r)) &&
    (!text || (r.name + " " + (r.address || "")).toLowerCase().includes(text)));
}

function ensureMap() {
  if (map) return;
  map = L.map("map").setView([40.64, 22.94], 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

function renderMap(list, refit) {
  ensureMap();
  markerLayer.clearLayers();
  markersByPlace.clear();
  const points = [];
  list.filter((r) => r.lat != null).forEach((r) => {
    const marker = L.circleMarker([r.lat, r.lon], { radius: 9, color: "#fff", weight: 2, fillColor: MARKER_COLORS[r.site_status], fillOpacity: 0.95 });
    marker.bindPopup(el("div", {}, el("b", { textContent: r.name }), el("br"), el("span", { textContent: phoneOf(r) || "χωρίς τηλέφωνο" })));
    marker.on("click", () => selectPlace(r, true));
    marker.addTo(markerLayer);
    markersByPlace.set(r.place_id, marker);
    points.push([r.lat, r.lon]);
  });
  if (refit && points.length) map.fitBounds(points, { padding: [40, 40], maxZoom: 17 });
}

let lastCount = -1;
function render() {
  const list = visible();
  cardsByPlace.clear();
  $("result-filters").hidden = !results.length;
  $("empty").hidden = list.length > 0 || !results.length;
  $("cards").replaceChildren(...list.map(card));
  const count = (fn) => list.filter(fn).length;
  const stats = [["Καταστήματα", list.length], ["Χωρίς site", count((r) => r.site_status === "none")],
    ["Μόνο social", count((r) => r.site_status === "social_only")], ["Με τηλέφωνο", count((r) => phoneOf(r))]];
  $("stats").replaceChildren(...(results.length ? stats : []).map(([label, n]) =>
    el("div", { className: "stat" }, el("b", { textContent: n }), el("span", { textContent: label }))));
  renderMap(list, list.length !== lastCount);   // only re-zoom when the set of results changed
  lastCount = list.length;
}

async function runSearch(area) {
  const query = $("query").value.trim();
  const grid = Number($("grid").value);
  const max = GRID_CALLS[grid];
  const left = status.limit - status.calls_this_month;
  if (grid > 1 && !confirm(`Η αναζήτηση θα χρησιμοποιήσει έως ${max} κλήσεις Google (απομένουν ${left} αυτόν τον μήνα). Συνέχεια;`)) return;
  setStatus("Αναζήτηση στο Google...");
  $("search-btn").disabled = true;
  try {
    const { name, display_name, osm_type, osm_id, lat, lon, place_type, bbox } = area;
    const data = await api("/api/google/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, grid, radius: Number($("radius").value) || 1500,
        area: { name, display_name, osm_type, osm_id, lat, lon, place_type, bbox } }),
    });
    results = data.results;
    status = { calls_this_month: data.calls_this_month, limit: data.limit };
    showUsage();
    setStatus(`${results.length} καταστήματα · ${data.calls_used_now} κλήσεις σε αυτή την αναζήτηση` +
      (data.partial ? " · ΣΤΑΜΑΤΗΣΕ νωρίς: έφτασες το μηνιαίο όριο." : ""));
    render();
  } catch (e) { setStatus(e.message); } finally { $("search-btn").disabled = false; }
}

async function start() {
  const query = $("query").value.trim(), name = $("area-name").value.trim();
  if (query.length < 2 || name.length < 2) { setStatus("Γράψε τι ψάχνεις και σε ποια περιοχή."); return; }
  $("candidates").replaceChildren();
  setStatus("Εύρεση περιοχής...");
  try {
    const params = new URLSearchParams({ name });
    if ($("area-hint").value.trim()) params.set("hint", $("area-hint").value.trim());
    const areas = await api("/api/resolve?" + params);
    if (!areas.length) { setStatus("Δεν βρέθηκε περιοχή. Δοκίμασε άλλο όνομα ή αφαίρεσε το φίλτρο."); return; }
    if (areas.length === 1) { runSearch({ ...areas[0], name }); return; }
    setStatus("Βρέθηκαν πολλές περιοχές. Διάλεξε τη σωστή:");
    $("candidates").replaceChildren(...areas.map((a) => {
      const radio = el("input", { type: "radio", name: "candidate" });
      radio.onchange = () => { $("candidates").replaceChildren(); runSearch({ ...a, name }); };
      return el("label", { className: "candidate" }, radio,
        el("span", {}, a.display_name, el("small", { textContent: a.has_boundary ? " (με όρια)" : " (σημείο)" })));
    }));
  } catch (e) { setStatus(e.message); }
}

async function init() {
  $("chips").replaceChildren(...CHIPS.map((c) => {
    const chip = el("button", { type: "button", className: "chip", textContent: c });
    chip.onclick = () => { $("query").value = c; $("query").focus(); };
    return chip;
  }));
  ["only-no-site", "only-phone"].forEach((id) => $(id).addEventListener("change", render));
  $("text-filter").addEventListener("input", render);
  $("search-btn").onclick = start;
  ["query", "area-name", "area-hint"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") start(); }));
  try {
    const s = await api("/api/google/status");
    status = s;
    if (!s.configured) { setStatus("Λείπει το GOOGLE_PLACES_API_KEY από το .env"); $("search-btn").disabled = true; }
    showUsage();
  } catch (e) { setStatus(e.message); }
  // Shareable link, e.g. /google?q=φαρμακεία&area=Πεύκα&hint=Θεσσαλονίκη&auto=1
  const params = new URLSearchParams(location.search);
  if (params.get("q")) $("query").value = params.get("q");
  if (params.get("area")) $("area-name").value = params.get("area");
  if (params.get("hint")) { $("area-hint").value = params.get("hint"); $("area-hint").closest("details").open = true; }
  if (params.get("auto") === "1" && !$("search-btn").disabled) start();
}

ensureMapSoon();
init();
