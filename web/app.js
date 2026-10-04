const SITE_LABELS = {
  none: "Χωρίς site", dead: "Νεκρό site", social_only: "Μόνο social", alive: "Έχει site", unchecked: "Μη ελεγμένο",
};
const CONTACT_LABELS = {
  new: "Νέο", called: "Κλήθηκε", interested: "Ενδιαφέρεται", not_interested: "Δεν ενδιαφέρεται", do_not_call: "Να μην καλεστεί",
};
const SELECT_FILTERS = ["area", "category", "site_status", "contact_status"];
const CHECK_FILTERS = ["leads_only", "has_phone", "verified"];
const $ = (id) => document.getElementById(id);

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

let timer;
const debounced = () => { clearTimeout(timer); timer = setTimeout(load, 250); };

async function init() {
  const f = await (await fetch("/api/filters")).json();
  f.areas.forEach((a) => $("area").append(el("option", { value: a, textContent: a })));
  f.categories.forEach((c) => $("category").append(el("option", { value: c, textContent: c })));
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
