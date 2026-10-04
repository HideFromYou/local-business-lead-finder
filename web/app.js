const SITE_LABELS = {
  none: "Χωρίς site", dead: "Νεκρό site", social_only: "Μόνο social", alive: "Έχει site", unchecked: "Μη ελεγμένο",
};
const CONTACT_LABELS = {
  new: "Νέο", called: "Κλήθηκε", interested: "Ενδιαφέρεται", not_interested: "Δεν ενδιαφέρεται", do_not_call: "Να μην καλεστεί",
};
const SELECT_FILTERS = ["area", "category", "site_status", "contact_status"];
const CHECK_FILTERS = ["leads_only", "has_phone", "verified"];
const $ = (id) => document.getElementById(id);

const CATEGORY_LABELS = {
  cafe: "Καφέ", restaurant: "Εστιατόριο", fast_food: "Fast food", bar: "Μπαρ", pharmacy: "Φαρμακείο",
  bakery: "Αρτοποιείο", butcher: "Κρεοπωλείο", supermarket: "Σούπερ μάρκετ", clothes: "Ρούχα",
  hairdresser: "Κομμωτήριο", beauty: "Αισθητική", florist: "Ανθοπωλείο", bookstore: "Βιβλιοπωλείο",
  electronics: "Ηλεκτρονικά", car_repair: "Συνεργείο", dentist: "Οδοντίατρος",
};

let sort = { key: null, desc: false };

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);   // textContent/href only: never innerHTML with data
  node.append(...children);
  return node;
}

function filterParams() {
  const params = new URLSearchParams();
  [...SELECT_FILTERS, "q"].forEach((id) => { if ($(id).value) params.set(id, $(id).value); });
  CHECK_FILTERS.forEach((id) => { if ($(id).checked) params.set(id, "true"); });
  if (sort.key) { params.set("sort", sort.key); if (sort.desc) params.set("desc", "true"); }
  return params;
}

function safeHttpUrl(url) {
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(url) ? url : "https://" + url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch { return null; }
}

const googleUrl = (b) =>
  "https://www.google.com/search?q=" + encodeURIComponent([b.name, b.address, b.area].filter(Boolean).join(" "));
const phoneOf = (b) => b.manual_phone || b.phone || "";

async function save(b, body, box, reload = false) {
  const res = await fetch(`/api/businesses/${b.id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) { alert("Η αποθήκευση απέτυχε"); return; }
  Object.assign(b, body);
  box.classList.add("saved");
  setTimeout(() => box.classList.remove("saved"), 800);
  if (reload || body.contact_status === "do_not_call") load();
}

function phoneCell(b) {
  const td = el("td");
  const phone = phoneOf(b);
  if (phone) {
    td.append(el("a", { className: "phone-link", href: "tel:" + phone.replace(/[^\d+]/g, ""), textContent: phone }));
    const copy = el("button", { className: "copy", textContent: "αντιγραφή", title: "Αντιγραφή αριθμού" });
    copy.onclick = async () => { await navigator.clipboard.writeText(phone); copy.textContent = "✓"; setTimeout(() => (copy.textContent = "αντιγραφή"), 900); };
    td.append(copy);
    if (!b.manual_phone) td.append(el("small", { textContent: "από OSM" }));
  }
  const input = el("input", { type: "text", className: "phone-input", maxLength: 40,
    value: b.manual_phone || "", placeholder: phone ? "άλλο τηλέφωνο" : "πρόσθεσε τηλέφωνο" });
  input.onblur = () => {
    if (input.value.trim() !== (b.manual_phone || "")) save(b, { manual_phone: input.value }, input, true);
  };
  input.onkeydown = (e) => { if (e.key === "Enter") input.blur(); };
  td.append(el("div", {}, input));
  return td;
}

function siteCell(b) {
  const td = el("td", {}, el("span", { className: "badge " + b.site_status, textContent: SITE_LABELS[b.site_status] }));
  const href = b.website_url && safeHttpUrl(b.website_url);
  if (href) td.append(el("small", {}, el("a", { href, target: "_blank", rel: "noopener noreferrer", textContent: b.website_url })));
  if (b.check_error) td.append(el("small", { textContent: b.check_error }));
  return td;
}

function verifyCell(b) {
  const checkbox = el("input", { type: "checkbox", checked: !!b.no_site_verified });
  const text = el("span", { className: "verify-text", textContent: b.no_site_verified ? "Επιβεβαιωμένο" : "Έλεγξα" });
  const td = el("td", { className: b.no_site_verified ? "verified-yes" : "" },
    el("div", { className: "verify" },
      el("a", { href: googleUrl(b), target: "_blank", rel: "noopener noreferrer", textContent: "Αναζήτηση στο Google ↗" }),
      el("label", {}, checkbox, text)));
  checkbox.onchange = () => save(b, { no_site_verified: checkbox.checked }, td, true);
  return td;
}

function row(b) {
  const contact = el("select");
  for (const [value, label] of Object.entries(CONTACT_LABELS)) {
    contact.append(el("option", { value, textContent: label, selected: value === b.contact_status }));
  }
  contact.onchange = () => { b.contact_status = contact.value; save(b, { contact_status: contact.value }, contact, true); };

  const notes = el("textarea", { value: b.notes || "", placeholder: "σημειώσεις κλήσης" });
  notes.onblur = () => { if (notes.value !== (b.notes || "")) save(b, { notes: notes.value }, notes); };

  return el("tr", { className: "s-" + b.contact_status },
    el("td", { className: "name" }, b.name, el("small", { textContent: `${b.area} · ${b.category}` })),
    phoneCell(b),
    el("td", { textContent: b.address || "-" }),
    el("td", { textContent: b.opening_hours || "-" }),
    siteCell(b),
    verifyCell(b),
    el("td", {}, contact),
    el("td", {}, notes),
  );
}

function renderStats(data) {
  const count = (fn) => data.filter(fn).length;
  const stats = [
    ["Επιχειρήσεις", data.length],
    ["Χωρίς site", count((b) => b.site_status === "none")],
    ["Νεκρό ή μόνο social", count((b) => ["dead", "social_only"].includes(b.site_status))],
    ["Με τηλέφωνο", count((b) => phoneOf(b))],
    ["Επιβεβαιωμένοι", count((b) => b.no_site_verified)],
    ["Έτοιμοι για κλήση", count((b) => phoneOf(b) && b.no_site_verified && b.contact_status === "new")],
  ];
  $("stats").replaceChildren(...stats.map(([label, n]) =>
    el("div", { className: "stat" }, el("b", { textContent: n }), el("span", { textContent: label }))));
}

async function load() {
  const params = filterParams();
  $("export").href = "/api/export.csv?" + params;
  const data = await (await fetch("/api/businesses?" + params)).json();
  $("rows").replaceChildren(...data.map(row));
  $("empty").hidden = data.length > 0;
  renderStats(data);
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.sort === sort.key);
    th.classList.toggle("desc", th.dataset.sort === sort.key && sort.desc);
  });
}

// ---- new area scan (OpenStreetMap) ----
let chosenArea = null;

async function api(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(typeof detail.detail === "string" ? detail.detail : `Σφάλμα ${res.status}`);
  }
  return res.json();
}

const setStatus = (text) => { $("scan-status").textContent = text; };

async function resolveArea() {
  const name = $("scan-name").value.trim();
  if (name.length < 2) { setStatus("Γράψε το όνομα της περιοχής."); return; }
  $("resolve-btn").disabled = true;
  setStatus("Αναζήτηση...");
  $("scan-categories").hidden = true;
  chosenArea = null;
  try {
    const params = new URLSearchParams({ name });
    if ($("scan-hint").value.trim()) params.set("hint", $("scan-hint").value.trim());
    const areas = await api("/api/resolve?" + params);
    if (!areas.length) { $("candidates").replaceChildren(); setStatus("Δεν βρέθηκε περιοχή. Δοκίμασε άλλο όνομα ή αφαίρεσε το φίλτρο."); return; }
    $("candidates").replaceChildren(...areas.map((a, i) => {
      const radio = el("input", { type: "radio", name: "candidate", checked: areas.length === 1 });
      radio.onchange = () => pickArea({ ...a, name });
      if (areas.length === 1) pickArea({ ...a, name });
      return el("label", { className: "candidate" }, radio,
        el("span", {}, a.display_name, el("small", { textContent: ` (${a.has_boundary ? "με όρια" : "σημείο, ακτίνα " + $("scan-radius").value + " m"})` })));
    }));
    setStatus(areas.length > 1 ? "Βρέθηκαν πολλές περιοχές. Διάλεξε τη σωστή." : "");
  } catch (e) { setStatus(e.message); } finally { $("resolve-btn").disabled = false; }
}

function pickArea(area) {
  chosenArea = area;
  $("scan-categories").hidden = false;
  setStatus("");
}

async function runScan() {
  const categories = [...document.querySelectorAll("#category-boxes input:checked")].map((i) => i.value);
  if (!chosenArea || !categories.length) { setStatus("Διάλεξε περιοχή και τουλάχιστον μία κατηγορία."); return; }
  const { name, display_name, osm_type, osm_id, lat, lon, place_type } = chosenArea;
  const radius = Number($("scan-radius").value) || 1500;
  $("scan-btn").disabled = true;
  let total = 0, fresh = 0;
  try {
    for (const [i, category] of categories.entries()) {
      setStatus(`(${i + 1}/${categories.length}) ${CATEGORY_LABELS[category] || category}...`);
      const r = await api("/api/scan", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ area: { name, display_name, osm_type, osm_id, lat, lon, place_type }, category, radius }),
      });
      total += r.found; fresh += r.new;
    }
    setStatus(`Έτοιμο: ${total} επιχειρήσεις, ${fresh} νέες. Πάτα «Έλεγχος sites» για όσες έχουν website.`);
    await refreshFilters();
    load();
  } catch (e) { setStatus("Σταμάτησε: " + e.message); } finally { $("scan-btn").disabled = false; }
}

async function runChecks() {
  const { pending } = await api("/api/check/pending");
  if (!pending) { alert("Δεν υπάρχουν sites προς έλεγχο."); return; }
  if (pending > 20 && !confirm(`Θα σταλούν αιτήματα σε ${pending} sites. Συνέχεια;`)) return;
  $("check-btn").disabled = true;
  $("check-btn").textContent = `Έλεγχος ${pending} sites...`;
  try {
    const r = await api("/api/check", { method: "POST" });
    alert(`Ελέγχθηκαν ${r.checked}: ${r.alive || 0} ζωντανά, ${r.dead || 0} νεκρά, ${r.social_only || 0} μόνο social.`);
    load();
  } catch (e) { alert(e.message); } finally {
    $("check-btn").disabled = false; $("check-btn").textContent = "Έλεγχος sites";
  }
}

async function refreshFilters() {
  const f = await api("/api/filters");
  for (const [id, values] of [["area", f.areas], ["category", f.categories]]) {
    const select = $(id), current = select.value;
    select.replaceChildren(el("option", { value: "", textContent: "Όλες" }),
      ...values.map((v) => el("option", { value: v, textContent: v })));
    select.value = current;
  }
}

let timer;
const debounced = () => { clearTimeout(timer); timer = setTimeout(load, 250); };

async function init() {
  await refreshFilters();
  const categories = await api("/api/categories");
  $("category-boxes").replaceChildren(...categories.map((c) =>
    el("label", {}, el("input", { type: "checkbox", value: c, checked: c === "cafe" }), CATEGORY_LABELS[c] || c)));
  const setAll = (on) => document.querySelectorAll("#category-boxes input").forEach((i) => { i.checked = on; });
  $("cat-all").onclick = () => setAll(true);
  $("cat-none").onclick = () => setAll(false);
  $("resolve-btn").onclick = resolveArea;
  $("scan-name").addEventListener("keydown", (e) => { if (e.key === "Enter") resolveArea(); });
  $("scan-btn").onclick = runScan;
  $("check-btn").onclick = runChecks;
  SELECT_FILTERS.concat(CHECK_FILTERS).forEach((id) => $(id).addEventListener("change", load));
  $("q").addEventListener("input", debounced);
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.onclick = () => {
      sort = { key: th.dataset.sort, desc: sort.key === th.dataset.sort && !sort.desc };
      load();
    };
  });
  load();
}

init();
