const SITE_LABELS = {
  none: "Χωρίς site", dead: "Νεκρό site", social_only: "Μόνο social", alive: "Έχει site", unchecked: "Μη ελεγμένο",
};
const CONTACT_LABELS = {
  new: "Νέο", called: "Κλήθηκε", interested: "Ενδιαφέρεται", not_interested: "Δεν ενδιαφέρεται", do_not_call: "Να μην καλεστεί",
};
const FILTER_IDS = ["area", "category", "site_status", "contact_status", "q"];

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);   // textContent/href only: never innerHTML with data
  node.append(...children);
  return node;
}

function filterParams() {
  const params = new URLSearchParams();
  FILTER_IDS.forEach((id) => { if ($(id).value) params.set(id, $(id).value); });
  if ($("leads_only").checked) params.set("leads_only", "true");
  return params;
}

function safeHttpUrl(url) {
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(url) ? url : "https://" + url);
    return ["http:", "https:"].includes(u.protocol) ? u.href : null;
  } catch { return null; }
}

function googleUrl(b) {
  const query = [b.name, b.address, b.area].filter(Boolean).join(" ");
  return "https://www.google.com/search?q=" + encodeURIComponent(query);
}

async function save(id, body, box) {
  const res = await fetch(`/api/businesses/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) { alert("Η αποθήκευση απέτυχε"); return; }
  box.classList.add("saved");
  setTimeout(() => box.classList.remove("saved"), 800);
  if (body.contact_status === "do_not_call") load();   // it disappears from the list
}

function row(b) {
  const phone = b.phone
    ? el("a", { href: "tel:" + b.phone.replace(/[^\d+]/g, ""), textContent: b.phone })
    : "-";

  const site = el("td", {}, el("span", { className: "badge " + b.site_status, textContent: SITE_LABELS[b.site_status] }));
  const href = b.website_url && safeHttpUrl(b.website_url);
  if (href) site.append(el("small", {}, el("a", { href, target: "_blank", rel: "noopener noreferrer", textContent: b.website_url })));
  if (b.check_error) site.append(el("small", { textContent: b.check_error }));

  const contact = el("select");
  for (const [value, label] of Object.entries(CONTACT_LABELS)) {
    contact.append(el("option", { value, textContent: label, selected: value === b.contact_status }));
  }
  contact.onchange = () => save(b.id, { contact_status: contact.value }, contact);

  const notes = el("textarea", { value: b.notes || "", placeholder: "σημειώσεις κλήσης" });
  notes.onblur = () => { if (notes.value !== (b.notes || "")) { b.notes = notes.value; save(b.id, { notes: notes.value }, notes); } };

  return el("tr", {},
    el("td", {}, b.name, el("small", { textContent: `${b.area} · ${b.category}` })),
    el("td", {}, phone),
    el("td", { textContent: b.address || "-" }),
    el("td", { textContent: b.opening_hours || "-" }),
    site,
    el("td", {}, el("a", { href: googleUrl(b), target: "_blank", rel: "noopener noreferrer", textContent: "Αναζήτηση στο Google" })),
    el("td", {}, contact),
    el("td", {}, notes),
  );
}

async function load() {
  const params = filterParams();
  $("export").href = "/api/export.csv?" + params;
  const data = await (await fetch("/api/businesses?" + params)).json();
  $("rows").replaceChildren(...data.map(row));
  $("count").textContent = `${data.length} επιχειρήσεις`;
  $("empty").hidden = data.length > 0;
}

async function init() {
  const f = await (await fetch("/api/filters")).json();
  f.areas.forEach((a) => $("area").append(el("option", { value: a, textContent: a })));
  f.categories.forEach((c) => $("category").append(el("option", { value: c, textContent: c })));
  [...FILTER_IDS, "leads_only"].forEach((id) => $(id).addEventListener(id === "q" ? "input" : "change", debounced));
  load();
}

let timer;
function debounced() { clearTimeout(timer); timer = setTimeout(load, 250); }

init();
