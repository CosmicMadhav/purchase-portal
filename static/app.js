// Purchase Portal front-end (plain JS, no build step).
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const S = { settings: null, projects: [], vendors: [], items: [], advDefs: [], cvDefs: [] };

// ---------------------------------------------------------------- helpers
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(o.body); }
  const r = await fetch(path, o);
  const data = await r.json().catch(() => ({}));
  if (r.status === 401) { location.href = "/login"; throw new Error("Please log in"); }
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
}
function toast(msg, bad = false) {
  const d = h("div", { class: bad ? "bad" : "" }, msg);
  $("#toast").append(d);
  setTimeout(() => d.remove(), bad ? 8000 : 3500);
}
const num = (v) => (v === "" || v === null || v === undefined || isNaN(Number(v)) ? 0 : Number(v));
const r2 = (x) => Math.round((Number(x) + Number.EPSILON) * 100) / 100;
const inr = (x) => (num(x) < 0 ? "−" : "") + "₹" + Math.abs(num(x)).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const today = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const dmy = (d) => (d && /^\d{4}-\d{2}-\d{2}/.test(d) ? d.slice(0, 10).split("-").reverse().join("-") : d || "");
const projById = (id) => S.projects.find((p) => String(p.id) === String(id)) || {};

function field(label, input, hint, cls = "") {
  return h("label", { class: "f " + cls }, h("span", {}, label, hint ? h("small", {}, "  " + hint) : null), input);
}
function inp(obj, key, attrs = {}, onchange) {
  const el = h("input", { value: obj[key] ?? "", ...attrs });
  el.addEventListener("input", () => {
    obj[key] = attrs.type === "number" ? (el.value === "" ? "" : Number(el.value)) : el.value;
    onchange && onchange();
  });
  return el;
}
function area(obj, key, attrs = {}, onchange) {
  const el = h("textarea", { rows: attrs.rows || 2, ...attrs }, obj[key] ?? "");
  el.addEventListener("input", () => { obj[key] = el.value; onchange && onchange(); });
  return el;
}
function autoGrow(el) {
  const fit = () => { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; };
  el.addEventListener("input", fit);
  requestAnimationFrame(fit);
  return el;
}
function sel(obj, key, options, onchange) {
  const el = h("select", {}, options.map(([v, t]) => h("option", { value: v }, t)));
  if (obj[key] === undefined || obj[key] === null || !options.some(([v]) => String(v) === String(obj[key]))) obj[key] = options[0]?.[0] ?? "";
  el.value = obj[key];
  el.addEventListener("change", () => { obj[key] = el.value; onchange && onchange(); });
  return el;
}
function chk(obj, key, label, onchange) {
  const el = h("input", { type: "checkbox", checked: !!obj[key] });
  el.addEventListener("change", () => { obj[key] = el.checked; onchange && onchange(); });
  return h("label", { class: "c" }, el, label);
}
async function busy(btn, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="spin"></span> ' + old;
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; btn.innerHTML = old; }
}
function modal(content) {
  const back = h("div", { class: "modal-back", onclick: (e) => e.target === back && back.remove() }, h("div", { class: "modal", role: "dialog" }, content));
  document.body.append(back);
  const esc = (e) => { if (e.key === "Escape") { back.remove(); document.removeEventListener("keydown", esc); } };
  document.addEventListener("keydown", esc);
  return () => back.remove();
}
function lineTotals(q) {   // same rules as money.totals on the server
  let sub = 0, gst = 0;
  for (const it of q.items || []) {
    const l = r2(num(it.qty) * num(it.rate)); sub += l;
    gst += l * (it.gst === "" || it.gst === undefined || it.gst === null ? 18 : num(it.gst)) / 100;
  }
  sub = r2(sub);
  const disc = r2(num(q.discount));
  if (sub && disc) gst = gst * (sub - disc) / sub;
  const ship = r2(num(q.other));
  gst = r2(gst + ship * num(q.other_gst) / 100);
  if (q.gst_override !== "" && q.gst_override !== undefined && q.gst_override !== null) gst = r2(num(q.gst_override));
  const other = r2(ship + num(q.round_off));
  return { sub, disc, gst, other, grand: r2(sub - disc + gst + other) };
}
const DOC_NAMES = { permission: "Purchase Permission", po: "Purchase Order", rfq: "Quotation request letters",
  advance_voucher: "Advance Voucher", advance_adjustment: "Advance Adjustment Voucher", cash_voucher: "Cash Voucher", waiver: "Waiver form" };
function docsList(rec) {
  if (!rec.docs || !rec.docs.length) return h("p", { class: "muted small-t", style: "margin:0" }, "Generated files will appear here.");
  const base = (f) => f.split(/[\\/]/).pop();
  const open = (f, d) => window.open("/api/file?path=" + encodeURIComponent(f) + "&v=" + encodeURIComponent(d.made));
  return h("div", { class: "docs" }, rec.docs.map((d) => {
    // one line per document (one per vendor for request letters), PDF first
    const groups = {};
    d.files.forEach((f) => { const k = base(f).replace(/\.\w+$/, ""); (groups[k] = groups[k] || []).push(f); });
    return h("div", { class: "doc", "data-t": "doc-" + d.kind },
      h("div", { class: "doc-top" }, h("b", {}, DOC_NAMES[d.kind] || d.kind), h("span", { class: "when" }, d.made.replace("T", " ").slice(0, 16)),
        S.settings.can_open_folder ? h("a", { class: "folder", onclick: () => api("/api/open-folder", { method: "POST", body: { path: d.files[0] } }) }, "Open folder") : null),
      h("div", { class: "when", title: d.files[0] }, "Saved in " + docFolder(d.files[0])),
      Object.entries(groups).map(([name, files]) => h("div", { class: "doc-line" },
        h("span", { class: "doc-name" }, d.kind === "rfq" ? name.replace(/^Quotation Request - /, "") : ""),
        h("span", { class: "links" }, files.slice().sort((a, b) => (a.endsWith(".pdf") ? -1 : 0) - (b.endsWith(".pdf") ? -1 : 0))
          .map((f) => h("a", { title: base(f), onclick: () => open(f, d) }, f.split(".").pop().toUpperCase()))))));
  }));
}
function docFolder(f) {
  // path inside the portal's output folder, written the Windows way: data\output\KISAN KAWACH\Purchase 2 - …
  const norm = f.split("\\").join("/");
  const i = norm.indexOf("/output/");
  const rel = i >= 0 ? "data/output/" + norm.slice(i + 8) : norm;
  return rel.split("/").slice(0, -1).join("\\");
}
function emptyState(text, btnLabel, onclick) {
  return h("div", { class: "empty" }, h("div", {}, text), btnLabel ? h("button", { class: "primary", onclick }, btnLabel) : null);
}

// ---------------------------------------------------------------- data
async function loadBase() {
  [S.settings, S.projects, S.vendors, S.items, S.advDefs, S.cvDefs] = await Promise.all([
    api("/api/settings"), api("/api/projects"), api("/api/vendors"), api("/api/items"),
    api("/api/stages/advances"), api("/api/stages/reimbursements")]);
}
const vendorDatalist = () => h("datalist", { id: "dl-vendors" }, S.vendors.map((v) => h("option", { value: v.name })));
const itemDatalist = () => h("datalist", { id: "dl-items" }, S.items.map((i) => h("option", { value: i.description })));
const projOptions = () => S.projects.map((p) => [String(p.id), p.name]);
const ROUTES = { po: "Purchase Order to the vendor", card: "Direct payment (Nirma card)", advance: "From an advance", personal: "Own money, then reimbursement" };

// ---------------------------------------------------------------- router
const views = {};
const go = (view, arg) => { location.hash = arg !== undefined ? `${view}/${arg}` : view; };
let dirty = false;
async function route() {
  const [view, arg] = (location.hash.slice(1) || "dashboard").split("/");
  const base = { "purchase-edit": "purchases", "advance-edit": "advances", "reimbursement-edit": "reimbursements" }[view] || view;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === base));
  main.innerHTML = "";
  dirty = false;
  try { await loadBase(); await (views[view] || views.dashboard)(arg); }
  catch (e) { main.append(h("div", { class: "note bad" }, e.message)); }
  window.scrollTo(0, 0);
}
document.querySelectorAll("[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); go(a.dataset.view); }));
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

function nextStep(rec, defs) {
  const done = rec.stages || {};
  const s = defs.find((x) => !done[x.key]);
  return s ? h("span", { class: "pill wait" }, s.label) : h("span", { class: "pill ok" }, "Complete");
}
function head(title, lede, ...actions) {
  return h("div", { class: "head" }, h("div", { class: "grow" }, h("h1", {}, title), lede ? h("p", { class: "lede" }, lede) : null), ...actions);
}

// ---------------------------------------------------------------- overview
views.dashboard = async () => {
  const [purchases, advances, reims] = await Promise.all([api("/api/purchases"), api("/api/advances"), api("/api/reimbursements")]);
  main.append(head("Overview", "Where the grant stands and which papers are waiting on a signature."));
  for (const p of S.projects.filter((p) => num(p.provision) > 0)) {
    const b = await api("/api/budget/" + p.id);
    const pct = Math.min(100, (b.utilized / (b.provision || 1)) * 100);
    main.append(h("section", { class: "sheet", "data-t": "budget" },
      h("header", {}, h("h2", {}, p.name), h("span", { class: "pill ink" }, "Budget head " + (p.budget_code || "—"))),
      h("div", { class: "budget" },
        h("div", {}, h("div", { class: "big", "data-t": "available", style: b.available < 0 ? "color:var(--red)" : "" }, inr(b.available)), h("div", { class: "muted" }, "left to spend")),
        h("div", {}, h("div", { class: "meter" }, h("i", { class: b.available < 0 ? "over" : "", style: `width:${pct}%` })),
          h("div", { class: "legend" }, h("span", {}, `${inr(b.utilized)} spent`), h("span", {}, `of ${inr(b.provision)}`)))),
      h("details", { class: "more", style: "margin-top:14px" }, h("summary", {}, `What makes up the spent amount (${b.entries.length + (b.opening ? 1 : 0)} entries)`),
        h("div", { class: "table-wrap" }, h("table", {},
          b.opening ? h("tr", {}, h("td", {}, `Spent before the portal (as of ${dmy(b.opening_as_of)})`), h("td", { class: "num" }, inr(b.opening))) : null,
          b.entries.map((e) => h("tr", {}, h("td", {}, [e.date ? dmy(e.date) + "  " : "", e.what || ""]), h("td", { class: "num" }, inr(e.amount)))))))));
  }
  main.append(h("div", { class: "quick" },
    h("button", { class: "primary", "data-t": "new-purchase", onclick: () => go("purchase-edit", "new") }, "New purchase"),
    h("button", { onclick: () => go("advance-edit", "new") }, "New advance request"),
    h("button", { onclick: () => go("reimbursement-edit", "new") }, "New reimbursement")));
  const open = purchases.filter((p) => !(p.stages || {}).settled);
  main.append(h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Purchases in progress")),
    open.length ? purchaseTable(open) : emptyState("Nothing in progress. Start with the quotations you have.", "New purchase", () => go("purchase-edit", "new"))));
  const openAdv = advances.filter((a) => !(a.stages || {}).settled);
  if (openAdv.length) main.append(h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Advances not settled")), advanceTable(openAdv)));
  const openR = reims.filter((r) => !(r.stages || {}).reimbursed);
  if (openR.length) main.append(h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Reimbursements pending")), reimTable(openR)));
};

function purchaseTable(list) {
  const defs = S.settings.stages;
  return h("div", { class: "table-wrap" }, h("table", { "data-t": "purchase-table" },
    h("tr", {}, h("th", {}, "Date"), h("th", {}, "Purchase"), h("th", { class: "hide-sm" }, "Vendor"), h("th", { class: "num" }, "Amount"), h("th", { class: "hide-sm" }, "Approval"), h("th", {}, "Next step")),
    list.map((p) => {
      const q = (p.quotes || [])[p.selected || 0] || {};
      const applicable = defs.filter((d) => !d.if || (p.req || {})[d.if]);
      return h("tr", { class: "link", onclick: () => go("purchase-edit", p.id) },
        h("td", {}, dmy(p.date)), h("td", {}, p.title || "Untitled purchase"), h("td", { class: "hide-sm" }, (q.vendor || {}).name || "—"),
        h("td", { class: "num" }, inr(p.amount)), h("td", { class: "hide-sm" }, (p.req || {}).authority_name || ""), h("td", {}, nextStep(p, applicable)));
    })));
}

// ---------------------------------------------------------------- purchases
views.purchases = async () => {
  const list = await api("/api/purchases");
  main.append(head("Purchases", "Every purchase permission with its quotations, order and progress.",
    h("button", { class: "primary", onclick: () => go("purchase-edit", "new") }, "New purchase")));
  main.append(h("section", { class: "sheet" }, list.length ? purchaseTable(list) : emptyState("No purchases yet.", "New purchase", () => go("purchase-edit", "new"))));
};

function blankQuote() { return { vendor: { name: "" }, quote_no: "", quote_date: "", payment: "", delivery: "", items: [{ description: "", qty: 1, rate: "", gst: 18 }], discount: "", other: "", other_gst: "", round_off: "", gst_override: "" }; }

function routeFor(proj, authority) {
  if (proj.letter_style === "incubation")
    return [{ who: proj.mentor_name || "Mentor", note: "Prepared by", on: true }, { who: (proj.through || "Incubation cell").split("\n")[0], note: "Through", on: true }, { who: (proj.to || "Head").split("\n")[0], note: "Approves", to: true }];
  const hod = proj.hod || "HoD- EC", ar = proj.ar || "Asst. Registrar", dir = proj.director || "Director", er = proj.exec_registrar || "Exec. Registrar", vp = proj.vp || "Vice President";
  const all = [{ who: proj.mentor_name || "Mentor", note: "Prepared by", on: true }];
  if (authority === "hod" || authority === "hod_statement") return all.concat([{ who: hod, note: "Approves", to: true }]);
  all.push({ who: hod, note: "Through", on: true }, { who: ar, note: "Through", on: true });
  if (authority === "director") return all.concat([{ who: dir, note: "Approves", to: true }]);
  return all.concat([{ who: dir, note: "Through", on: true }, { who: er, note: "Through", on: true }, { who: vp, note: "Approves", to: true }]);
}

views["purchase-edit"] = async (id) => {
  let p = id && id !== "new" ? await api("/api/purchases/" + id) : {
    project_id: String(S.projects[0]?.id || ""), date: today(), title: "", route: "po", quotes: [blankQuote()], selected: 0,
    list_items_in_subject: true, stages: {}, docs: [],
  };
  p.quotes = p.quotes && p.quotes.length ? p.quotes : [blankQuote()];
  let req = null;
  const slipBox = h("div", { class: "slip", "data-t": "slip" });
  const quotesBox = h("div");
  const docsBox = h("div");
  const stepsBox = h("div", { class: "steps" });
  const titleEl = h("h1", {}, p.title || "New purchase");
  const touch = () => { dirty = true; };

  async function refreshRules() {
    req = await api("/api/rules", { method: "POST", body: p });
    const proj = projById(p.project_id);
    const authority = p.authority_override || req.authority;
    const grands = req.all_totals.map((t) => t.grand);
    const valid = grands.filter((g) => g > 0);
    const lo = valid.length ? grands.indexOf(Math.min(...valid)) : -1;
    slipBox.replaceChildren(
      h("div", { class: "slip-amt" }, h("div", { class: "k" }, "Purchase value (selected quotation)"), h("div", { class: "v", "data-t": "amount" }, inr(req.totals.grand)), h("div", { class: "k" }, req.label)),
      h("div", { class: "slip-sec" }, h("h3", {}, "Signature route"),
        h("ol", { class: "route", "data-t": "route" }, routeFor(proj, authority).map((r) => h("li", { class: (r.on ? "on " : "") + (r.to ? "on to" : "") }, r.who, h("small", {}, r.note))))),
      h("div", { class: "slip-sec" }, h("dl", { class: "facts" },
        h("dt", {}, "Quotations"), h("dd", {}, `${req.quotes_have} of ${req.quotes} `, h("span", { class: "pill " + (req.quotes_ok ? "ok" : "bad") }, req.quotes_ok ? "enough" : "add more")),
        h("dt", {}, "Purchase order"), h("dd", {}, req.po ? (req.tally_po ? "Tally + normal" : "Needed") : "Not needed"),
        h("dt", {}, "Internal audit"), h("dd", {}, req.audit ? "Needed, then outward" : "Not needed")),
        lo >= 0 && p.quotes.length > 1 && lo !== Number(p.selected || 0)
          ? h("div", { class: "note", "data-t": "l1-note" }, `Lowest quotation is ${(p.quotes[lo].vendor || {}).name || "Quotation " + (lo + 1)}. Buying from another vendor needs a justification or waiver.`) : null),
      h("div", { class: "slip-sec" }, h("h3", {}, "Papers for this purchase"), h("ul", { class: "needs" }, req.documents.map((d) => h("li", {}, d)))));
    renderSteps();
  }
  let tmr;
  const debounceRules = () => { clearTimeout(tmr); tmr = setTimeout(refreshRules, 250); };

  function renderQuotes() {
    quotesBox.replaceChildren(...p.quotes.map((q, qi) => quoteCard(q, qi)));
  }

  function quoteCard(q, qi) {
    q.vendor = q.vendor || { name: "" };
    const isSel = Number(p.selected || 0) === qi;
    const sumBox = h("div", { class: "q-sum" });
    const totalEl = h("div", { class: "total", "data-t": "quote-total" });
    const warnBox = h("div");
    const changed = () => { touch(); updTot(); debounceRules(); };
    function updTot() {
      const t = lineTotals(q);
      totalEl.textContent = inr(t.grand);
      sumBox.replaceChildren(h("div", {}, "Total", h("b", {}, inr(t.sub - t.disc))), h("div", {}, "GST", h("b", {}, inr(t.gst))),
        h("div", {}, "Other charges", h("b", {}, inr(t.other))), h("div", {}, "Grand total", h("b", {}, inr(t.grand))));
      warnBox.innerHTML = "";
      if (q.scanned_grand && Math.abs(num(q.scanned_grand) - t.grand) > 1)
        warnBox.append(h("div", { class: "note" }, `The scanned quotation's total is ${inr(q.scanned_grand)}, these figures give ${inr(t.grand)}. Check quantities, rates, shipping GST or round off.`));
      if (q.scanned_items && q.scanned_items.length) {
        const key = (i) => `${String(i.description || "").trim().toLowerCase()}|${num(i.qty)}|${num(i.rate)}`;
        const quoted = new Set(q.scanned_items.map(key));
        const extra = (q.items || []).filter((i) => i.description && !quoted.has(key(i)));
        if (extra.length) warnBox.append(h("div", { class: "note", "data-t": "mismatch" }, `Not as in ${(q.vendor || {}).name || "this vendor"}'s uploaded quotation: ${extra.map((i) => i.description).join(", ")}. Ask the vendor for a revised quotation ("Make quotation request letters") and read it in.`));
      }
      if (q.gst_override !== "" && q.gst_override !== undefined && q.gst_override !== null)
        warnBox.append(h("div", { class: "note" }, "GST is fixed by the override, so it will not change when you edit items."));
    }

    const nameEl = h("span", { class: "name" }, q.vendor.name || `Quotation ${qi + 1}`);
    const vName = h("input", { value: q.vendor.name || "", list: "dl-vendors", placeholder: "Start typing a saved vendor", "data-t": "vendor" });
    const vAddr = h("textarea", { rows: 2, placeholder: "Printed on the purchase order" }, q.vendor.address || "");
    const vGst = h("input", { value: q.vendor.gst || "", placeholder: "15-character GSTIN" });
    vName.addEventListener("input", () => { q.vendor.name = vName.value; touch(); nameEl.textContent = vName.value || `Quotation ${qi + 1}`; });
    vName.addEventListener("change", () => {
      const v = S.vendors.find((x) => x.name.toLowerCase() === vName.value.trim().toLowerCase());
      if (v) {
        q.vendor = { id: v.id, name: v.name, address: v.address, gst: v.gst, phone: v.phone, email: v.email };
        if (!q.payment && v.payment) q.payment = v.payment;
        if (!q.delivery && v.delivery) q.delivery = v.delivery;
        renderQuotes(); debounceRules();
      }
    });
    vAddr.addEventListener("input", () => { q.vendor.address = vAddr.value; touch(); });
    vGst.addEventListener("input", () => { q.vendor.gst = vGst.value; touch(); });

    const itemsBox = h("div", { class: "items" });
    const drawItems = () => {
      itemsBox.replaceChildren(h("div", { class: "it-row headr" }, h("span", {}, "Item description"), h("span", {}, "Qty"), h("span", {}, "Rate (before GST)"), h("span", {}, "GST %"), h("span", {}, "Amount"), h("span", {})));
      q.items.forEach((it, ii) => {
        const amt = h("div", { class: "amt" }, inr(num(it.qty) * num(it.rate)));
        const upd = () => { amt.textContent = inr(num(it.qty) * num(it.rate)); changed(); };
        const d = autoGrow(area(it, "description", { rows: 1, placeholder: "Item as written in the quotation", "data-t": "item-desc" }, upd));
        d.addEventListener("blur", () => {
          const known = S.items.find((x) => x.description.toLowerCase() === d.value.trim().toLowerCase());
          if (known && !it.rate) { it.rate = known.rate; it.gst = known.gst ?? 18; it.hsn = known.hsn; drawItems(); changed(); toast(`Filled last rate ${inr(known.rate)} (${known.vendor || "earlier purchase"})`); }
        });
        const cell = (lbl, el) => h("div", {}, h("span", { class: "lbl" }, lbl), el);
        itemsBox.append(h("div", { class: "it-row" },
          d,
          cell("Qty", inp(it, "qty", { type: "number", step: "any", min: 0, "data-t": "item-qty" }, upd)),
          cell("Rate", inp(it, "rate", { type: "number", step: "any", min: 0, "data-t": "item-rate" }, upd)),
          cell("GST %", inp(it, "gst", { type: "number", step: "any", min: 0 }, upd)),
          amt,
          h("button", { class: "icon-btn", title: "Remove item", "aria-label": "Remove item", onclick: () => { q.items.splice(ii, 1); if (!q.items.length) q.items.push({ description: "", qty: 1, rate: "", gst: 18 }); drawItems(); changed(); } }, "×")));
      });
    };
    drawItems();
    updTot();

    const scanInput = h("input", { type: "file", accept: ".pdf,image/*", style: "display:none", "data-t": "scan-input" });
    const scanBtn = h("button", { class: "sm", onclick: () => scanInput.click() }, "Read from PDF / photo");
    scanInput.addEventListener("change", () => busy(scanBtn, async () => {
      if (!scanInput.files[0]) return;
      const fd = new FormData(); fd.append("file", scanInput.files[0]); fd.append("kind", "quote");
      const res = await api("/api/scan", { method: "POST", body: fd });
      const nq = res.quote;
      Object.assign(q, { ...nq, items: nq.items.length ? nq.items : q.items });
      if (res.warning) toast("The AI reader failed, so only basic details were read: " + res.warning, true);
      else toast(res.vendor_match ? `Read. Matched saved vendor ${res.vendor_match.name}. Check the figures.` : "Read. New vendor will be saved. Check the figures.");
      touch(); renderQuotes(); debounceRules();
    }));

    const radio = h("input", { type: "radio", name: "selq", checked: isSel, "aria-label": "Buy from this vendor", "data-t": "select-quote" });
    radio.addEventListener("change", () => { p.selected = qi; touch(); renderQuotes(); debounceRules(); });

    return h("article", { class: "quote" + (isSel ? " sel" : ""), "data-t": "quote" },
      h("div", { class: "q-head" },
        h("label", { class: "c" }, radio, isSel ? h("span", { class: "pill ink" }, "Buying from") : h("span", { class: "muted small-t" }, "Buy from this")),
        nameEl, totalEl),
      h("div", { class: "q-body" },
        h("div", { class: "grid g2" }, field("Vendor", vName), field("GSTIN", vGst)),
        h("div", { class: "grid g4" }, field("Quotation no.", inp(q, "quote_no", {}, touch)), field("Quotation date", inp(q, "quote_date", { type: "date" }, touch)),
          field("Payment condition", inp(q, "payment", { placeholder: "After 15 days of delivery" }, touch)), field("Delivery time", inp(q, "delivery", { placeholder: "7-10 working days" }, touch))),
        itemsBox,
        h("div", { class: "row" },
          h("button", { class: "sm", "data-t": "add-item", onclick: () => { q.items.push({ description: "", qty: 1, rate: "", gst: 18 }); drawItems(); } }, "Add item"),
          qi > 0 ? h("button", { class: "sm quiet", title: "Copy the item list of the first quotation, then enter this vendor's rates", onclick: () => { q.items = p.quotes[0].items.map((i) => ({ description: i.description, qty: i.qty, rate: "", gst: i.gst })); touch(); renderQuotes(); debounceRules(); } }, "Copy items from first quotation") : null,
          h("span", { class: "grow" }), scanBtn, scanInput,
          p.quotes.length > 1 ? h("button", { class: "sm quiet danger", onclick: () => { if (!confirm("Remove this quotation?")) return; p.quotes.splice(qi, 1); if (Number(p.selected) >= p.quotes.length || Number(p.selected) === qi) p.selected = 0; touch(); renderQuotes(); debounceRules(); } }, "Remove quotation") : null),
        h("details", { class: "more", open: num(q.discount) || num(q.other) || num(q.round_off) ? true : null },
          h("summary", {}, "Discount, shipping, round off and address"),
          h("div", { class: "grid g4" }, field("Discount (₹)", inp(q, "discount", { type: "number", step: "any" }, changed)),
            field("Shipping / other (₹)", inp(q, "other", { type: "number", step: "any", "data-t": "shipping" }, changed), "before GST"),
            field("GST on shipping (%)", inp(q, "other_gst", { type: "number", step: "any", placeholder: "0", "data-t": "shipping-gst" }, changed)),
            field("Round off (₹)", h("div", { class: "inline" }, inp(q, "round_off", { type: "number", step: "any", placeholder: "0" }, changed),
              h("button", { class: "sm", "data-t": "round", title: "Round the grand total to the nearest rupee", onclick: () => { q.round_off = 0; const t = lineTotals(q); q.round_off = r2(Math.round(t.grand) - t.grand); touch(); renderQuotes(); debounceRules(); } }, "Round")))),
          h("div", { class: "grid g2", style: "margin-top:12px" }, field("Address", vAddr, "printed on the purchase order"),
            field("GST amount override (₹)", inp(q, "gst_override", { type: "number", step: "any", placeholder: "Calculated automatically" }, changed), "only if the vendor's GST differs"))),
        q.file ? h("div", { class: "small-t muted" }, "Quotation file: ", h("a", { href: "/api/file?path=" + encodeURIComponent(q.file), target: "_blank" }, q.file.split(/[\\/]/).pop().replace(/^[\dT\-]+_/, ""))) : null,
        sumBox, warnBox));
  }

  async function save(silent) {
    const fresh = !p.id;
    p = await api("/api/purchases", { method: "POST", body: p });
    p.quotes = p.quotes.length ? p.quotes : [blankQuote()];
    dirty = false;
    if (!silent) toast("Saved");
    if (fresh) history.replaceState(null, "", "#purchase-edit/" + p.id);
    titleEl.textContent = p.title || "Purchase";
    renderDocs(); renderSteps(); renderQuotes();
    return p;
  }
  async function gen(kind, btn) {
    await busy(btn, async () => {
      await save(true);
      p = await api(`/api/generate/${kind}/${p.id}`, { method: "POST", body: {} });
      toast(DOC_NAMES[kind] + " ready");
      renderDocs(); renderSteps();
    });
  }
  function renderDocs() {
    const proj = projById(p.project_id);
    const bPerm = h("button", { class: "primary", "data-t": "gen-permission", onclick: () => gen("permission", bPerm) }, p.post_facto ? "Make Post-facto Permission" : "Make Purchase Permission");
    const bPo = h("button", { "data-t": "gen-po", onclick: () => gen("po", bPo) }, "Make Purchase Order");
    const bRfq = h("button", { "data-t": "gen-rfq", onclick: () => gen("rfq", bRfq) }, "Make quotation request letters");
    docsBox.replaceChildren(h("div", { class: "gen" }, bPerm, proj.letter_style !== "incubation" ? [bPo, bRfq] : null), h("div", { style: "margin-top:12px" }, docsList(p)));
  }
  function renderSteps() {
    if (!req) return;
    const done = p.stages || {};
    stepsBox.replaceChildren(...req.stages.map((s) => {
      const locked = (s.needs || []).some((n) => req.stages.some((x) => x.key === n) && !done[n]);
      const box = h("input", { type: "checkbox", checked: !!done[s.key], "data-t": "stage-" + s.key });
      box.addEventListener("change", async () => {
        try {
          if (!p.id) await save(true);
          p = await api(`/api/purchases/${p.id}/stage`, { method: "POST", body: { key: s.key, done: box.checked } });
          renderSteps(); refreshRules();
        } catch (e) { box.checked = !box.checked; toast(e.message, true); }
      });
      return h("label", { class: "step" + (done[s.key] ? " done" : "") + (locked && !done[s.key] ? " locked" : "") }, box, s.label, h("span", { class: "when" }, done[s.key] ? dmy(done[s.key]) : ""));
    }));
  }

  const postFactoBox = h("div");
  const drawPostFacto = () => postFactoBox.replaceChildren(p.post_facto
    ? h("div", { style: "margin-top:10px" }, field("Justification for buying without prior permission",
        autoGrow(area(p, "justification", { rows: 3, placeholder: "Why it had to be bought before approval (deadline, stock running out…). Leave blank for the standard wording.", "data-t": "justification" }, touch))),
        h("div", { class: "note info" }, "The letter becomes a post-facto approval request. Fewer than 3 quotations are allowed; attach a Waiver form from the reimbursement if the procedure was not followed."))
    : "");
  drawPostFacto();
  const nirmaCard = "The payment may please be made directly to the vendor using the NU WiFi Card (Nirma Card) at the time of purchase. No purchase order or reimbursement process is required, as the payment will be executed directly through the Nirma Card to the vendor.";
  const extraBox = h("div");
  const drawExtra = () => extraBox.replaceChildren(p.extra_paragraphs && p.extra_paragraphs.length
    ? h("div", { class: "note info" }, "Extra paragraph added: Nirma card payment. ", h("button", { class: "sm quiet", onclick: () => { p.extra_paragraphs = []; touch(); drawExtra(); } }, "Remove"))
    : h("button", { class: "sm", onclick: () => { p.extra_paragraphs = [nirmaCard]; touch(); drawExtra(); } }, "Add the Nirma card payment paragraph"));
  drawExtra();

  main.append(vendorDatalist(), itemDatalist(),
    h("a", { class: "back", onclick: () => go("purchases") }, "‹ All purchases"),
    h("div", { class: "head" }, h("div", { class: "grow" }, titleEl),
      p.id ? h("button", { class: "quiet danger", onclick: async () => { if (confirm("Delete this purchase? Files already made stay in the output folder.")) { await api("/api/purchases/" + p.id, { method: "DELETE" }); dirty = false; go("purchases"); } } }, "Delete") : null,
      h("button", { class: "primary", "data-t": "save", onclick: (e) => busy(e.currentTarget, () => save()) }, "Save")),
    h("div", { class: "editor" },
      h("div", {},
        h("section", { class: "sheet" },
          h("header", {}, h("h2", {}, "What is being bought")),
          h("div", { class: "grid g4" },
            field("Subject", inp(p, "title", { placeholder: "Electronics Components (IMU BNO055)", "data-t": "title" }, () => { touch(); titleEl.textContent = p.title || "New purchase"; }), "after “Permission to purchase for”", "span2"),
            field("Letter date", inp(p, "date", { type: "date" }, touch)),
            field("Grant", sel(p, "project_id", projOptions(), () => { touch(); renderDocs(); debounceRules(); }))),
          h("div", { class: "grid g4", style: "margin-top:12px" },
            field("How it will be paid", sel(p, "route", Object.entries(ROUTES), () => { touch(); debounceRules(); }), null, "span2")),
          h("div", { style: "margin-top:14px" }, chk(p, "post_facto", "Already bought without permission: ask for post-facto approval", () => { touch(); drawPostFacto(); renderDocs(); })),
          postFactoBox,
          h("details", { class: "more", style: "margin-top:14px" }, h("summary", {}, "Letter wording and order terms"),
            h("div", { class: "grid g3" },
              field("Payment condition in letter", inp(p, "payment_condition", { placeholder: "From the selected quotation" }, touch)),
              field("Delivery time in letter", inp(p, "delivery_time", { placeholder: "From the selected quotation" }, touch)),
              field("Signature route", sel(p, "authority_override", [["", "Decide from the amount"], ["hod", "To HoD only"], ["director", "Through HoD and AR to Director"], ["vp", "Up to the Vice President"]], () => { touch(); debounceRules(); })),
              field("Purchase order date", inp(p, "po_date", { type: "date" }, touch), "blank = letter date"),
              field("Payment term on order", inp(p, "po_payment", { placeholder: "From the selected quotation" }, touch)),
              field("Delivery on order", inp(p, "po_delivery", { placeholder: "From the selected quotation" }, touch))),
            h("div", { class: "row", style: "margin-top:12px" },
              chk(p, "list_items_in_subject", "List each item under the subject", touch),
              chk(p, "quote_waiver", "Single source / waiver: allow fewer quotations", () => { touch(); debounceRules(); })),
            h("div", { style: "margin-top:10px" }, extraBox))),
        h("section", { class: "sheet" },
          h("header", {}, h("h2", { class: "grow" }, "Quotations"),
            h("button", { "data-t": "add-quote", onclick: () => { p.quotes.push(blankQuote()); touch(); renderQuotes(); debounceRules(); } }, "Add quotation"),
            h("p", {}, "Pick the vendor you are buying from. It is printed first in the comparative statement.")),
          quotesBox)),
      h("aside", { class: "rail" }, slipBox,
        h("section", { class: "slip" }, h("div", { class: "slip-sec" }, h("h3", {}, "Documents"), docsBox)),
        h("section", { class: "slip" }, h("div", { class: "slip-sec" }, h("h3", {}, "Progress"), h("p", { class: "muted small-t", style: "margin:-4px 0 8px" }, "Tick a step when it happens. Steps unlock in order."), stepsBox)))));
  renderQuotes(); renderDocs();
  await refreshRules();
};

// ---------------------------------------------------------------- bills (advances + reimbursements)
function billsEditor(rec, onchange) {
  rec.bills = rec.bills || [];
  const box = h("div");
  const draw = () => {
    const totalEl = h("b", { "data-t": "bills-total" }, "Total " + inr(rec.bills.reduce((s, b) => s + num(b.amount), 0)));
    const rows = rec.bills.map((b, i) => h("tr", {},
      h("td", {}, inp(b, "biller", { list: "dl-vendors", placeholder: "Seller" }, () => { dirty = true; })),
      h("td", {}, inp(b, "bill_no", {}, () => { dirty = true; })),
      h("td", {}, inp(b, "bill_date", { type: "date" }, () => { dirty = true; })),
      h("td", {}, inp(b, "gst", { type: "number", step: "any" }, () => { dirty = true; })),
      h("td", {}, inp(b, "items", { placeholder: "Short list of items" }, () => { dirty = true; })),
      h("td", {}, inp(b, "amount", { type: "number", step: "any", "data-t": "bill-amount" }, () => { dirty = true; totalEl.textContent = "Total " + inr(rec.bills.reduce((s, x) => s + num(x.amount), 0)); onchange && onchange(); })),
      h("td", {}, h("button", { class: "icon-btn", "aria-label": "Remove bill", onclick: () => { rec.bills.splice(i, 1); draw(); onchange && onchange(); } }, "×"))));
    const scanInput = h("input", { type: "file", accept: ".pdf,image/*", multiple: true, style: "display:none" });
    const scanBtn = h("button", { class: "sm", onclick: () => scanInput.click() }, "Read bills from PDF / photo");
    scanInput.addEventListener("change", () => busy(scanBtn, async () => {
      for (const f of scanInput.files) {
        const fd = new FormData(); fd.append("file", f); fd.append("kind", "bill");
        const res = await api("/api/scan", { method: "POST", body: fd });
        const d = res.data;
        rec.bills.push({ biller: d.biller || "", bill_no: d.bill_no || "", bill_date: d.bill_date || "", gst: d.gst || 0, items: d.items || "", amount: d.amount || 0, file: res.file });
        if (res.warning) toast("The AI reader failed for " + f.name + ": " + res.warning, true);
      }
      dirty = true; toast("Bills read. Check them before making the voucher."); draw(); onchange && onchange();
    }));
    box.replaceChildren(
      h("div", { class: "table-wrap" }, h("table", { style: "min-width:760px" }, h("tr", {}, h("th", {}, "Seller"), h("th", { style: "width:120px" }, "Bill no."), h("th", { style: "width:150px" }, "Bill date"), h("th", { style: "width:100px" }, "GST (₹)"), h("th", {}, "Items"), h("th", { style: "width:120px" }, "Amount (₹)"), h("th", { style: "width:40px" })), rows)),
      rec.bills.length ? null : h("p", { class: "muted" }, "No bills yet. Add them by hand or read them from the PDFs."),
      h("div", { class: "row", style: "margin-top:10px" },
        h("button", { class: "sm", "data-t": "add-bill", onclick: () => { rec.bills.push({ biller: "", bill_no: "", bill_date: "", gst: "", items: "", amount: "" }); draw(); } }, "Add bill"), scanBtn, scanInput,
        h("span", { class: "grow" }), totalEl));
  };
  draw();
  return box;
}

function stepsEditor(table, getRec, setRec, defs, ensureSaved) {
  const box = h("div", { class: "steps" });
  const draw = () => {
    const done = getRec().stages || {};
    box.replaceChildren(...defs.map((s) => {
      const locked = (s.needs || []).some((n) => !done[n]);
      const c = h("input", { type: "checkbox", checked: !!done[s.key], "data-t": "stage-" + s.key });
      c.addEventListener("change", async () => {
        try { await ensureSaved(); setRec(await api(`/api/${table}/${getRec().id}/stage`, { method: "POST", body: { key: s.key, done: c.checked } })); draw(); }
        catch (e) { c.checked = !c.checked; toast(e.message, true); }
      });
      return h("label", { class: "step" + (done[s.key] ? " done" : "") + (locked && !done[s.key] ? " locked" : "") }, c, s.label, h("span", { class: "when" }, done[s.key] ? dmy(done[s.key]) : ""));
    }));
  };
  draw();
  return { el: box, draw };
}
function sideRail(...sections) { return h("aside", { class: "rail" }, sections.map(([title, body]) => h("section", { class: "slip" }, h("div", { class: "slip-sec" }, h("h3", {}, title), body)))); }

// ---------------------------------------------------------------- advances
function advanceTable(list) {
  return h("div", { class: "table-wrap" }, h("table", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "Advance"), h("th", { class: "num" }, "Amount"), h("th", { class: "num hide-sm" }, "Spent"), h("th", {}, "Next step")),
    list.map((a) => h("tr", { class: "link", onclick: () => go("advance-edit", a.id) }, h("td", {}, dmy(a.date)), h("td", {}, a.title || "Untitled advance"),
      h("td", { class: "num" }, inr(a.amount)), h("td", { class: "num hide-sm" }, inr((a.bills || []).reduce((s, b) => s + num(b.amount), 0))), h("td", {}, nextStep(a, S.advDefs))))));
}
views.advances = async () => {
  const list = await api("/api/advances");
  main.append(head("Advances", "Request an advance, spend it, then settle it with the Advance Adjustment Voucher.",
    h("button", { class: "primary", onclick: () => go("advance-edit", "new") }, "New advance request")));
  main.append(h("section", { class: "sheet" }, list.length ? advanceTable(list) : emptyState("No advances yet.", "New advance request", () => go("advance-edit", "new"))));
};
views["advance-edit"] = async (id) => {
  let a = id && id !== "new" ? await api("/api/advances/" + id) : { project_id: String(S.projects[0]?.id || ""), date: today(), title: "", amount: "", items: [{ description: "", qty: 1, rate: "" }], bills: [], stages: {} };
  a.items = a.items && a.items.length ? a.items : [{ description: "", qty: 1, rate: "" }];
  const docsBox = h("div"), sumBox = h("div");
  const save = async (silent) => { const fresh = !a.id; a = await api("/api/advances", { method: "POST", body: a }); dirty = false; if (!silent) toast("Saved"); if (fresh) history.replaceState(null, "", "#advance-edit/" + a.id); docsBox.replaceChildren(docsList(a)); return a; };
  const gen = (kind, btn) => busy(btn, async () => { await save(true); a = await api(`/api/generate/${kind}/${a.id}`, { method: "POST", body: {} }); toast(DOC_NAMES[kind] + " ready"); docsBox.replaceChildren(docsList(a)); st.draw(); drawSum(); });
  const amountIn = inp(a, "amount", { type: "number", step: "any", placeholder: "Sum of the items", "data-t": "adv-amount" }, () => { dirty = true; drawSum(); });
  const cols = "minmax(0,1fr) 80px 130px 130px 32px";
  const planned = h("div", { class: "items" });
  const drawPlanned = () => {
    planned.replaceChildren(h("div", { class: "it-row headr", style: `grid-template-columns:${cols}` }, h("span", {}, "Item to buy from this advance"), h("span", {}, "Qty"), h("span", {}, "Unit rate (₹)"), h("span", {}, "Total"), h("span", {})),
      ...a.items.map((it, i) => {
        const tot = h("div", { class: "amt" }, inr(num(it.qty || 1) * num(it.rate)));
        const upd = () => { tot.textContent = inr(num(it.qty || 1) * num(it.rate)); recalc(); };
        return h("div", { class: "it-row adv-row" },
          autoGrow(area(it, "description", { rows: 1, placeholder: "Item", "data-t": "adv-item" }, () => { dirty = true; })),
          h("div", {}, h("span", { class: "lbl" }, "Qty"), inp(it, "qty", { type: "number", step: "any" }, upd)),
          h("div", {}, h("span", { class: "lbl" }, "Rate"), inp(it, "rate", { type: "number", step: "any", "data-t": "adv-rate" }, upd)), tot,
          h("button", { class: "icon-btn", "aria-label": "Remove item", onclick: () => { a.items.splice(i, 1); if (!a.items.length) a.items.push({ description: "", qty: 1, rate: "" }); drawPlanned(); recalc(); } }, "×"));
      }));
  };
  function recalc() { dirty = true; a.amount = r2(a.items.reduce((s, it) => s + num(it.qty || 1) * num(it.rate), 0)); amountIn.value = a.amount; drawSum(); }
  function drawSum() {
    const spent = (a.bills || []).reduce((s, b) => s + num(b.amount), 0);
    const diff = num(a.amount) - spent;
    sumBox.replaceChildren(h("dl", { class: "facts" },
      h("dt", {}, "Advance"), h("dd", {}, inr(a.amount)), h("dt", {}, "Spent (bills)"), h("dd", {}, inr(spent)),
      h("dt", {}, diff >= 0 ? "Unspent, to return" : "Spent beyond advance"), h("dd", { style: diff < 0 ? "color:var(--red)" : "" }, inr(Math.abs(diff)))));
  }
  const st = stepsEditor("advances", () => a, (r) => (a = r), S.advDefs, async () => { if (!a.id) await save(true); });
  drawPlanned(); drawSum(); docsBox.append(docsList(a));
  const bAdv = h("button", { class: "primary", "data-t": "gen-adv", onclick: () => gen("advance_voucher", bAdv) }, "Make Advance Voucher");
  const bAdj = h("button", { class: "primary", "data-t": "gen-adj", onclick: () => gen("advance_adjustment", bAdj) }, "Make Advance Adjustment Voucher");
  main.append(vendorDatalist(), itemDatalist(),
    h("a", { class: "back", onclick: () => go("advances") }, "‹ All advances"),
    h("div", { class: "head" }, h("div", { class: "grow" }, h("h1", {}, a.title || "Advance request")),
      a.id ? h("button", { class: "quiet danger", onclick: async () => { if (confirm("Delete this advance record?")) { await api("/api/advances/" + a.id, { method: "DELETE" }); dirty = false; go("advances"); } } }, "Delete") : null,
      h("button", { class: "primary", "data-t": "save", onclick: (e) => busy(e.currentTarget, () => save()) }, "Save")),
    h("div", { class: "editor" },
      h("div", {},
        h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Advance request"), h("p", {}, "Fills the Voucher for Advance.")),
          h("div", { class: "grid g4" }, field("Name for your list", inp(a, "title", { placeholder: "Mechanical parts, October", "data-t": "adv-title" }, () => { dirty = true; }), null, "span2"),
            field("Voucher date", inp(a, "date", { type: "date" }, () => { dirty = true; })), field("Grant", sel(a, "project_id", projOptions(), () => { dirty = true; }))),
          h("div", { class: "grid g2", style: "margin-top:12px" }, field("Advance amount (₹)", amountIn), field("Purpose", inp(a, "purpose", { placeholder: "Grant default" }, () => { dirty = true; }))),
          h("h3", { style: "margin-top:16px" }, "Items to be bought"), planned,
          h("div", { class: "row", style: "margin-top:10px" }, h("button", { class: "sm", onclick: () => { a.items.push({ description: "", qty: 1, rate: "" }); drawPlanned(); } }, "Add item"), h("span", { class: "grow" }), bAdv)),
        h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Bills paid from the advance"), h("p", {}, "Fills the Advance Adjustment Voucher. Tick ‘Advance amount received’ first.")),
          billsEditor(a, drawSum),
          h("div", { class: "grid g3", style: "margin-top:14px" }, field("Adjustment voucher date", inp(a, "adjust_date", { type: "date" }, () => { dirty = true; })),
            field("Remaining bill adjustment (₹)", inp(a, "remaining_adjustment", { type: "number", step: "any" }, () => { dirty = true; })),
            field("Particular", inp(a, "particular", { placeholder: "Grant default" }, () => { dirty = true; }))),
          h("div", { class: "row", style: "margin-top:12px" }, h("span", { class: "grow" }), bAdj))),
      sideRail(["Money", sumBox], ["Documents", docsBox], ["Progress", st.el])));
};

// ---------------------------------------------------------------- reimbursements
function reimTable(list) {
  return h("div", { class: "table-wrap" }, h("table", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "Reimbursement"), h("th", { class: "num" }, "Amount"), h("th", {}, "Next step")),
    list.map((c) => h("tr", { class: "link", onclick: () => go("reimbursement-edit", c.id) }, h("td", {}, dmy(c.date)), h("td", {}, c.title || "Untitled"),
      h("td", { class: "num" }, inr((c.bills || []).reduce((s, b) => s + num(b.amount), 0))), h("td", {}, nextStep(c, S.cvDefs))))));
}
views.reimbursements = async () => {
  const list = await api("/api/reimbursements");
  main.append(head("Reimbursements", "Bought with your own money after permission? Claim it back with a Cash Voucher and the original bill.",
    h("button", { class: "primary", onclick: () => go("reimbursement-edit", "new") }, "New reimbursement")));
  main.append(h("section", { class: "sheet" }, list.length ? reimTable(list) : emptyState("Nothing to claim yet.", "New reimbursement", () => go("reimbursement-edit", "new"))));
};
views["reimbursement-edit"] = async (id) => {
  const purchases = await api("/api/purchases");
  let c = id && id !== "new" ? await api("/api/reimbursements/" + id) : { project_id: String(S.projects[0]?.id || ""), date: today(), title: "", bills: [], stages: {} };
  const docsBox = h("div");
  const save = async (silent) => { const fresh = !c.id; c = await api("/api/reimbursements", { method: "POST", body: c }); dirty = false; if (!silent) toast("Saved"); if (fresh) history.replaceState(null, "", "#reimbursement-edit/" + c.id); docsBox.replaceChildren(docsList(c)); };
  const st = stepsEditor("reimbursements", () => c, (r) => (c = r), S.cvDefs, async () => { if (!c.id) await save(true); });
  const bGen = h("button", { class: "primary", "data-t": "gen-cv", onclick: () => busy(bGen, async () => { await save(true); c = await api(`/api/generate/cash_voucher/${c.id}`, { method: "POST", body: {} }); toast("Cash Voucher ready"); docsBox.replaceChildren(docsList(c)); st.draw(); }) }, "Make Cash Voucher");
  const bWaiver = h("button", { "data-t": "gen-waiver", onclick: () => busy(bWaiver, async () => { await save(true); c = await api(`/api/generate/waiver/${c.id}`, { method: "POST", body: {} }); toast("Waiver form ready"); docsBox.replaceChildren(docsList(c)); }) }, "Make Waiver form");
  docsBox.append(docsList(c));
  const permOpts = [["", "Choose the approved permission"]].concat(purchases.map((p) => [String(p.id), `${dmy(p.date)}  ${p.title || "Untitled"}  ${inr(p.amount)}${(p.stages || {}).permission_approved ? "" : "  (not approved yet)"}`]));
  main.append(vendorDatalist(),
    h("a", { class: "back", onclick: () => go("reimbursements") }, "‹ All reimbursements"),
    h("div", { class: "head" }, h("div", { class: "grow" }, h("h1", {}, c.title || "Reimbursement")),
      c.id ? h("button", { class: "quiet danger", onclick: async () => { if (confirm("Delete this record?")) { await api("/api/reimbursements/" + c.id, { method: "DELETE" }); dirty = false; go("reimbursements"); } } }, "Delete") : null,
      h("button", { class: "primary", "data-t": "save", onclick: (e) => busy(e.currentTarget, () => save()) }, "Save")),
    h("div", { class: "editor" },
      h("div", {},
        h("div", { class: "note info", style: "margin:0 0 16px" }, "Paying from your own pocket does not replace the permission. Link the approved Purchase Permission, or give the post-facto approval reference."),
        h("section", { class: "sheet" },
          h("div", { class: "grid g4" }, field("Name for your list", inp(c, "title", { "data-t": "cv-title" }, () => { dirty = true; }), null, "span2"),
            field("Voucher date", inp(c, "date", { type: "date" }, () => { dirty = true; })), field("Grant", sel(c, "project_id", projOptions(), () => { dirty = true; }))),
          h("div", { class: "grid g2", style: "margin-top:12px" }, field("Approved permission", sel(c, "purchase_id", permOpts, () => { dirty = true; })),
            field("Or post-facto approval reference", inp(c, "post_facto_ref", { placeholder: "VP approval dated 15-01-2026", "data-t": "post-facto" }, () => { dirty = true; }))),
          h("div", { class: "grid g2", style: "margin-top:12px" }, field("Pay to", inp(c, "payee", { placeholder: "Grant default" }, () => { dirty = true; })),
            field("Being payment of", inp(c, "purpose", { placeholder: "Reimbursement of material purchased…" }, () => { dirty = true; })))),
        h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Original bills")), billsEditor(c),
          h("div", { class: "row", style: "margin-top:12px" }, h("p", { class: "muted small-t grow", style: "margin:0" }, "There was no official Cash Voucher format in your files, so this uses the Nirma voucher sheet titled Cash Voucher."), bGen)),
        h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Waiver of purchase procedure"), h("p", {}, "Only if the purchase was made without permission, quotations or PO. Lists the bills above and goes to the Vice President.")),
          field("Reason the procedure was not followed", autoGrow(area(c, "waiver_reason", { rows: 4, placeholder: "Leave blank for the standard wording.", "data-t": "waiver-reason" }, () => { dirty = true; }))),
          h("div", { class: "row", style: "margin-top:12px" }, h("span", { class: "grow" }), bWaiver))),
      sideRail(["Documents", docsBox], ["Progress", st.el])));
};

// ---------------------------------------------------------------- vendors
views.vendors = async () => {
  const purchases = await api("/api/purchases");
  const count = {};
  purchases.forEach((p) => (p.quotes || []).forEach((q) => { const n = (q.vendor || {}).name; if (n) count[n] = (count[n] || 0) + 1; }));
  const tbody = h("tbody");
  const search = h("input", { placeholder: "Search by name, GSTIN or city", type: "search", "data-t": "vendor-search" });
  const draw = () => {
    const s = search.value.toLowerCase();
    const rows = S.vendors.filter((v) => !s || JSON.stringify(v).toLowerCase().includes(s));
    tbody.replaceChildren(...(rows.length ? rows.map((v) =>
      h("tr", { class: "link", onclick: () => editVendor(v) }, h("td", {}, h("b", {}, v.name), v.contact_person ? h("div", { class: "muted small-t" }, v.contact_person) : null),
        h("td", { class: "hide-sm", style: "white-space:pre-line;max-width:380px" }, v.address || h("span", { class: "muted" }, "No address yet")), h("td", {}, v.gst || "—"),
        h("td", { class: "hide-sm" }, [v.phone, v.email].filter(Boolean).join(", ") || "—"), h("td", { class: "num" }, count[v.name] || ""))) : [h("tr", {}, h("td", { colspan: 5, class: "muted" }, "No vendor matches that search."))]));
  };
  search.addEventListener("input", draw);
  main.append(head("Vendors", "Saved from every quotation you enter or read. Type a name in a quotation to fill address and GSTIN.",
    h("button", { class: "primary", "data-t": "add-vendor", onclick: () => editVendor({}) }, "Add vendor")),
    h("section", { class: "sheet" }, search, h("div", { class: "table-wrap", style: "margin-top:12px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", { class: "hide-sm" }, "Address"), h("th", {}, "GSTIN"), h("th", { class: "hide-sm" }, "Contact"), h("th", { class: "num" }, "Quotations"))), tbody))));
  draw();
};
function editVendor(v) {
  v = { ...v };
  const close = modal([h("h2", {}, v.id ? v.name : "New vendor"),
    h("div", { class: "grid g2" }, field("Name", inp(v, "name", { "data-t": "vendor-name" })), field("GSTIN", inp(v, "gst"))),
    h("div", { style: "margin-top:12px" }, field("Address", area(v, "address", { rows: 3 }), "as printed on the purchase order")),
    h("div", { class: "grid g3", style: "margin-top:12px" }, field("Contact person", inp(v, "contact_person")), field("Phone", inp(v, "phone")), field("Email", inp(v, "email"))),
    h("div", { class: "grid g2", style: "margin-top:12px" }, field("Usual payment condition", inp(v, "payment")), field("Usual delivery time", inp(v, "delivery"))),
    h("div", { class: "row", style: "margin-top:18px" }, v.id ? h("button", { class: "quiet danger", onclick: async () => { if (confirm("Delete this vendor?")) { await api("/api/vendors/" + v.id, { method: "DELETE" }); close(); route(); } } }, "Delete") : null,
      h("span", { class: "grow" }), h("button", { onclick: () => close() }, "Cancel"),
      h("button", { class: "primary", "data-t": "vendor-save", onclick: async () => { if (!String(v.name || "").trim()) return toast("Give the vendor a name", true); await api("/api/vendors", { method: "POST", body: v }); close(); toast("Vendor saved"); route(); } }, "Save vendor"))]);
}

// ---------------------------------------------------------------- items
views.items = async () => {
  const tbody = h("tbody");
  const search = h("input", { placeholder: "Search items or vendors", type: "search" });
  const draw = () => {
    const s = search.value.toLowerCase();
    tbody.replaceChildren(...S.items.filter((i) => !s || (i.description + " " + i.vendor).toLowerCase().includes(s)).map((i) =>
      h("tr", {}, h("td", {}, i.description, (i.history || []).length > 1 ? h("div", { class: "muted small-t" }, "Earlier: " + i.history.slice(0, -1).map((x) => `${x.vendor || "?"} ${inr(x.rate)}`).join(", ")) : null),
        h("td", { class: "hide-sm" }, i.vendor || "—"), h("td", { class: "num" }, inr(i.rate)), h("td", { class: "num hide-sm" }, (i.gst ?? 18) + "%"), h("td", { class: "hide-sm" }, dmy(i.last_date)),
        h("td", {}, h("button", { class: "icon-btn", "aria-label": "Forget item", onclick: async () => { if (confirm("Remove this item from memory?")) { await api("/api/items/" + i.id, { method: "DELETE" }); route(); } } }, "×")))));
  };
  search.addEventListener("input", draw);
  main.append(head("Items", "Last rate paid for each item, before GST. Typing an item in a quotation suggests it and fills the rate."),
    h("section", { class: "sheet" }, search, h("div", { class: "table-wrap", style: "margin-top:12px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", { class: "hide-sm" }, "Last vendor"), h("th", { class: "num" }, "Last rate"), h("th", { class: "num hide-sm" }, "GST"), h("th", { class: "hide-sm" }, "Date"), h("th", {}))), tbody))));
  draw();
};

// ---------------------------------------------------------------- settings
const PROJECT_FIELDS = [
  ["Letters", [["name", "Name in the portal"], ["project", "Project name in letters"], ["grant", "Grant in brackets"], ["letter_style", "Letter style: nu or incubation"], ["ref_prefix", "Reference line ({fy} becomes 2026-27)"], ["institute", "Institute"]]],
  ["Signatures", [["mentor_name", "Signed by"], ["mentor_title", "Designation"], ["hod", "HoD line"], ["ar", "Asst. Registrar line"], ["director", "Director line"], ["exec_registrar", "Exec. Registrar line"], ["vp", "Vice President line"], ["through", "Through (incubation)"], ["to", "To (incubation)"]]],
  ["Budget", [["budget_code", "Budget code"], ["budget_head_po", "Budget head on audit page"], ["department", "Department on audit page"], ["dop_authority", "Authority on audit page"], ["provision", "Budget provision (₹)"], ["opening_utilized", "Spent before the portal (₹)"], ["opening_as_of", "…as of (YYYY-MM-DD)"]]],
  ["Vouchers", [["payee", "Pay to"], ["contact", "Contact no."], ["payee_dept", "Dept."], ["advance_purpose", "Advance purpose"], ["advance_approver", "Advance approving authority"], ["adjust_particular", "Adjustment particular"], ["adjust_ref_prefix", "Adjustment reference ({project}, {fy})"], ["voucher_mentor", "Adjustment: prepared by"], ["voucher_hod", "Adjustment: HoD"], ["voucher_approver", "Adjustment: approving authority"]]],
];
views.settings = async () => {
  const s = { ...S.settings, slabs: S.settings.slabs.map((x) => ({ ...x })) };
  const ledger = await api("/api/ledger");
  const led = { project_id: String(S.projects[0]?.id || ""), date: today(), amount: "", note: "" };
  const slabRows = s.slabs.map((sl) => h("tr", {}, h("td", {}, inp(sl, "upto", { type: "number", placeholder: "and above" })), h("td", {}, inp(sl, "label")),
    h("td", {}, sel(sl, "authority", Object.entries(S.settings.authority_names))), h("td", {}, inp(sl, "quotes", { type: "number", min: 1 })),
    ...["po", "tally_po", "audit", "outward"].map((k) => h("td", { style: "text-align:center" }, chk(sl, k, "")))));
  main.append(head("Settings", "Reading quotations, purchase rules, grant details and manual budget entries."),
    h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Reading quotations and bills"), h("p", {}, "Google Vision reads scanned PDFs and photos. Grok or Groq turns the text into vendor, items and totals. Keys stay in this computer's portal database.")),
      h("div", { class: "grid g2" },
        field("Google Vision API key", inp(s, "vision_key", { type: "password", autocomplete: "off", placeholder: s.vision_key_set ? "Saved. Type to replace" : "Not set" })),
        field("AI service", sel(s, "llm_provider", [["groq", "Groq (key starts with gsk_)"], ["xai", "xAI Grok (key starts with xai-)"]])),
        field("AI key", inp(s, "llm_key", { type: "password", autocomplete: "off", placeholder: s.llm_key_set ? "Saved. Type to replace" : "Not set" })),
        field("Model", inp(s, "llm_model", { placeholder: "Default: openai/gpt-oss-120b (Groq), grok-4 (xAI)" })))),
    h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Backup"), h("p", {}, "Everything lives on this computer. Download a backup now and then (database, keys, all generated documents) and keep it on Drive or a pen drive. To restore, unzip it into the portal folder.")),
      h("a", { href: "/api/backup", "data-t": "backup" }, h("button", { class: "primary" }, "Download backup"))),
    h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Where files are saved")),
      s.output_fixed ? h("p", { style: "margin:0" }, "Running in Docker: files go to the portal's data/output folder on this computer.") : field("Folder", inp(s, "output_dir"))),
    h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Purchase value rules"), h("p", {}, "Which signatures, how many quotations and which papers each amount needs.")),
      h("div", { class: "table-wrap" }, h("table", { style: "min-width:820px" }, h("tr", {}, ["Up to (₹)", "Label", "Approved by", "Quotations", "PO", "Tally PO", "Audit", "Outward"].map((x) => h("th", {}, x))), slabRows))),
    h("div", { class: "row", style: "margin-bottom:28px" }, h("span", { class: "grow" }), h("button", { class: "primary", "data-t": "save-settings", onclick: (e) => busy(e.currentTarget, async () => { S.settings = await api("/api/settings", { method: "POST", body: s }); toast("Settings saved"); route(); }) }, "Save settings")),
    h("h2", { style: "margin:0 0 10px" }, "Grants"),
    S.projects.map((p) => {
      const d = { ...p };
      return h("details", { class: "sheet more" }, h("summary", {}, p.name),
        PROJECT_FIELDS.map(([group, fields]) => h("div", { style: "margin-bottom:16px" }, h("h3", {}, group),
          h("div", { class: "grid g3" }, fields.map(([k, l]) => {
            const t = h("textarea", { rows: 1 }, d[k] ?? "");
            t.addEventListener("input", () => (d[k] = ["provision", "opening_utilized"].includes(k) ? num(t.value) : t.value));
            return field(l, autoGrow(t));
          })))),
        d.letter_style === "incubation" ? field("Introduction paragraphs (blank line between them)", (() => { const t = h("textarea", { rows: 6 }, (d.intro_paragraphs || []).join("\n\n")); t.addEventListener("input", () => (d.intro_paragraphs = t.value.split(/\n\s*\n/))); return t; })()) : null,
        h("div", { class: "row", style: "margin-top:10px" }, h("span", { class: "grow" }), h("button", { class: "primary", onclick: async () => { await api("/api/projects", { method: "POST", body: d }); toast("Grant saved"); route(); } }, "Save grant")));
    }),
    h("button", { style: "margin-bottom:24px", onclick: async () => { await api("/api/projects", { method: "POST", body: { name: "New grant", project: "", letter_style: "nu", provision: 0 } }); route(); } }, "Add grant"),
    h("section", { class: "sheet" }, h("header", {}, h("h2", {}, "Manual budget entries"), h("p", {}, "Spending that did not go through the portal, like Nirma overhead or older purchases. Counted as spent.")),
      h("div", { class: "table-wrap" }, h("table", { "data-t": "ledger" }, ledger.map((l) => h("tr", {}, h("td", {}, dmy(l.date) || "—"), h("td", { class: "hide-sm" }, projById(l.project_id).name || ""), h("td", {}, l.note), h("td", { class: "num" }, inr(l.amount)),
        h("td", {}, h("button", { class: "icon-btn", "aria-label": "Delete entry", onclick: async () => { if (confirm("Delete this entry?")) { await api("/api/ledger/" + l.id, { method: "DELETE" }); route(); } } }, "×")))))),
      h("div", { class: "grid g4", style: "margin-top:12px" }, field("Grant", sel(led, "project_id", projOptions())), field("Date", inp(led, "date", { type: "date" })), field("What", inp(led, "note", { "data-t": "ledger-note" })), field("Amount (₹)", inp(led, "amount", { type: "number", step: "any", "data-t": "ledger-amount" }))),
      h("div", { class: "row", style: "margin-top:12px" }, h("span", { class: "grow" }), h("button", { "data-t": "ledger-add", onclick: async () => { if (!led.note || !num(led.amount)) return toast("Enter what it was and the amount", true); await api("/api/ledger", { method: "POST", body: { ...led, name: led.note } }); toast("Entry added"); route(); } }, "Add entry"))));
};

route();
