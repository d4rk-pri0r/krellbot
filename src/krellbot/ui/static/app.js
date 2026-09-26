// krellbot dashboard: hydrate the embedded view and submit forms.
//
// The view JSON is injected into a global `__KB_VIEW__` by the server.
// The CSRF token is already in the `krellbot_csrf` cookie, but cookies
// are HttpOnly so we cannot read it from JS. The server embeds the
// token directly into every form's `csrf` hidden field on the way out.
//
// All dynamic value insertion uses `textContent` so an untrusted view
// string cannot inject HTML. No `innerHTML` writes anywhere in this
// file.

(function () {
  "use strict";

  var view = window.__KB_VIEW__ || {};
  var armed = Array.isArray(view.armed) ? view.armed : [];
  var paper = view.paper || {};
  var journal = Array.isArray(view.journal_tail) ? view.journal_tail : [];
  var license = view.license || null;
  var receipts = Array.isArray(view.receipts) ? view.receipts : [];
  var trust = view.trust || null;

  // ---- wizard nav active state (enhancement only; nav works without JS) ----
  // The wizard nav <a> elements already have sibling-relative hrefs, so a
  // no-JS browser navigates fine. JS just adds aria-current on the active
  // link so the user can see where they are.
  try {
    var current = document.body && document.body.dataset
      ? document.body.dataset.route
      : null;
    if (current) {
      var navLinks = document.querySelectorAll(".wizard-nav a[data-step]");
      for (var i = 0; i < navLinks.length; i++) {
        if (navLinks[i].getAttribute("data-step") === current) {
          navLinks[i].setAttribute("aria-current", "page");
        }
      }
    }
  } catch (_e) {
    // enhancement only — never break the page if nav highlighting fails
  }

  // ---- status grid (dashboard shell) --------------------------------------
  // Render the detected backend name from the trust snapshot if the
  // server embedded one. Always use textContent: the backend path is
  // a class string and we never want to interpret it as markup.
  var statusBackend = document.getElementById("status-backend");
  if (statusBackend) {
    if (trust && typeof trust.keychain_backend === "string" && trust.keychain_backend) {
      statusBackend.textContent = trust.keychain_backend;
      statusBackend.removeAttribute("aria-invalid");
    } else if (trust && trust.keychain_ok === false) {
      statusBackend.textContent = "(no persistent keychain detected)";
      statusBackend.setAttribute("aria-invalid", "true");
    } else {
      statusBackend.textContent = "(unknown)";
      statusBackend.setAttribute("aria-invalid", "true");
    }
  }

  // ---- armed packs table --------------------------------------------------
  var armedTable = document.getElementById("armed-table");
  var armedEmpty = document.getElementById("armed-empty");
  var armedBody = document.getElementById("armed-body");
  if (armedTable && armedEmpty && armedBody) {
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
  }

  // ---- paper state --------------------------------------------------------
  var paperBlocks = document.getElementById("paper-blocks");
  var paperEmpty = document.getElementById("paper-empty");
  if (paperBlocks && paperEmpty) {
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
        bal.className = "balances";
        bal.textContent = "balances: " + Object.keys(balances).map(function (k) {
          return k + "=" + balances[k];
        }).join(", ");
        card.appendChild(bal);

        var ord = document.createElement("div");
        ord.className = "open-orders";
        ord.textContent = "open orders: " + orders.length;
        card.appendChild(ord);

        var tbl = document.createElement("table");
        var thead = document.createElement("thead");
        var trh = document.createElement("tr");
        ["pair", "side", "qty", "stop_price"].forEach(function (label) {
          var th = document.createElement("th");
          th.scope = "col";
          th.textContent = label;
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
  }

  // ---- journal tail -------------------------------------------------------
  var journalPre = document.getElementById("journal-pre");
  var journalEmpty = document.getElementById("journal-empty");
  if (journalPre && journalEmpty) {
    if (journal.length === 0) {
      journalEmpty.hidden = false;
    } else {
      journalPre.hidden = false;
      journalPre.textContent = journal.map(function (r) {
        return JSON.stringify(r);
      }).join("\n");
    }
  }

  // ---- license cache ------------------------------------------------------
  var licensePre = document.getElementById("license-pre");
  if (licensePre) {
    licensePre.textContent = license ? JSON.stringify(license, null, 2) : "missing";
  }

  // ---- receipts -----------------------------------------------------------
  var receiptsList = document.getElementById("receipts-list");
  var receiptsEmpty = document.getElementById("receipts-empty");
  if (receiptsList && receiptsEmpty) {
    if (receipts.length === 0) {
      receiptsEmpty.hidden = false;
    } else {
      receipts.forEach(function (r) {
        var li = document.createElement("li");
        li.textContent = r.name + " (" + r.size + " bytes)";
        receiptsList.appendChild(li);
      });
    }
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
