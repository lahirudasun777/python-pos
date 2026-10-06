// POS screen logic: product grid, cart, payment, checkout
(() => {
  const $ = (s) => document.querySelector(s);
  const fmt = (n) => CUR + " " + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const byId = Object.fromEntries(PRODUCTS.map((p) => [p.id, p]));
  let cart = {};       // id -> qty
  let cat = "";
  let method = "cash";

  // ---------- product grid
  function renderProducts() {
    const q = $("#search").value.trim().toLowerCase();
    const list = PRODUCTS.filter((p) =>
      (!cat || String(p.category_id) === cat) &&
      (!q || p.name.toLowerCase().includes(q) || (p.barcode || "").toLowerCase().includes(q)));
    $("#prods").innerHTML = list.length ? list.map((p) => {
      const left = p.stock - (cart[p.id] || 0);
      const low = p.stock <= p.low_stock;
      return `<button class="prod" data-id="${p.id}" ${left <= 0 ? "disabled" : ""}>
        <span class="n">${esc(p.name)}</span>
        <span class="s ${low ? "low" : ""}">${left <= 0 ? "Out of stock" : left + " in stock"}</span>
        <span class="p">${fmt(p.price)}</span></button>`;
    }).join("") : `<div class="empty" style="grid-column:1/-1">No products match.</div>`;
  }

  // ---------- cart
  function add(id, n = 1) {
    const p = byId[id]; if (!p) return;
    const q = (cart[id] || 0) + n;
    if (q > p.stock) return flash(`Only ${p.stock} of ${p.name} in stock`);
    if (q <= 0) delete cart[id]; else cart[id] = q;
    render();
  }

  function totals() {
    const sub = Object.entries(cart).reduce((s, [id, q]) => s + byId[id].price * q, 0);
    const dis = Math.min(Math.max(parseFloat($("#discount").value) || 0, 0), sub);
    const tax = Math.round((sub - dis) * TAX * 100) / 100;
    const tot = Math.round((sub - dis + tax) * 100) / 100;
    return { sub, dis, tax, tot };
  }

  function render() {
    const ids = Object.keys(cart);
    $("#cart").innerHTML = ids.length ? ids.map((id) => {
      const p = byId[id], q = cart[id];
      return `<div class="ci"><div><div class="n">${esc(p.name)}</div><div class="u">${fmt(p.price)} each</div></div>
        <div class="qty"><button data-dec="${id}">−</button><span>${q}</span><button data-inc="${id}">+</button></div>
        <div class="t">${fmt(p.price * q)}</div></div>`;
    }).join("") : `<div class="empty">Tap a product to add it.</div>`;

    const t = totals();
    $("#sub").textContent = fmt(t.sub);
    $("#dis").textContent = t.dis ? "− " + fmt(t.dis) : fmt(0);
    if ($("#tax")) $("#tax").textContent = fmt(t.tax);
    $("#tot").textContent = fmt(t.tot);

    const paid = parseFloat($("#paid").value) || 0;
    const cash = method === "cash";
    $("#paidBox").style.visibility = cash ? "visible" : "hidden";
    $("#chgRow").style.display = cash ? "" : "none";
    $("#chg").textContent = fmt(Math.max(paid - t.tot, 0));
    $("#checkout").disabled = !ids.length || (cash && paid < t.tot);
    $("#checkout").textContent = ids.length ? "Charge " + fmt(t.tot) : "Charge";
    renderProducts();
  }

  // ---------- checkout
  async function checkout() {
    const btn = $("#checkout");
    btn.disabled = true;
    const t = totals();
    try {
      const res = await fetch("/api/checkout", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: Object.entries(cart).map(([id, qty]) => ({ id: +id, qty })),
          discount: t.dis, method, paid: method === "cash" ? parseFloat($("#paid").value) || 0 : t.tot,
        }),
      });
      const data = await res.json();
      if (!data.ok) { flash(data.error || "Checkout failed"); btn.disabled = false; return; }
      // reduce local stock so the grid stays correct without reload
      for (const [id, q] of Object.entries(cart)) byId[id].stock -= q;
      $("#doneInv").textContent = data.invoice;
      $("#doneChg").textContent = method === "cash" ? "Change: " + fmt(data.change) : fmt(t.tot) + " paid by " + method.toUpperCase();
      $("#doneRcpt").href = RECEIPT_URL + data.sale_id;
      $("#done").classList.add("show");
    } catch (e) {
      flash("Network error — sale not saved"); btn.disabled = false;
    }
  }

  function reset() {
    cart = {}; $("#discount").value = ""; $("#paid").value = "";
    $("#done").classList.remove("show"); render(); $("#search").focus();
  }

  // ---------- helpers
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function flash(msg) {
    let el = $("#toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; el.className = "flash error";
      el.style.cssText = "position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:30;box-shadow:0 6px 20px rgba(0,0,0,.12)";
      document.body.appendChild(el); }
    el.textContent = msg; el.style.display = "block";
    clearTimeout(el._t); el._t = setTimeout(() => (el.style.display = "none"), 2600);
  }

  // ---------- events
  $("#prods").addEventListener("click", (e) => { const b = e.target.closest(".prod"); if (b) add(b.dataset.id); });
  $("#cart").addEventListener("click", (e) => {
    if (e.target.dataset.inc) add(e.target.dataset.inc, 1);
    if (e.target.dataset.dec) add(e.target.dataset.dec, -1);
  });
  $("#chips").addEventListener("click", (e) => {
    const c = e.target.closest(".chip"); if (!c) return;
    document.querySelectorAll(".chip").forEach((x) => x.classList.remove("on"));
    c.classList.add("on"); cat = c.dataset.cat; renderProducts();
  });
  $("#pay").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#pay button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on"); method = b.dataset.m; render();
  });
  $("#search").addEventListener("input", renderProducts);
  $("#search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const q = e.target.value.trim().toLowerCase(); if (!q) return;
    // exact barcode match first (for barcode scanners), else the only search result
    let p = PRODUCTS.find((x) => (x.barcode || "").toLowerCase() === q);
    if (!p) { const m = PRODUCTS.filter((x) => x.name.toLowerCase().includes(q)); if (m.length === 1) p = m[0]; }
    if (p) { add(p.id); e.target.value = ""; renderProducts(); } else flash("No exact match");
  });
  $("#discount").addEventListener("input", render);
  $("#paid").addEventListener("input", render);
  $("#paid").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("#checkout").disabled) checkout(); });
  $("#checkout").addEventListener("click", checkout);
  $("#clear").addEventListener("click", () => { if (Object.keys(cart).length && confirm("Clear the cart?")) reset(); });
  $("#doneNew").addEventListener("click", reset);

  render();
})();
