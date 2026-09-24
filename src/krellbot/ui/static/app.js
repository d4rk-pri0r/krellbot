// krellbot dashboard: hydrate the embedded view and submit forms.
//
// The view JSON is injected into a global `__KB_VIEW__` by the server. The
// CSRF token is already in the `krellbot_csrf` cookie, but cookies are
// HttpOnly so we cannot read it from JS. Instead, the server embeds the
// token directly into every form's `csrf` field via a small helper below
// that pulls it from the URL hash... wait, the brief disallows that too.
// Instead, the server inserts the CSRF token into each form's hidden
// field by rewriting the HTML on the way out.

(function () {
  "use strict";

  var view = window.__KB_VIEW__ || {};
  var armed = Array.isArray(view.armed) ? view.armed : [];
  var paper = view.paper || {};
  var journal = Array.isArray(view.journal_tail) ? view.journal_tail : [];
  var license = view.license || null;
  var receipts = Array.isArray(view.receipts) ? view.receipts : [];

  // ---- armed packs table --------------------------------------------------
  var armedTable = document.getElementById("armed-table");
  var armedEmpty = document.getElementById("armed-empty");
  var armedBody = document.getElementById("armed-body");
  if (armed.length === 0) {
    armedEmpty.hidden = false;
  } else {
    armedTable.hidden = false;
    armed.forEach(function (a) {
      var tr = document.createElement("tr");
      function cell(text) {
        var td = document.createElement("td");
        td.textContent = String(text == null ? "" : text);
        tr.appendChild(td);
      }
      cell(a.pack_id);
      cell(a.pack_version);
      cell(a.pending_version || "");
      cell(a.venue);
      cell(a.pair);
      cell(a.mode);
      cell(a.cap);
      cell(a.stop);
      cell(a.owned_qty);

      var actionsTd = document.createElement("td");
      var disarmBtn = document.createElement("button");
      disarmBtn.type = "button";
      disarmBtn.textContent = "disarm";
      disarmBtn.dataset.venue = a.venue;
      disarmBtn.dataset.pair = a.pair;
      disarmBtn.addEventListener("click", function () {
        submitForm(document.getElementById("form-disarm"), {
          venue: a.venue,
          pair: a.pair,
        });
      });
      actionsTd.appendChild(disarmBtn);

      if (a.pending_version) {
        var adoptBtn = document.createElement("button");
        adoptBtn.type = "button";
        adoptBtn.textContent = "adopt v" + a.pending_version;
        adoptBtn.style.marginLeft = ".25rem";
        adoptBtn.addEventListener("click", function () {
          submitForm(document.getElementById("form-adopt"), { pack_id: a.pack_id });
        });
        actionsTd.appendChild(adoptBtn);
      }
      tr.appendChild(actionsTd);
      armedBody.appendChild(tr);
    });
  }

  // ---- paper state --------------------------------------------------------
  var paperBlocks = document.getElementById("paper-blocks");
  var paperEmpty = document.getElementById("paper-empty");
  var venues = Object.keys(paper);
  if (venues.length === 0) {
    paperEmpty.hidden = false;
  } else {
    venues.forEach(function (venue) {
      var s = paper[venue] || {};
      var balances = s.balances || {};
      var orders = s.open_orders || [];
      var card = document.createElement("div");
      card.className = "card";

      var h = document.createElement("h3");
      h.textContent = venue;
      card.appendChild(h);

      var bal = document.createElement("div");
      bal.textContent = "balances: " + Object.keys(balances).map(function (k) {
        return k + "=" + balances[k];
      }).join(", ");
      card.appendChild(bal);

      var ord = document.createElement("div");
      ord.textContent = "open orders: " + orders.length;
      card.appendChild(ord);

      var tbl = document.createElement("table");
      var thead = document.createElement("thead");
      var trh = document.createElement("tr");
      ["pair", "side", "qty", "stop_price"].forEach(function (h) {
        var th = document.createElement("th");
        th.textContent = h;
        trh.appendChild(th);
      });
      thead.appendChild(trh);
      tbl.appendChild(thead);
      var tb = document.createElement("tbody");
      orders.forEach(function (o) {
        var tr = document.createElement("tr");
        ["pair", "side", "qty", "stop_price"].forEach(function (k) {
          var td = document.createElement("td");
          td.textContent = o[k] == null ? "" : String(o[k]);
          tr.appendChild(td);
        });
        tb.appendChild(tr);
      });
      tbl.appendChild(tb);
      card.appendChild(tbl);

      paperBlocks.appendChild(card);
    });
  }

  // ---- journal tail -------------------------------------------------------
  var journalPre = document.getElementById("journal-pre");
  var journalEmpty = document.getElementById("journal-empty");
  if (journal.length === 0) {
    journalEmpty.hidden = false;
  } else {
    journalPre.hidden = false;
    journalPre.textContent = journal.map(function (r) {
      return JSON.stringify(r);
    }).join("\n");
  }

  // ---- license cache ------------------------------------------------------
  var licensePre = document.getElementById("license-pre");
  licensePre.textContent = license ? JSON.stringify(license, null, 2) : "missing";

  // ---- receipts -----------------------------------------------------------
  var receiptsList = document.getElementById("receipts-list");
  var receiptsEmpty = document.getElementById("receipts-empty");
  if (receipts.length === 0) {
    receiptsEmpty.hidden = false;
  } else {
    receipts.forEach(function (r) {
      var li = document.createElement("li");
      li.textContent = r.name + " (" + r.size + " bytes)";
      receiptsList.appendChild(li);
    });
  }

  // ---- form helpers -------------------------------------------------------

  // Pull the CSRF token from the first form's hidden field (the server
  // embeds it). All forms share the same token; the server compares form
  // csrf against cookie csrf, both set on the first GET.
  function readCsrf() {
    var first = document.querySelector('input[name="csrf"]');
    return first ? first.value : "";
  }

  // Inject the CSRF into every form that doesn't have it yet (the server
  // already fills it; this is a fallback for templating mistakes).
  document.querySelectorAll('input[name="csrf"]').forEach(function (el) {
    if (!el.value) {
      el.value = readCsrf();
    }
  });

  function submitForm(form, overrides) {
    var fd = new FormData(form);
    Object.keys(overrides || {}).forEach(function (k) {
      fd.set(k, overrides[k]);
    });
    fd.set("csrf", readCsrf());
    var body = new URLSearchParams();
    fd.forEach(function (v, k) { body.append(k, String(v)); });
    fetch(form.getAttribute("action"), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
      credentials: "same-origin",
    }).then(function (r) {
      var flash = document.getElementById("flash-pre");
      flash.textContent = r.status + " " + r.statusText;
      return r.text();
    }).then(function (txt) {
      if (txt) {
        document.getElementById("flash-pre").textContent += "\n" + txt;
      }
      // Reload the page so the embedded view refreshes.
      setTimeout(function () { location.reload(); }, 600);
    }).catch(function (e) {
      document.getElementById("flash-pre").textContent = "error: " + e;
    });
  }

  document.querySelectorAll("form").forEach(function (form) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      submitForm(form, {});
    });
  });
})();
