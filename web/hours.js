// Opening-hours helpers. Pure functions, so they can be tested with node (tests/test_hours_js.py).
// Google periods use day 0 = Sunday, like Date.getDay().
const DAY_NAMES_EL = ["Κυριακή", "Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο"];
const WEEK_MIN = 7 * 1440;
const pad2 = (n) => String(n).padStart(2, "0");
const clock = (point) => `${pad2(point.hour)}:${pad2(point.minute || 0)}`;
const minuteOfWeek = (point) => point.day * 1440 + point.hour * 60 + (point.minute || 0);

function periodRange(period) {
  const start = minuteOfWeek(period.open);
  if (!period.close) return [start, start + WEEK_MIN];   // no closing time = open all the time
  let end = minuteOfWeek(period.close);
  if (end <= start) end += WEEK_MIN;                       // closes after midnight / next week
  return [start, end];
}

function whenLabel(point, now) {
  const today = now.getDay();
  if (point.day === today) return "σήμερα";
  if (point.day === (today + 1) % 7) return "αύριο";
  return DAY_NAMES_EL[point.day];
}

// -> { state: "open" | "closed" | "unknown" | "gone", label }
function openStatus(place, now = new Date()) {
  if (place.business_status === "CLOSED_PERMANENTLY") return { state: "gone", label: "Έκλεισε οριστικά" };
  if (place.business_status === "CLOSED_TEMPORARILY") return { state: "closed", label: "Κλειστό προσωρινά" };
  const periods = place.opening_periods;
  if (!periods || !periods.length) return { state: "unknown", label: "Ωράριο μη διαθέσιμο" };

  const nowMin = now.getDay() * 1440 + now.getHours() * 60 + now.getMinutes();
  for (const period of periods) {
    const [start, end] = periodRange(period);
    if ((nowMin >= start && nowMin < end) || (nowMin + WEEK_MIN >= start && nowMin + WEEK_MIN < end)) {
      if (!period.close) return { state: "open", label: "Ανοιχτό 24 ώρες" };
      return { state: "open", label: `Ανοιχτό · κλείνει ${clock(period.close)}` };
    }
  }
  let next = null;
  for (const period of periods) {
    const wait = (minuteOfWeek(period.open) - nowMin + WEEK_MIN) % WEEK_MIN;
    if (!next || wait < next.wait) next = { wait, period };
  }
  const when = whenLabel(next.period.open, now);
  return { state: "closed", label: `Κλειστό · ανοίγει ${when} ${clock(next.period.open)}` };
}

// "8:00 π.μ.–9:00 μ.μ." for today, taken from Google's own weekday lines.
function todayHours(place, now = new Date()) {
  const name = DAY_NAMES_EL[now.getDay()];
  const line = (place.opening_hours || []).find((l) => l.startsWith(name));
  return line ? line.slice(line.indexOf(":") + 1).trim() : "";
}

if (typeof module !== "undefined") module.exports = { openStatus, todayHours };
