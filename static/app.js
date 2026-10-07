// Purchase Portal front-end (no build step).
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const S = { settings: null, projects: [], vendors: [], items: [] };

// ---------------------------------------------------------------- helpers
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else if (k === "html") el.innerHTML = v;
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
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
function toast(msg, bad = false) {
  const d = h("div", { class: bad ? "bad" : "" }, msg);
  $("#toast").append(d);
  setTimeout(() => d.remove(), bad ? 7000 : 3500);
}
const inr = (x) => {
  const n = Number(x || 0);
  return "₹ " + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
const today = () => new Date().toISOString().slice(0, 10);
const dmy = (d) => (d ? d.split("-").reverse().join("-") : "");
const num = (v) => (v === "" || v === null || v === undefined ? 0 : Number(v));
function field(label, input, cls = "") { return h("label", { class: cls }, label, input); }
function inp(obj, key, attrs = {}, onchange) {
  const el = h("input", { value: obj[key] ?? "", ...attrs });
  el.addEventListener("input", () => { obj[key] = attrs.type === "number" ? (el.value === "" ? "" : Number(el.value)) : el.value; onchange && onchange(); });
  return el;
}
function sel(obj, key, options, onchange) {
  const el = h("select", {}, options.map(([v, t]) => h("option", { value: v }, t)));
  el.value = obj[key] ?? options[0]?.[0] ?? "";
  if (obj[key] === undefined && options.length) obj[key] = el.value;
  el.addEventListener("change", () => { obj[key] = el.value; onchange && onchange(); });
  return el;
}
function chk(obj, key, label, onchange) {
  const el = h("input", { type: "checkbox", checked: !!obj[key] });
  el.addEventListener("change", () => { obj[key] = el.checked; onchange && onchange(); });
  return h("label", { class: "chk" }, el, label);
}
async function busy(btn, fn) {
  const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="spin"></span> ' + old;
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; btn.innerHTML = old; }
}
function lineTotals(q) {
  let sub = 0, gst = 0;
  for (const it of q.items || []) {
    const l = num(it.qty) * num(it.rate); sub += l;
    gst += l * (it.gst === "" || it.gst === undefined ? 18 : num(it.gst)) / 100;
  }
  const disc = num(q.discount);
  if (sub && disc) gst = gst * (sub - disc) / sub;
  if (q.gst_override !== "" && q.gst_override !== undefined && q.gst_override !== null) gst = num(q.gst_override);
  const other = num(q.other);
  return { sub, disc, gst, other, grand: sub - disc + gst + other };
}
function fileLinks(doc) {
  return doc.files.map((f) => {
    const ext = f.split(".").pop().toUpperCase();
    return h("a", { onclick: () => window.open("/api/file?path=" + encodeURIComponent(f)) }, ext);
  }).concat([h("a", { onclick: () => api("/api/open-folder", { method: "POST", body: { path: doc.files[0] } }) }, "Folder")]);
}
const DOC_NAMES = { permission: "Purchase Permission", po: "Purchase Order", rfq: "Quotation requests",
  advance_voucher: "Advance Voucher", advance_adjustment: "Advance Adjustment Voucher", cash_voucher: "Cash Voucher" };
function docsList(rec) {
  if (!rec.docs || !rec.docs.length) return h("p", { class: "muted" }, "Nothing generated yet.");
  return h("table", {}, rec.docs.map((d) => h("tr", {}, h("td", {}, DOC_NAMES[d.kind] || d.kind),
    h("td", { class: "muted" }, d.made.replace("T", " ").slice(0, 16)), h("td", { class: "docs" }, fileLinks(d)))));
}
function modal(content) {
  const back = h("div", { class: "modal-back", onclick: (e) => e.target === back && back.remove() }, h("div", { class: "modal" }, content));
  document.body.append(back);
  return () => back.remove();
}

// ---------------------------------------------------------------- data
async function loadBase() {
  [S.settings, S.projects, S.vendors, S.items, ADV_DEFS, CV_DEFS] = await Promise.all([
    api("/api/settings"), api("/api/projects"), api("/api/vendors"), api("/api/items"),
    api("/api/stages/advances"), api("/api/stages/reimbursements")]);
}
function vendorDatalist() {
  return h("datalist", { id: "dl-vendors" }, S.vendors.map((v) => h("option", { value: v.name })));
}
function itemDatalist() {
  return h("datalist", { id: "dl-items" }, S.items.map((i) => h("option", { value: i.description }, i.vendor ? `${i.vendor} · ₹${i.rate}` : "")));
}
const projOptions = () => S.projects.map((p) => [String(p.id), p.name]);

// ---------------------------------------------------------------- router
const views = {};
async function go(view, arg) {
  location.hash = arg ? `${view}/${arg}` : view;
}
async function route() {
  const [view, arg] = (location.hash.slice(1) || "dashboard").split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === view.replace(/-edit$/, "")));
  main.innerHTML = "";
  try { await loadBase(); await (views[view] || views.dashboard)(arg); }
  catch (e) { main.append(h("div", { class: "note" }, e.message)); }
}
document.querySelectorAll("nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.view)));
window.addEventListener("hashchange", route);

// ---------------------------------------------------------------- dashboard
views.dashboard = async () => {
  main.append(h("h1", {}, "Dashboard"), h("p", { class: "sub" }, "Budget position and purchases that are waiting on a step."));
  const [purchases, advances, reims] = await Promise.all([api("/api/purchases"), api("/api/advances"), api("/api/reimbursements")]);
  const cards = h("div", { class: "grid g2" });
  for (const p of S.projects.filter((p) => num(p.provision) > 0)) {
    const b = await api("/api/budget/" + p.id);
    const pct = Math.min(100, (b.utilized / (b.provision || 1)) * 100);
    cards.append(h("div", { class: "panel" },
      h("h2", {}, p.name, " ", h("span", { class: "pill" }, p.budget_code || "")),
      h("div", { class: "grid g3" },
        h("div", {}, h("small", { class: "muted" }, "Provision"), h("div", { class: "stat" }, inr(b.provision))),
        h("div", {}, h("small", { class: "muted" }, "Utilized"), h("div", { class: "stat" }, inr(b.utilized))),
        h("div", {}, h("small", { class: "muted" }, "Available"), h("div", { class: "stat", style: b.available < 0 ? "color:var(--bad)" : "" }, inr(b.available)))),
      h("div", { class: "bar", style: "margin:10px 0" }, h("i", { style: `width:${pct}%` })),
      h("details", {}, h("summary", {}, "How utilized is made up"),
        h("table", {}, h("tr", {}, h("td", {}, `Opening (as of ${dmy(b.opening_as_of)})`), h("td", { class: "num" }, inr(b.opening))),
          b.entries.map((e) => h("tr", {}, h("td", {}, `${dmy(e.date)} · ${e.what || ""}`), h("td", { class: "num" }, inr(e.amount))))))));
  }
  main.append(cards);
  const row = h("div", { class: "row", style: "margin-bottom:16px" },
    h("button", { class: "primary", onclick: () => go("purchase-edit", "new") }, "+ New purchase"),
    h("button", { onclick: () => go("advance-edit", "new") }, "+ Advance request"),
    h("button", { onclick: () => go("reimbursement-edit", "new") }, "+ Reimbursement (cash voucher)"));
  main.append(row);
  const open = purchases.filter((p) => !(p.stages || {}).settled);
  main.append(h("div", { class: "panel" }, h("h2", {}, "Open purchases"),
    open.length ? purchaseTable(open) : h("p", { class: "muted" }, "No open purchases.")));
  const openAdv = advances.filter((a) => !(a.stages || {}).settled);
  if (openAdv.length) main.append(h("div", { class: "panel" }, h("h2", {}, "Advances not yet settled"), advanceTable(openAdv)));
  const openR = reims.filter((r) => !(r.stages || {}).reimbursed);
  if (openR.length) main.append(h("div", { class: "panel" }, h("h2", {}, "Reimbursements pending"), reimTable(openR)));
};

function nextStage(rec, defs) {
  const done = rec.stages || {};
  const s = defs.find((x) => !done[x.key]);
  return s ? s.label : "Done";
}
function purchaseTable(list) {
  const defs = S.settings.stages;
  return h("table", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "Purchase"), h("th", {}, "Vendor"), h("th", {}, "Route"), h("th", { class: "num" }, "Amount"), h("th", {}, "Approval"), h("th", {}, "Next step")),
    list.map((p) => {
      const q = (p.quotes || [])[p.selected || 0] || {};
      const applicable = defs.filter((d) => !d.if || (p.req || {})[d.if]);
      return h("tr", { class: "click", onclick: () => go("purchase-edit", p.id) },
        h("td", {}, dmy(p.date)), h("td", {}, p.title || "(untitled)"), h("td", {}, (q.vendor || {}).name || ""),
        h("td", {}, ROUTES[p.route] || ""), h("td", { class: "num" }, inr(p.amount)),
        h("td", {}, h("span", { class: "pill" }, (p.req || {}).authority_name || "")),
        h("td", {}, h("span", { class: "pill warn" }, nextStage(p, applicable))));
    }));
}

// ---------------------------------------------------------------- purchases list
const ROUTES = { po: "Purchase Order to vendor", card: "Direct payment (Nirma card)", advance: "From an advance", personal: "Personal funds → reimbursement" };
views.purchases = async () => {
  const list = await api("/api/purchases");
  main.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, "Purchases"), h("p", { class: "sub" }, "Every purchase permission, its quotations, PO and status.")),
    h("button", { class: "primary", onclick: () => go("purchase-edit", "new") }, "+ New purchase")));
  main.append(h("div", { class: "panel" }, list.length ? purchaseTable(list) : h("p", { class: "muted" }, "No purchases yet.")));
};

// ---------------------------------------------------------------- purchase editor
function blankQuote() { return { vendor: { name: "" }, quote_no: "", quote_date: "", payment: "", delivery: "", items: [{ description: "", qty: 1, rate: "", gst: 18 }], discount: "", other: "", gst_override: "" }; }

views["purchase-edit"] = async (id) => {
  let p = id && id !== "new" ? await api("/api/purchases/" + id) : {
    project_id: String(S.projects[0]?.id || ""), date: today(), title: "", route: "po", quotes: [blankQuote()], selected: 0,
    list_items_in_subject: true, stages: {}, docs: [],
  };
  p.quotes = p.quotes && p.quotes.length ? p.quotes : [blankQuote()];
  let req = null;
  const bannerBox = h("div");
  const quotesBox = h("div", { class: "quotes" });
  const docsBox = h("div");
  const stagesBox = h("div");

  async function refreshRules() {
    req = await api("/api/rules", { method: "POST", body: p });
    const proj = S.projects.find((x) => String(x.id) === String(p.project_id)) || {};
    bannerBox.innerHTML = "";
    const qOk = req.quotes_ok;
    bannerBox.append(h("div", { class: "banner" },
      h("div", {}, h("small", {}, "Amount (selected quote)"), h("b", {}, inr(req.totals.grand))),
      h("div", {}, h("small", {}, "Slab"), h("b", {}, req.label)),
      h("div", {}, h("small", {}, "Approval authority"), h("b", {}, proj.letter_style === "incubation" ? "Incubation cell" : req.authority_name)),
      h("div", {}, h("small", {}, "Quotations"), h("b", {}, `${req.quotes_have} / ${req.quotes}  `, h("span", { class: "pill " + (qOk ? "good" : "bad") }, qOk ? "OK" : "Need more"))),
      h("div", {}, h("small", {}, "PO · Audit"), h("b", {}, `${req.po ? (req.tally_po ? "Tally + normal PO" : "Yes") : "No"} · ${req.audit ? "Yes + Outward" : "No"}`))));
    bannerBox.append(h("p", { class: "muted", style: "margin:-8px 0 14px" }, "Needed: " + req.documents.join(" · ")));
    // lowest bidder hint
    if (p.quotes.length > 1) {
      const grands = req.all_totals.map((t) => t.grand);
      const lo = grands.indexOf(Math.min(...grands.filter((g) => g > 0)));
      if (lo >= 0 && lo !== Number(p.selected || 0))
        bannerBox.append(h("div", { class: "note", style: "margin-bottom:14px" }, `The selected vendor is not the lowest quotation (L1 is "${(p.quotes[lo].vendor || {}).name}"). Purchasing from a non-L1 vendor needs a justification / waiver.`));
    }
    renderStages();
  }

  function renderQuotes() {
    quotesBox.innerHTML = "";
    p.quotes.forEach((q, qi) => quotesBox.append(quoteCard(q, qi)));
  }

  function quoteCard(q, qi) {
    q.vendor = q.vendor || { name: "" };
    const totBox = h("div", { class: "tot" });
    const updTot = () => {
      const t = lineTotals(q);
      totBox.innerHTML = "";
      totBox.append(h("div", {}, "Total", h("b", {}, inr(t.sub - t.disc))), h("div", {}, "GST", h("b", {}, inr(t.gst))),
        h("div", {}, "Other", h("b", {}, inr(t.other))), h("div", {}, "Grand total", h("b", {}, inr(t.grand))));
    };
    const changed = () => { updTot(); debounceRules(); };
    const vName = h("input", { value: q.vendor.name || "", list: "dl-vendors", placeholder: "Vendor name" });
    const vAddr = h("textarea", { rows: 2, placeholder: "Address (for the PO)" }, q.vendor.address || "");
    const vGst = h("input", { value: q.vendor.gst || "", placeholder: "GSTIN" });
    vName.addEventListener("input", () => { q.vendor.name = vName.value; });
    vName.addEventListener("change", () => {
      const v = S.vendors.find((x) => x.name.toLowerCase() === vName.value.toLowerCase());
      if (v) {
        q.vendor = { ...v }; vAddr.value = v.address || ""; vGst.value = v.gst || "";
        if (!q.payment && v.payment) q.payment = v.payment;
        if (!q.delivery && v.delivery) q.delivery = v.delivery;
        renderQuotes();
      }
    });
    vAddr.addEventListener("input", () => (q.vendor.address = vAddr.value));
    vGst.addEventListener("input", () => (q.vendor.gst = vGst.value));

    const itemsTbl = h("table", { class: "items" });
    const drawItems = () => {
      itemsTbl.innerHTML = "";
      itemsTbl.append(h("tr", {}, h("th", {}, "Item description"), h("th", { style: "width:60px" }, "Qty"), h("th", { style: "width:100px" }, "Rate (excl. GST)"), h("th", { style: "width:60px" }, "GST %"), h("th", { class: "num", style: "width:100px" }, "Amount"), h("th", {})));
      q.items.forEach((it, ii) => {
        const amt = h("td", { class: "num" }, inr(num(it.qty) * num(it.rate)));
        const upd = () => { amt.textContent = inr(num(it.qty) * num(it.rate)); changed(); };
        const d = inp(it, "description", { list: "dl-items" }, upd);
        d.addEventListener("change", () => {
          const known = S.items.find((x) => x.description.toLowerCase() === d.value.toLowerCase());
          if (known && !it.rate) { it.rate = known.rate; it.gst = known.gst ?? 18; it.hsn = known.hsn; drawItems(); changed(); }
        });
        itemsTbl.append(h("tr", {}, h("td", {}, d), h("td", {}, inp(it, "qty", { type: "number", step: "any" }, upd)),
          h("td", {}, inp(it, "rate", { type: "number", step: "any" }, upd)), h("td", {}, inp(it, "gst", { type: "number", step: "any" }, upd)), amt,
          h("td", {}, h("button", { class: "ghost small", title: "Remove", onclick: () => { q.items.splice(ii, 1); drawItems(); changed(); } }, "✕"))));
      });
    };
    drawItems();
    updTot();

    const scanInput = h("input", { type: "file", accept: ".pdf,image/*", style: "display:none" });
    const scanBtn = h("button", { class: "small", onclick: () => scanInput.click() }, "Scan quotation");
    scanInput.addEventListener("change", () => busy(scanBtn, async () => {
      const fd = new FormData(); fd.append("file", scanInput.files[0]); fd.append("kind", "quote");
      const res = await api("/api/scan", { method: "POST", body: fd });
      const nq = res.quote;
      Object.assign(q, { ...nq, items: nq.items.length ? nq.items : q.items });
      if (res.warning) toast("AI read failed, used basic reader: " + res.warning, true);
      toast(`Read with ${res.ocr} + ${res.parser}${res.vendor_match ? " · matched saved vendor " + res.vendor_match.name : " · new vendor"}. Please check the values.`);
      renderQuotes(); debounceRules();
    }));

    const isSel = Number(p.selected || 0) === qi;
    return h("div", { class: "quote" + (isSel ? " sel" : "") },
      h("div", { class: "row", style: "margin-bottom:8px" },
        h("b", {}, `Quotation ${qi + 1}`), isSel ? h("span", { class: "pill good" }, "Selected vendor") :
          h("button", { class: "small", onclick: () => { p.selected = qi; renderQuotes(); debounceRules(); } }, "Select this vendor"),
        h("span", { class: "grow" }), scanBtn, scanInput,
        qi > 0 ? h("button", { class: "small", title: "Copy item list from Quotation 1 (then change rates)", onclick: () => { q.items = p.quotes[0].items.map((i) => ({ ...i })); renderQuotes(); debounceRules(); } }, "Copy items from Q1") : null,
        p.quotes.length > 1 ? h("button", { class: "ghost small danger", onclick: () => { p.quotes.splice(qi, 1); if (p.selected >= p.quotes.length) p.selected = 0; renderQuotes(); debounceRules(); } }, "Remove") : null),
      h("div", { class: "grid g2" }, field("Vendor", vName), field("GSTIN", vGst)),
      field("Address", vAddr),
      h("div", { class: "grid g4", style: "margin-top:8px" }, field("Quotation no.", inp(q, "quote_no")), field("Quotation date", inp(q, "quote_date", { type: "date" })),
        field("Payment condition", inp(q, "payment", { placeholder: "e.g. After 15 days of purchase" })), field("Delivery time", inp(q, "delivery", { placeholder: "e.g. 7-10 working days" }))),
      h("div", { style: "margin-top:8px" }, itemsTbl,
        h("button", { class: "small", style: "margin-top:6px", onclick: () => { q.items.push({ description: "", qty: 1, rate: "", gst: 18 }); drawItems(); } }, "+ Item")),
      h("div", { class: "grid g3", style: "margin-top:8px" }, field("Discount (₹)", inp(q, "discount", { type: "number", step: "any" }, changed)),
        field("Other charges (₹, incl. shipping)", inp(q, "other", { type: "number", step: "any" }, changed)),
        field("GST amount override (₹)", inp(q, "gst_override", { type: "number", step: "any", placeholder: "auto" }, changed))),
      q.file ? h("p", { class: "muted", style: "margin:6px 0 0" }, "Source file: ", h("a", { href: "/api/file?path=" + encodeURIComponent(q.file), target: "_blank" }, q.file.split(/[\\/]/).pop())) : null,
      totBox);
  }

  let tmr;
  function debounceRules() { clearTimeout(tmr); tmr = setTimeout(refreshRules, 300); }

  async function save(silent) {
    const saved = await api("/api/purchases", { method: "POST", body: p });
    const fresh = !p.id;
    p = saved; p.quotes = p.quotes.length ? p.quotes : [blankQuote()];
    if (!silent) toast("Saved");
    if (fresh) { history.replaceState(null, "", "#purchase-edit/" + p.id); }
    renderDocs(); renderStages();
    return p;
  }

  async function gen(kind, btn) {
    await busy(btn, async () => {
      await save(true);
      p = await api(`/api/generate/${kind}/${p.id}`, { method: "POST", body: {} });
      toast(DOC_NAMES[kind] + " generated");
      renderDocs(); renderStages();
    });
  }

  function renderDocs() {
    docsBox.innerHTML = "";
    const proj = S.projects.find((x) => String(x.id) === String(p.project_id)) || {};
    const bPerm = h("button", { class: "primary", onclick: () => gen("permission", bPerm) }, "Generate Purchase Permission");
    const bPo = h("button", { onclick: () => gen("po", bPo) }, "Generate Purchase Order");
    const bRfq = h("button", { onclick: () => gen("rfq", bRfq) }, "Quotation request letters");
    docsBox.append(h("div", { class: "row", style: "margin-bottom:10px" }, bPerm, proj.letter_style !== "incubation" ? [bPo, bRfq] : null), docsList(p));
  }

  function renderStages() {
    stagesBox.innerHTML = "";
    if (!req) return;
    const done = p.stages || {};
    stagesBox.append(h("div", { class: "stages" }, req.stages.map((s) => {
      const box = h("input", { type: "checkbox", checked: !!done[s.key] });
      box.addEventListener("change", async () => {
        if (!p.id) await save(true);
        try { p = await api(`/api/purchases/${p.id}/stage`, { method: "POST", body: { key: s.key, done: box.checked } }); renderStages(); }
        catch (e) { box.checked = !box.checked; toast(e.message, true); }
      });
      return h("label", { class: "chk stage" + (done[s.key] ? " done" : "") }, box, s.label, h("span", { class: "when" }, done[s.key] ? dmy(done[s.key]) : ""));
    })));
  }

  const projSel = sel(p, "project_id", projOptions(), () => { renderDocs(); debounceRules(); });
  const nirmaCardPara = "The payment may please be made directly to the vendor using the NU WiFi Card (Nirma Card) at the time of purchase. No purchase order or reimbursement process is required, as the payment will be executed directly through the Nirma Card to the vendor.";
  main.append(vendorDatalist(), itemDatalist(),
    h("div", { class: "row" }, h("button", { class: "ghost", onclick: () => go("purchases") }, "← Purchases"), h("span", { class: "grow" }),
      p.id ? h("button", { class: "ghost danger", onclick: async () => { if (confirm("Delete this purchase record? (Generated files stay on disk.)")) { await api("/api/purchases/" + p.id, { method: "DELETE" }); go("purchases"); } } }, "Delete") : null,
      h("button", { class: "primary", onclick: (e) => busy(e.target, () => save()) }, "Save")),
    h("h1", {}, p.id ? p.title || "Purchase" : "New purchase"),
    h("p", { class: "sub" }, "Fill the quotations – the approval route, PO and audit need are worked out from the amount."),
    h("div", { class: "panel" }, h("div", { class: "grid g4" },
      field("Project / grant", projSel), field("Permission date", inp(p, "date", { type: "date" })),
      field("Subject – permission to purchase for…", inp(p, "title", { placeholder: "e.g. Electronics Components (IMU BNO055)" }), "grow"),
      field("How will it be paid?", sel(p, "route", Object.entries(ROUTES), debounceRules))),
      h("details", { style: "margin-top:12px" }, h("summary", {}, "Letter options"),
        h("div", { class: "grid g3" },
          field("Payment condition in permission (blank = from quote)", inp(p, "payment_condition")),
          field("Delivery time in permission (blank = from quote)", inp(p, "delivery_time")),
          field("Approval route override", sel(p, "authority_override", [["", "Automatic (by amount)"], ["hod", "To HOD only"], ["director", "Through HOD/AR → Director"], ["vp", "… → Exec. Registrar → VP"]], debounceRules)),
          field("PO date (blank = permission date)", inp(p, "po_date", { type: "date" })),
          field("PO payment term (blank = from quote)", inp(p, "po_payment", { placeholder: "PO – After 15 days of Delivery" })),
          field("PO delivery (blank = from quote)", inp(p, "po_delivery"))),
        h("div", { class: "row", style: "margin-top:8px" },
          chk(p, "list_items_in_subject", "List each item under the subject (multi-item)"),
          chk(p, "quote_waiver", "Single source / waiver – allow fewer quotations"),
          h("button", { class: "small", onclick: () => { p.extra_paragraphs = [nirmaCardPara]; toast("Nirma-card paragraph added"); } }, "Add Nirma-card payment paragraph"),
          p.extra_paragraphs && p.extra_paragraphs.length ? h("button", { class: "small ghost", onclick: () => { p.extra_paragraphs = []; toast("Removed"); } }, "Remove extra paragraph") : null))),
    bannerBox,
    h("div", { class: "panel" }, h("div", { class: "row", style: "margin-bottom:10px" }, h("h2", { class: "grow", style: "margin:0" }, "Quotations"),
      h("button", { onclick: () => { p.quotes.push(blankQuote()); renderQuotes(); debounceRules(); } }, "+ Add quotation")),
      h("p", { class: "muted", style: "margin-top:0" }, "Quotation 1 is normally the vendor you buy from. Scan a PDF/photo to fill a card automatically. The selected vendor goes first in the comparative statement."),
      quotesBox),
    h("div", { class: "grid g2" },
      h("div", { class: "panel" }, h("h2", {}, "Documents"), docsBox),
      h("div", { class: "panel" }, h("h2", {}, "Workflow"), h("p", { class: "muted", style: "margin-top:0" }, "Tick each step when it happens. A step stays locked until the ones before it are done."), stagesBox)));
  renderQuotes(); renderDocs(); await refreshRules();
};

// ---------------------------------------------------------------- bills table (advances + reimbursements)
function billsEditor(rec, onchange) {
  rec.bills = rec.bills || [];
  const box = h("div");
  const draw = () => {
    box.innerHTML = "";
    const tbl = h("table", { class: "items" }, h("tr", {}, h("th", {}, "Biller"), h("th", { style: "width:120px" }, "Bill no."), h("th", { style: "width:140px" }, "Bill date"), h("th", { style: "width:90px" }, "GST (₹)"), h("th", {}, "Items"), h("th", { style: "width:110px" }, "Amount (₹)"), h("th", {})));
    rec.bills.forEach((b, i) => tbl.append(h("tr", {},
      h("td", {}, inp(b, "biller", { list: "dl-vendors" })), h("td", {}, inp(b, "bill_no")), h("td", {}, inp(b, "bill_date", { type: "date" })),
      h("td", {}, inp(b, "gst", { type: "number", step: "any" })), h("td", {}, inp(b, "items")), h("td", {}, inp(b, "amount", { type: "number", step: "any" }, () => { onchange && onchange(); })),
      h("td", {}, h("button", { class: "ghost small", onclick: () => { rec.bills.splice(i, 1); draw(); onchange && onchange(); } }, "✕")))));
    const scanInput = h("input", { type: "file", accept: ".pdf,image/*", multiple: true, style: "display:none" });
    const scanBtn = h("button", { class: "small", onclick: () => scanInput.click() }, "Scan bill(s)");
    scanInput.addEventListener("change", () => busy(scanBtn, async () => {
      for (const f of scanInput.files) {
        const fd = new FormData(); fd.append("file", f); fd.append("kind", "bill");
        const res = await api("/api/scan", { method: "POST", body: fd });
        const d = res.data;
        rec.bills.push({ biller: d.biller || "", bill_no: d.bill_no || "", bill_date: d.bill_date || "", gst: d.gst || 0, items: d.items || "", amount: d.amount || 0, file: res.file });
        if (res.warning) toast("AI read failed, used basic reader: " + res.warning, true);
      }
      toast("Bills read – please check them"); draw(); onchange && onchange();
    }));
    box.append(tbl, h("div", { class: "row", style: "margin-top:6px" },
      h("button", { class: "small", onclick: () => { rec.bills.push({ biller: "", bill_no: "", bill_date: "", gst: "", items: "", amount: "" }); draw(); } }, "+ Bill"), scanBtn, scanInput,
      h("span", { class: "grow" }), h("b", {}, "Total: " + inr(rec.bills.reduce((s, b) => s + num(b.amount), 0)))));
  };
  draw();
  return box;
}

function stagesEditor(table, getRec, setRec, defs, ensureSaved) {
  const box = h("div");
  const draw = () => {
    box.innerHTML = "";
    const rec = getRec(); const done = rec.stages || {};
    box.append(h("div", { class: "stages" }, defs.map((s) => {
      const c = h("input", { type: "checkbox", checked: !!done[s.key] });
      c.addEventListener("change", async () => {
        await ensureSaved();
        try { setRec(await api(`/api/${table}/${getRec().id}/stage`, { method: "POST", body: { key: s.key, done: c.checked } })); draw(); }
        catch (e) { c.checked = !c.checked; toast(e.message, true); }
      });
      return h("label", { class: "chk stage" + (done[s.key] ? " done" : "") }, c, s.label, h("span", { class: "when" }, done[s.key] ? dmy(done[s.key]) : ""));
    })));
  };
  draw();
  return { el: box, draw };
}

// ---------------------------------------------------------------- advances
function advanceTable(list) {
  return h("table", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "Advance"), h("th", { class: "num" }, "Amount"), h("th", { class: "num" }, "Spent (bills)"), h("th", {}, "Next step")),
    list.map((a) => {
      const spent = (a.bills || []).reduce((s, b) => s + num(b.amount), 0);
      return h("tr", { class: "click", onclick: () => go("advance-edit", a.id) }, h("td", {}, dmy(a.date)), h("td", {}, a.title || ""),
        h("td", { class: "num" }, inr(a.amount)), h("td", { class: "num" }, inr(spent)), h("td", {}, h("span", { class: "pill warn" }, nextStage(a, ADV_DEFS))));
    }));
}
let ADV_DEFS = [], CV_DEFS = [];
views.advances = async () => {
  ADV_DEFS = await api("/api/stages/advances");
  const list = await api("/api/advances");
  main.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, "Advances"), h("p", { class: "sub" }, "Advance request → advance received → purchases → Advance Adjustment Voucher → Accounts.")),
    h("button", { class: "primary", onclick: () => go("advance-edit", "new") }, "+ Advance request")));
  main.append(h("div", { class: "panel" }, list.length ? advanceTable(list) : h("p", { class: "muted" }, "No advances yet.")));
};
views["advance-edit"] = async (id) => {
  ADV_DEFS = await api("/api/stages/advances");
  let a = id && id !== "new" ? await api("/api/advances/" + id) : { project_id: String(S.projects[0]?.id || ""), date: today(), title: "", amount: "", items: [{ description: "", qty: 1, rate: "" }], bills: [], stages: {} };
  const docsBox = h("div"), sumBox = h("div");
  const save = async (silent) => { const fresh = !a.id; a = await api("/api/advances", { method: "POST", body: a }); if (!silent) toast("Saved"); if (fresh) history.replaceState(null, "", "#advance-edit/" + a.id); docsBox.replaceChildren(docsList(a)); return a; };
  const gen = (kind, btn) => busy(btn, async () => { await save(true); a = await api(`/api/generate/${kind}/${a.id}`, { method: "POST", body: {} }); toast(DOC_NAMES[kind] + " generated"); docsBox.replaceChildren(docsList(a)); st.draw(); drawSum(); });
  const planned = h("table", { class: "items" });
  const amountIn = inp(a, "amount", { type: "number", step: "any", placeholder: "auto from items" });
  const drawPlanned = () => {
    planned.innerHTML = "";
    planned.append(h("tr", {}, h("th", {}, "Item to be procured"), h("th", { style: "width:70px" }, "Qty"), h("th", { style: "width:110px" }, "Unit rate"), h("th", { class: "num", style: "width:110px" }, "Total"), h("th", {})));
    a.items.forEach((it, i) => planned.append(h("tr", {}, h("td", {}, inp(it, "description", { list: "dl-items" })), h("td", {}, inp(it, "qty", { type: "number", step: "any" }, recalc)),
      h("td", {}, inp(it, "rate", { type: "number", step: "any" }, recalc)), h("td", { class: "num" }, inr(num(it.qty || 1) * num(it.rate))),
      h("td", {}, h("button", { class: "ghost small", onclick: () => { a.items.splice(i, 1); drawPlanned(); recalc(); } }, "✕")))));
  };
  function recalc() { a.amount = a.items.reduce((s, it) => s + num(it.qty || 1) * num(it.rate), 0); amountIn.value = a.amount; drawSum(); }
  function drawSum() {
    const spent = (a.bills || []).reduce((s, b) => s + num(b.amount), 0);
    const diff = num(a.amount) - spent;
    sumBox.replaceChildren(h("div", { class: "banner", style: "grid-template-columns:repeat(3,1fr)" },
      h("div", {}, h("small", {}, "Advance"), h("b", {}, inr(a.amount))), h("div", {}, h("small", {}, "Spent (bills)"), h("b", {}, inr(spent))),
      h("div", {}, h("small", {}, diff >= 0 ? "To return / unspent" : "Spent beyond advance"), h("b", { style: diff < 0 ? "color:var(--bad)" : "" }, inr(Math.abs(diff))))));
  }
  const st = stagesEditor("advances", () => a, (r) => (a = r), ADV_DEFS, async () => { if (!a.id) await save(true); });
  drawPlanned(); drawSum(); docsBox.append(docsList(a));
  const bAdv = h("button", { class: "primary", onclick: () => gen("advance_voucher", bAdv) }, "Generate Advance Voucher");
  const bAdj = h("button", { class: "primary", onclick: () => gen("advance_adjustment", bAdj) }, "Generate Advance Adjustment Voucher");
  main.append(vendorDatalist(), itemDatalist(),
    h("div", { class: "row" }, h("button", { class: "ghost", onclick: () => go("advances") }, "← Advances"), h("span", { class: "grow" }),
      a.id ? h("button", { class: "ghost danger", onclick: async () => { if (confirm("Delete this advance record?")) { await api("/api/advances/" + a.id, { method: "DELETE" }); go("advances"); } } }, "Delete") : null,
      h("button", { class: "primary", onclick: (e) => busy(e.target, () => save()) }, "Save")),
    h("h1", {}, a.title || "Advance request"),
    h("div", { class: "panel" }, h("h2", {}, "1 · Advance request"),
      h("div", { class: "grid g4" }, field("Project / grant", sel(a, "project_id", projOptions())), field("Voucher date", inp(a, "date", { type: "date" })),
        field("Name (for your reference)", inp(a, "title", { placeholder: "e.g. Mechanical parts – Oct" })), field("Advance amount (₹)", amountIn)),
      field("Purpose of advance (blank = project default)", inp(a, "purpose")),
      h("h3", { style: "margin-top:12px" }, "List of items to be procured from this advance"), planned,
      h("button", { class: "small", style: "margin-top:6px", onclick: () => { a.items.push({ description: "", qty: 1, rate: "" }); drawPlanned(); } }, "+ Item"),
      h("div", { style: "margin-top:12px" }, bAdv)),
    h("div", { class: "panel" }, h("h2", {}, "2 · Bills spent from the advance → Adjustment"),
      billsEditor(a, drawSum), sumBox,
      h("div", { class: "grid g3" }, field("Adjustment voucher date", inp(a, "adjust_date", { type: "date" })),
        field("Remaining bill adjustment (₹)", inp(a, "remaining_adjustment", { type: "number", step: "any" })),
        field("Particular (blank = project default)", inp(a, "particular"))),
      h("div", { style: "margin-top:12px" }, bAdj)),
    h("div", { class: "grid g2" }, h("div", { class: "panel" }, h("h2", {}, "Documents"), docsBox), h("div", { class: "panel" }, h("h2", {}, "Workflow"), st.el)));
};

// ---------------------------------------------------------------- reimbursements
function reimTable(list) {
  return h("table", {}, h("tr", {}, h("th", {}, "Date"), h("th", {}, "Reimbursement"), h("th", { class: "num" }, "Amount"), h("th", {}, "Next step")),
    list.map((c) => h("tr", { class: "click", onclick: () => go("reimbursement-edit", c.id) }, h("td", {}, dmy(c.date)), h("td", {}, c.title || ""),
      h("td", { class: "num" }, inr((c.bills || []).reduce((s, b) => s + num(b.amount), 0))), h("td", {}, h("span", { class: "pill warn" }, nextStage(c, CV_DEFS))))));
}
views.reimbursements = async () => {
  CV_DEFS = await api("/api/stages/reimbursements");
  const list = await api("/api/reimbursements");
  main.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, "Reimbursements"), h("p", { class: "sub" }, "Bought with your own money after permission → Cash Voucher with the original bill.")),
    h("button", { class: "primary", onclick: () => go("reimbursement-edit", "new") }, "+ Reimbursement")));
  main.append(h("div", { class: "panel" }, list.length ? reimTable(list) : h("p", { class: "muted" }, "Nothing yet.")));
};
views["reimbursement-edit"] = async (id) => {
  CV_DEFS = await api("/api/stages/reimbursements");
  const purchases = await api("/api/purchases");
  let c = id && id !== "new" ? await api("/api/reimbursements/" + id) : { project_id: String(S.projects[0]?.id || ""), date: today(), title: "", bills: [], stages: {} };
  const docsBox = h("div");
  const save = async (silent) => { const fresh = !c.id; c = await api("/api/reimbursements", { method: "POST", body: c }); if (!silent) toast("Saved"); if (fresh) history.replaceState(null, "", "#reimbursement-edit/" + c.id); docsBox.replaceChildren(docsList(c)); };
  const st = stagesEditor("reimbursements", () => c, (r) => (c = r), CV_DEFS, async () => { if (!c.id) await save(true); });
  const bGen = h("button", { class: "primary", onclick: () => busy(bGen, async () => { await save(true); c = await api(`/api/generate/cash_voucher/${c.id}`, { method: "POST", body: {} }); toast("Cash Voucher generated"); docsBox.replaceChildren(docsList(c)); st.draw(); }) }, "Generate Cash Voucher");
  docsBox.append(docsList(c));
  const permOpts = [["", "— choose the approved permission —"]].concat(purchases.map((p) => [String(p.id), `${dmy(p.date)} · ${p.title} · ${inr(p.amount)}${(p.stages || {}).permission_approved ? "" : "  (not approved yet)"}`]));
  main.append(vendorDatalist(),
    h("div", { class: "row" }, h("button", { class: "ghost", onclick: () => go("reimbursements") }, "← Reimbursements"), h("span", { class: "grow" }),
      c.id ? h("button", { class: "ghost danger", onclick: async () => { if (confirm("Delete this record?")) { await api("/api/reimbursements/" + c.id, { method: "DELETE" }); go("reimbursements"); } } }, "Delete") : null,
      h("button", { class: "primary", onclick: (e) => busy(e.target, () => save()) }, "Save")),
    h("h1", {}, c.title || "Reimbursement"),
    h("div", { class: "note info", style: "margin-bottom:14px" }, "Rule: paying from your own pocket does not replace prior permission. Link the approved Purchase Permission, or enter the post-facto approval reference."),
    h("div", { class: "panel" }, h("div", { class: "grid g4" }, field("Project / grant", sel(c, "project_id", projOptions())), field("Voucher date", inp(c, "date", { type: "date" })),
      field("Name (for your reference)", inp(c, "title")), field("Approved permission", sel(c, "purchase_id", permOpts))),
      h("div", { class: "grid g3", style: "margin-top:10px" }, field("…or post-facto approval reference", inp(c, "post_facto_ref")),
        field("Pay to (blank = project default)", inp(c, "payee")), field("Being payment of (blank = default)", inp(c, "purpose"))),
      h("h3", { style: "margin-top:14px" }, "Original bills"), billsEditor(c), h("div", { style: "margin-top:12px" }, bGen),
      h("p", { class: "muted" }, "No official Cash Voucher format was in your folders, so this uses the Nirma 'Voucher for Advance' sheet re-titled as CASH VOUCHER. Replace doc_templates\\advance_voucher.xlsx logic if Accounts gives you their format.")),
    h("div", { class: "grid g2" }, h("div", { class: "panel" }, h("h2", {}, "Documents"), docsBox), h("div", { class: "panel" }, h("h2", {}, "Workflow"), st.el)));
};

// ---------------------------------------------------------------- vendors
views.vendors = async () => {
  const purchases = await api("/api/purchases");
  const count = {};
  purchases.forEach((p) => (p.quotes || []).forEach((q) => { const n = (q.vendor || {}).name; if (n) count[n] = (count[n] || 0) + 1; }));
  const tbody = h("tbody");
  const search = h("input", { placeholder: "Search vendors…" });
  const draw = () => {
    const s = search.value.toLowerCase();
    tbody.replaceChildren(...S.vendors.filter((v) => !s || JSON.stringify(v).toLowerCase().includes(s)).map((v) =>
      h("tr", { class: "click", onclick: () => editVendor(v) }, h("td", {}, h("b", {}, v.name), v.contact_person ? h("div", { class: "muted" }, v.contact_person) : null),
        h("td", { style: "white-space:pre-line" }, v.address || h("span", { class: "muted" }, "—")), h("td", {}, v.gst || ""), h("td", {}, [v.phone, v.email].filter(Boolean).join(" · ")), h("td", { class: "num" }, count[v.name] || ""))));
  };
  search.addEventListener("input", draw);
  main.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, "Vendors"), h("p", { class: "sub" }, "Saved automatically from every quotation you enter or scan. Pick them by name in a quotation card.")),
    h("button", { class: "primary", onclick: () => editVendor({}) }, "+ Vendor")),
    h("div", { class: "panel" }, search, h("table", { style: "margin-top:10px" }, h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", {}, "Address"), h("th", {}, "GSTIN"), h("th", {}, "Contact"), h("th", { class: "num" }, "Quotes"))), tbody)));
  draw();
};
function editVendor(v) {
  v = { ...v };
  const close = modal([h("h2", {}, v.id ? "Edit vendor" : "New vendor"),
    h("div", { class: "grid g2" }, field("Name", inp(v, "name")), field("GSTIN", inp(v, "gst"))),
    field("Address (as on PO, multiple lines OK)", (() => { const t = h("textarea", { rows: 3 }, v.address || ""); t.addEventListener("input", () => (v.address = t.value)); return t; })()),
    h("div", { class: "grid g3" }, field("Contact person", inp(v, "contact_person")), field("Phone", inp(v, "phone")), field("Email", inp(v, "email"))),
    h("div", { class: "grid g2" }, field("Usual payment condition", inp(v, "payment")), field("Usual delivery time", inp(v, "delivery"))),
    h("div", { class: "row", style: "margin-top:14px" }, v.id ? h("button", { class: "ghost danger", onclick: async () => { if (confirm("Delete vendor?")) { await api("/api/vendors/" + v.id, { method: "DELETE" }); close(); route(); } } }, "Delete") : null,
      h("span", { class: "grow" }), h("button", { onclick: () => close() }, "Cancel"),
      h("button", { class: "primary", onclick: async () => { await api("/api/vendors", { method: "POST", body: v }); close(); toast("Vendor saved"); route(); } }, "Save"))]);
}

// ---------------------------------------------------------------- items
views.items = async () => {
  const tbody = h("tbody");
  const search = h("input", { placeholder: "Search items…" });
  const draw = () => {
    const s = search.value.toLowerCase();
    tbody.replaceChildren(...S.items.filter((i) => !s || (i.description + i.vendor).toLowerCase().includes(s)).map((i) =>
      h("tr", {}, h("td", {}, i.description), h("td", {}, i.vendor || ""), h("td", { class: "num" }, inr(i.rate)), h("td", { class: "num" }, (i.gst ?? 18) + "%"), h("td", {}, dmy(i.last_date)),
        h("td", { class: "muted" }, (i.history || []).slice(0, -1).map((x) => `${x.vendor || "?"} ₹${x.rate}`).join(" · ")),
        h("td", {}, h("button", { class: "ghost small danger", onclick: async () => { if (confirm("Remove from item memory?")) { await api("/api/items/" + i.id, { method: "DELETE" }); route(); } } }, "✕")))));
  };
  search.addEventListener("input", draw);
  main.append(h("h1", {}, "Items"), h("p", { class: "sub" }, "Last price paid for each item (pre-GST). Typing an item name in a quotation suggests these and fills the last rate."),
    h("div", { class: "panel" }, search, h("table", { style: "margin-top:10px" }, h("thead", {}, h("tr", {}, h("th", {}, "Item"), h("th", {}, "Last vendor"), h("th", { class: "num" }, "Last rate"), h("th", { class: "num" }, "GST"), h("th", {}, "Date"), h("th", {}, "Earlier"), h("th", {}))), tbody)));
  draw();
};

// ---------------------------------------------------------------- settings
const PROJECT_FIELDS = [
  ["name", "Name in portal"], ["project", "Project name in letters"], ["letter_style", "Letter style (nu / incubation)"], ["grant", "Grant (in brackets)"],
  ["ref_prefix", "Reference line ({fy} = 2026-27)"], ["budget_code", "Budget code"], ["budget_head_po", "Budget head on PO audit page"], ["department", "Department on audit page"],
  ["institute", "Institute"], ["dop_authority", "DOP authority on audit page"], ["provision", "Budget provision (₹)"], ["opening_utilized", "Utilized before portal (₹)"], ["opening_as_of", "…as of date (YYYY-MM-DD)"],
  ["mentor_name", "Signatory name"], ["mentor_title", "Signatory title"], ["hod", "HoD line"], ["ar", "Asst. Registrar line"], ["director", "Director line"], ["exec_registrar", "Exec. Registrar line"], ["vp", "VP line"],
  ["through", "Through (incubation)"], ["to", "To (incubation)"],
  ["payee", "Voucher: pay to"], ["contact", "Voucher: contact no."], ["payee_dept", "Voucher: dept."], ["advance_purpose", "Advance voucher purpose"], ["advance_approver", "Advance voucher approving authority"],
  ["adjust_particular", "Adjustment particular"], ["adjust_ref_prefix", "Adjustment ref ({project}, {fy}=2627)"], ["voucher_mentor", "Adjustment: prepared by (mentor)"], ["voucher_hod", "Adjustment: HOD"], ["voucher_approver", "Adjustment: approving authority"],
];
views.settings = async () => {
  const s = { ...S.settings };
  const slabsBox = h("div");
  const drawSlabs = () => {
    slabsBox.replaceChildren(h("table", { class: "items" }, h("tr", {}, ["Up to (₹, blank = above)", "Label", "Authority", "Quotes", "PO", "Tally PO", "Audit", "Outward"].map((x) => h("th", {}, x))),
      s.slabs.map((sl) => h("tr", {}, h("td", {}, inp(sl, "upto", { type: "number" })), h("td", {}, inp(sl, "label")),
        h("td", {}, sel(sl, "authority", Object.entries(S.settings.authority_names))), h("td", {}, inp(sl, "quotes", { type: "number" })),
        ["po", "tally_po", "audit", "outward"].map((k) => h("td", {}, chk(sl, k, "")))))));
  };
  drawSlabs();
  const ledger = await api("/api/ledger");
  const led = { project_id: String(S.projects[0]?.id || ""), date: today(), amount: "", note: "" };
  main.append(h("h1", {}, "Settings"),
    h("div", { class: "panel" }, h("h2", {}, "Quotation reading (AI)"),
      h("p", { class: "muted", style: "margin-top:0" }, "Google Vision reads scanned PDFs and photos. Grok (xAI) – or Groq – turns the text into vendor, items, GST and totals. Keys are stored only in data\\portal.db on this computer."),
      h("div", { class: "grid g2" },
        field(`Google Vision API key ${s.vision_key_set ? "(saved – leave blank to keep)" : ""}`, inp(s, "vision_key", { type: "password", autocomplete: "off" })),
        field("LLM provider", sel(s, "llm_provider", [["xai", "xAI Grok (api.x.ai)"], ["groq", "Groq (api.groq.com)"]])),
        field(`LLM API key ${s.llm_key_set ? "(saved – leave blank to keep)" : ""}`, inp(s, "llm_key", { type: "password", autocomplete: "off" })),
        field("Model (blank = default: grok-4 / openai/gpt-oss-120b)", inp(s, "llm_model")))),
    h("div", { class: "panel" }, h("h2", {}, "Output folder"), field("Generated documents are saved under", inp(s, "output_dir"))),
    h("div", { class: "panel" }, h("h2", {}, "Purchase value rules"),
      h("p", { class: "muted", style: "margin-top:0" }, "Default: up to ₹3,000 → HOD; ₹3,001–10,000 → 3-party comparison, stays with HOD, PO (Tally + normal), no audit; ₹10,001–50,000 → Director, PO + Internal Audit + Outward; above ₹50,000 → VP."),
      slabsBox),
    h("div", { class: "row" }, h("span", { class: "grow" }), h("button", { class: "primary", onclick: (e) => busy(e.target, async () => { S.settings = await api("/api/settings", { method: "POST", body: s }); toast("Settings saved"); route(); }) }, "Save settings")),
    h("h2", { style: "margin-top:24px" }, "Projects / grants"),
    S.projects.map((p) => {
      const d = { ...p };
      return h("details", { class: "panel" }, h("summary", {}, p.name),
        h("div", { class: "grid g3" }, PROJECT_FIELDS.map(([k, l]) => {
          if (k === "intro_paragraphs") return null;
          const t = h("textarea", { rows: 1 }, d[k] ?? ""); t.addEventListener("input", () => (d[k] = ["provision", "opening_utilized"].includes(k) ? num(t.value) : t.value));
          return field(l, t);
        })),
        d.letter_style === "incubation" ? field("Intro paragraphs (blank line between paragraphs)", (() => { const t = h("textarea", { rows: 6 }, (d.intro_paragraphs || []).join("\n\n")); t.addEventListener("input", () => (d.intro_paragraphs = t.value.split(/\n\s*\n/))); return t; })()) : null,
        h("div", { class: "row", style: "margin-top:10px" }, h("span", { class: "grow" }), h("button", { class: "primary", onclick: async () => { await api("/api/projects", { method: "POST", body: d }); toast("Project saved"); route(); } }, "Save project")));
    }),
    h("button", { onclick: async () => { await api("/api/projects", { method: "POST", body: { name: "New project", project: "", letter_style: "nu", provision: 0 } }); route(); } }, "+ Project"),
    h("div", { class: "panel", style: "margin-top:16px" }, h("h2", {}, "Manual budget entries"),
      h("p", { class: "muted", style: "margin-top:0" }, "For spending that did not go through the portal (counts in 'Utilized')."),
      h("table", {}, ledger.map((l) => h("tr", {}, h("td", {}, dmy(l.date)), h("td", {}, (S.projects.find((p) => String(p.id) === String(l.project_id)) || {}).name || ""), h("td", {}, l.note), h("td", { class: "num" }, inr(l.amount)),
        h("td", {}, h("button", { class: "ghost small danger", onclick: async () => { await api("/api/ledger/" + l.id, { method: "DELETE" }); route(); } }, "✕"))))),
      h("div", { class: "grid g4", style: "margin-top:8px" }, field("Project", sel(led, "project_id", projOptions())), field("Date", inp(led, "date", { type: "date" })), field("Note", inp(led, "note")), field("Amount (₹)", inp(led, "amount", { type: "number", step: "any" }))),
      h("button", { style: "margin-top:8px", onclick: async () => { await api("/api/ledger", { method: "POST", body: { ...led, name: led.note } }); route(); } }, "Add entry")));
};

route();
