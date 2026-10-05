const SITE_LABELS = { none: "Χωρίς website στη Google", social_only: "Μόνο social στη Google", has_site: "Έχει website" };
const BADGE_CLASS = { none: "none", social_only: "social_only", has_site: "alive" };
const PIN_COLORS = { none: "#dc2626", social_only: "#d97706", has_site: "#16a34a" };
const CONTACT_LABELS = {
  new: "Νέο", called: "Κλήθηκε", interested: "Ενδιαφέρεται", not_interested: "Δεν ενδιαφέρεται", do_not_call: "Να μην καλεστεί",
};
const CHIPS = ["φαρμακεία", "καφετέριες", "σούπερ μάρκετ", "κομμωτήρια", "φούρνοι", "εστιατόρια", "γυμναστήρια", "βιβλιοπωλεία", "οδοντίατροι", "ηλεκτρολόγοι"];
const GRID_CALLS = { 1: 3, 2: 12, 3: 27 };
const ALL_QUERY = "καταστήματα";
let mode = "category";

const $ = (id) => document.getElementById(id);
let results = [];
let usage = { calls_this_month: 0, limit: 900 };
let map, markerLayer;
let selectedId = null;
let lastKey = "";
const cardsByPlace = new Map();
const markersByPlace = new Map();

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);   // textContent/href only: never innerHTML with data
  node.append(...children);
  return node;
}

async function api(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90000);   // never spin forever
  try {
    const res = await fetch(url, { ...options, signal: controller.signal });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(typeof detail.detail === "string" ? detail.detail : `Σφάλμα ${res.status}`);
    }
    return await res.json();
  } catch (e) {
    if (e.name === "AbortError") throw new Error("Η αναζήτηση άργησε πάνω από 90 δευτερόλεπτα. Έλεγξε τη σύνδεσή σου και ξαναδοκίμασε.");
    throw e;
  } finally { clearTimeout(timer); }
}

function setStatus(text, isError = false) {
  const box = $("status");
  box.hidden = !text;
  box.textContent = text;
  box.classList.toggle("error", isError);
}

const phoneOf = (r) => r.manual_phone || r.phone || "";
const showUsage = () => {
  $("usage").textContent = `Κλήσεις Google αυτόν τον μήνα: ${usage.calls_this_month} από ${usage.limit} (σκληρό όριο του εργαλείου).`;
};

function safeHttpUrl(url) {
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(url) ? url : "https://" + url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch { return null; }
}

const googleSearchUrl = (r) =>
  "https://www.google.com/search?q=" + encodeURIComponent([r.name, r.address].filter(Boolean).join(" "));
const googleMapsUrl = (r) =>
  "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(`${r.name} ${r.address || ""}`);

function stars(r) {
  if (!r.rating) return el("span", { className: "muted", textContent: "χωρίς βαθμολογία" });
  return el("span", { className: "stars", textContent: `★ ${r.rating.toFixed(1)}`, title: `${r.rating_count || 0} κριτικές` },
    el("span", { className: "muted", textContent: ` (${r.rating_count || 0})` }));
}

async function save(r, body, box) {
  try {
    await api(`/api/google/leads/${encodeURIComponent(r.place_id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch (e) { alert("Η αποθήκευση απέτυχε: " + e.message); return false; }
  Object.assign(r, body);
  box.classList.add("saved");
  setTimeout(() => box.classList.remove("saved"), 800);
  if (body.contact_status === "do_not_call") { results = results.filter((x) => x !== r); render(); }
  return true;
}

function contactInput(r, field, placeholder, type) {
  const input = el("input", { type, className: "mini", maxLength: 120, value: r[field] || "", placeholder });
  input.onblur = async () => {
    if (input.value.trim() === (r[field] || "")) return;
    if (!(await save(r, { [field]: input.value }, input))) return;
    if (field === "manual_website") r.site_status = r.manual_website ? "has_site" : r.google_site_status;   // a site you found beats "Google lists none"
    if (field === "manual_phone" || field === "manual_website") render();
  };
  input.onkeydown = (e) => { if (e.key === "Enter") input.blur(); };
  return input;
}

function openBadge(r, now) {
  const status = openStatus(r, now);
  return el("span", { className: "open open-" + status.state, textContent: status.label });
}

function weekList(r, now) {
  const lines = hoursLines(r);
  if (!lines.length) return null;
  const today = DAY_NAMES_EL[now.getDay()];
  return el("ul", { className: "hours-week" },
    ...lines.map((line) => el("li", { className: line.startsWith(today) ? "today" : "", textContent: line })));
}

function card(r) {
  const now = new Date();
  const phone = phoneOf(r);
  const href = r.website_url && safeHttpUrl(r.website_url);

  const call = phone
    ? el("a", { className: "phone-link", href: "tel:" + phone.replace(/[^\d+]/g, ""), textContent: "Κλήση " + phone })
    : el("span", { className: "muted", textContent: "Χωρίς τηλέφωνο" });

  const checkbox = el("input", { type: "checkbox", checked: !!r.no_site_verified });
  checkbox.onchange = () => save(r, { no_site_verified: checkbox.checked }, checkbox.closest(".card-item"));
  const contact = el("select", { className: "mini" });
  for (const [value, label] of Object.entries(CONTACT_LABELS)) {
    contact.append(el("option", { value, textContent: label, selected: value === r.contact_status }));
  }
  contact.onchange = async () => {
    if (!(await save(r, { contact_status: contact.value }, contact))) return;
    const item = cardsByPlace.get(r.place_id);   // restyle in place: a full render would close the open card
    if (item) item.className = item.className.replace(/s-\w+/, "s-" + r.contact_status);
  };
  const notes = el("textarea", { value: r.notes || "", placeholder: "σημειώσεις κλήσης", rows: 3 });
  notes.onblur = () => { if (notes.value !== (r.notes || "")) save(r, { notes: notes.value }, notes); };

  const more = el("details", { className: "card-more" },
    el("summary", { textContent: r.no_site_verified ? "Επιβεβαιωμένο ✓ · στοιχεία επαφής" : "Στοιχεία επαφής και σημειώσεις" }),
    el("div", { className: "more-body" },
      contactInput(r, "manual_website", "website που βρήκες (π.χ. prodent.gr)", "text"),
      contactInput(r, "manual_phone", "τηλέφωνο (δικό σου)", "text"),
      contactInput(r, "manual_email", "email", "email"),
      el("label", { className: "check" }, checkbox, " Έλεγξα στο Google: δεν έχει website"),
      contact, notes, ...(weekList(r, now) ? [el("div", {}, el("b", { textContent: "Ωράριο" }), weekList(r, now))] : [])));
  more.addEventListener("click", (e) => e.stopPropagation());

  const item = el("article", { className: "card-item s-" + r.contact_status + (r.place_id === selectedId ? " selected" : "") },
    el("div", { className: "card-title" }, el("span", { textContent: r.name }),
      el("span", { className: "badge " + BADGE_CLASS[r.site_status], textContent: SITE_LABELS[r.site_status] })),
    el("div", { className: "card-line" }, stars(r), el("span", { className: "muted", textContent: r.address || "" })),
    el("div", { className: "card-line" }, openBadge(r, now),
      el("span", { className: "muted", textContent: todayHours(r, now) })),
    el("div", { className: "card-actions" }, call));
  if (r.manual_email) item.querySelector(".card-actions").append(
    el("a", { href: "mailto:" + r.manual_email, textContent: r.manual_email, className: "card-meta" }));
  if (href) item.append(el("a", { href, target: "_blank", rel: "noopener noreferrer", className: "card-meta", textContent: r.website_url }));
  const found = r.manual_website && safeHttpUrl(r.manual_website);
  if (found) item.append(el("a", { href: found, target: "_blank", rel: "noopener noreferrer", className: "card-meta", textContent: `${r.manual_website} (το βρήκες εσύ)` }));
  item.append(el("div", { className: "card-actions" },
    el("a", { href: googleSearchUrl(r), target: "_blank", rel: "noopener noreferrer", textContent: "Έλεγχος στο Google ↗" }),
    el("a", { href: googleMapsUrl(r), target: "_blank", rel: "noopener noreferrer", textContent: "Google Maps ↗" })));
  item.append(more);
  item.onclick = (e) => { if (!e.target.closest("a,input,select,textarea,button,summary")) selectPlace(r, false); };
  cardsByPlace.set(r.place_id, item);
  return item;
}

function popupFor(r) {
  const body = el("div", { className: "popup" },
    el("b", { textContent: r.name }), stars(r),
    el("span", { className: "badge " + BADGE_CLASS[r.site_status], textContent: SITE_LABELS[r.site_status] }),
    el("div", {}, openBadge(r, new Date())),
    el("div", { textContent: phoneOf(r) || "χωρίς τηλέφωνο" }));
  if (r.manual_email) body.append(el("div", { textContent: r.manual_email }));
  return body;
}

function pinIcon(r, selected) {
  // html is built only from our own constants, never from business data
  return L.divIcon({
    className: "pin-wrap", iconSize: [26, 26], iconAnchor: [13, 30], popupAnchor: [0, -28],
    html: `<div class="pin${selected ? " selected" : ""}" style="--c:${PIN_COLORS[r.site_status]}"></div>`,
  });
}

function selectPlace(r, fromMap) {
  const previous = results.find((x) => x.place_id === selectedId);
  selectedId = r.place_id;
  if (previous && markersByPlace.has(previous.place_id)) markersByPlace.get(previous.place_id).setIcon(pinIcon(previous, false));
  cardsByPlace.forEach((card, id) => card.classList.toggle("selected", id === r.place_id));
  const marker = markersByPlace.get(r.place_id);
  if (marker) {
    marker.setIcon(pinIcon(r, true));
    if (!fromMap) map.setView([r.lat, r.lon], Math.max(map.getZoom(), 16));
    marker.openPopup();
  }
  if (fromMap) cardsByPlace.get(r.place_id)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function visible() {
  const text = $("text-filter").value.trim().toLowerCase();
  const now = new Date();
  const list = results.filter((r) =>
    (!$("only-no-site").checked || r.site_status !== "has_site") &&
    (!$("only-phone").checked || phoneOf(r)) &&
    (!$("only-open").checked || openStatus(r, now).state === "open") &&
    (!text || (r.name + " " + (r.address || "")).toLowerCase().includes(text)));
  const sort = $("sort").value;
  const by = { rating: (a, b) => (b.rating || 0) - (a.rating || 0), reviews: (a, b) => (b.rating_count || 0) - (a.rating_count || 0),
    name: (a, b) => a.name.localeCompare(b.name, "el") };
  return list.sort(by[sort]);
}

function ensureMap() {
  if (map) return;
  map = L.map("map").setView([40.64, 22.94], 12);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
}

function renderMap(list) {
  ensureMap();
  markerLayer.clearLayers();
  markersByPlace.clear();
  const points = [];
  list.filter((r) => r.lat != null && r.lon != null).forEach((r) => {
    const marker = L.marker([r.lat, r.lon], { icon: pinIcon(r, r.place_id === selectedId), title: r.name });
    marker.bindPopup(popupFor(r));
    marker.on("click", () => selectPlace(r, true));
    marker.addTo(markerLayer);
    markersByPlace.set(r.place_id, marker);
    points.push([r.lat, r.lon]);
  });
  const key = points.map((p) => p.join()).join("|");
  if (points.length && key !== lastKey) map.fitBounds(points, { padding: [50, 50], maxZoom: 17 });   // re-zoom only if the pins changed
  lastKey = key;
}

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
  try { renderMap(list); } catch (e) { setStatus("Πρόβλημα στον χάρτη: " + e.message, true); }
}

function setMode(next) {
  mode = next;
  $("tab-category").classList.toggle("active", mode === "category");
  $("tab-all").classList.toggle("active", mode === "all");
  for (const id of ["query-wrap", "chips", "grid-wrap"]) $(id).hidden = mode === "all";
  for (const id of ["budget-wrap", "all-note"]) $(id).hidden = mode !== "all";
}

async function runSearch(area) {
  const query = mode === "all" ? ALL_QUERY : $("query").value.trim();
  const grid = Number($("grid").value);
  const maxCalls = mode === "all" ? Number($("budget").value) : GRID_CALLS[grid];
  const left = usage.limit - usage.calls_this_month;
  if ((mode === "all" || grid > 1) &&
      !confirm(`Η αναζήτηση θα χρησιμοποιήσει έως ${maxCalls} κλήσεις Google (απομένουν ${left} αυτόν τον μήνα). Συνέχεια;`)) return;
  setStatus(`Αναζήτηση «${query}» σε: ${area.display_name}`);
  $("search-btn").disabled = true;
  try {
    const { name, display_name, osm_type, osm_id, lat, lon, place_type, bbox } = area;
    const data = await api("/api/google/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, grid, mode, max_calls: Number($("budget").value), radius: Number($("radius").value) || 1500,
        area: { name, display_name, osm_type, osm_id, lat, lon, place_type, bbox } }),
    });
    results = data.results;
    selectedId = null;
    usage = { calls_this_month: data.calls_this_month, limit: data.limit };
    showUsage();
    const what = mode === "all" ? "όλα τα καταστήματα" : `«${query}»`;
    setStatus(`${results.length} καταστήματα · ${what} · ${area.display_name.split(",")[0]} · ${data.calls_used_now} κλήσεις` +
      (data.partial ? ` · ΣΤΑΜΑΤΗΣΕ νωρίς: ${data.stop_reason}` : ""), data.partial);
    render();
  } catch (e) { setStatus(e.message, true); } finally { $("search-btn").disabled = false; }
}

async function start() {
  const query = $("query").value.trim(), name = $("area-name").value.trim(), hint = $("area-hint").value.trim();
  if ((mode === "category" && query.length < 2) || name.length < 2) {
    setStatus(mode === "all" ? "Γράψε την περιοχή." : "Γράψε τι ψάχνεις και σε ποια περιοχή.", true); return;
  }
  try { localStorage.setItem("scanner-city", hint); } catch { /* storage may be blocked */ }
  $("pick-wrap").hidden = true;
  setStatus("Εύρεση περιοχής...");
  try {
    const params = new URLSearchParams({ name });
    if (hint) params.set("hint", hint);
    const areas = (await api("/api/resolve?" + params)).map((a) => ({ ...a, name }));
    if (!areas.length) { setStatus("Δεν βρέθηκε περιοχή. Δοκίμασε άλλο όνομα ή άλλαξε την πόλη.", true); return; }
    if (areas.length > 1) {   // search the best match at once; the dropdown lets you switch
      $("area-pick").replaceChildren(...areas.map((a, i) => el("option", { value: i, textContent: a.display_name.slice(0, 90) })));
      $("area-pick").onchange = () => runSearch(areas[Number($("area-pick").value)]);
      $("pick-wrap").hidden = false;
    }
    runSearch(areas[0]);
  } catch (e) { setStatus(e.message, true); }
}

async function init() {
  $("chips").replaceChildren(...CHIPS.map((c) => {
    const chip = el("button", { type: "button", className: "chip", textContent: c });
    chip.onclick = () => { $("query").value = c; $("area-name").focus(); };
    return chip;
  }));
  ["only-no-site", "only-phone", "only-open", "sort"].forEach((id) => $(id).addEventListener("change", render));
  $("text-filter").addEventListener("input", render);
  $("search-btn").onclick = start;
  $("tab-category").onclick = () => setMode("category");
  $("tab-all").onclick = () => setMode("all");
  ["query", "area-name", "area-hint"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") start(); }));
  try { $("area-hint").value = localStorage.getItem("scanner-city") ?? "Θεσσαλονίκη"; } catch { $("area-hint").value = "Θεσσαλονίκη"; }
  ensureMap();
  try {
    usage = await api("/api/google/status");
    if (!usage.configured) { setStatus("Λείπει το GOOGLE_PLACES_API_KEY από το .env", true); $("search-btn").disabled = true; }
    showUsage();
  } catch (e) { setStatus(e.message, true); }
  // Shareable link, e.g. /?q=φαρμακεία&area=Πεύκα&hint=Θεσσαλονίκη&auto=1
  const params = new URLSearchParams(location.search);
  if (params.get("q")) $("query").value = params.get("q");
  if (params.get("area")) $("area-name").value = params.get("area");
  if (params.get("hint") !== null) $("area-hint").value = params.get("hint");
  if (params.get("mode") === "all") setMode("all");
  if (params.get("auto") === "1" && !$("search-btn").disabled) start();
}

init();
