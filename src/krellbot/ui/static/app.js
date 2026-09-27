// krellbot command-center dashboard: hydrate the embedded view and submit forms.
//
// The view JSON is injected into a global `__KB_VIEW__` by the server.
// The CSRF token is already in the `krellbot_csrf` cookie, but cookies
// are HttpOnly so we cannot read it from JS. The server embeds the
// token directly into every form's `csrf` hidden field on the way out.
//
// All dynamic value insertion uses `textContent` so an untrusted view
// string cannot inject HTML. No `innerHTML` writes anywhere in this
// file. No invented telemetry: every field rendered on this page is
// either a literal the server placed in the view or an explicit
// "unavailable / not measured locally" string.

(function () {
  "use strict";

  var view = window.__KB_VIEW__ || {};
  var armed = Array.isArray(view.armed) ? view.armed : [];
  var paper = view.paper || {};
  var journal = Array.isArray(view.journal_tail) ? view.journal_tail : [];
  var license = view.license || null;
  var receipts = Array.isArray(view.receipts) ? view.receipts : [];
  var trust = view.trust || null;
  var asOf = typeof view.as_of === "string" ? view.as_of : null;
  var readiness = view.readiness || null;
  var tradingReadiness = typeof view.trading_readiness === "string"
    ? view.trading_readiness
    : "not evaluated on this page; run `krellbot doctor`";
  var keysStatus = view.keys_status || {};
  var licenseSummary = view.license_summary || null;
  var schedulerInstalled = view.scheduler_installed;
  var tickState = view.tick_state || null;

  // ---- helpers ------------------------------------------------------------

  function el(id) {
    return document.getElementById(id);
  }

  function setText(parent, selector, value) {
    if (!parent) return;
    var node = parent.querySelector(selector);
    if (node) node.textContent = value;
  }

  function setBind(metricName, value, klass) {
    var metric = document.querySelector('[data-metric="' + metricName + '"]');
    if (!metric) return;
    var valueNode = metric.querySelector('[data-bind="' + metricName + '_value"]');
    if (valueNode) {
      valueNode.textContent = value;
      valueNode.classList.remove("is-zero", "is-empty", "is-stale", "is-ok", "is-fail");
      if (klass) valueNode.classList.add(klass);
    }
  }

  function fmtAge(seconds) {
    if (typeof seconds !== "number" || !isFinite(seconds) || seconds < 0) return "—";
    if (seconds < 60) return seconds + "s ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
    return Math.floor(seconds / 86400) + "d ago";
  }

  function fmtTs(unixSeconds) {
    if (typeof unixSeconds !== "number" || !isFinite(unixSeconds) || unixSeconds <= 0) return "—";
    try {
      var d = new Date(unixSeconds * 1000);
      if (isNaN(d.getTime())) return "—";
      var pad = function (n) { return (n < 10 ? "0" : "") + n; };
      return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate())
        + " " + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + "Z";
    } catch (_e) {
      return "—";
    }
  }

  // ---- header -------------------------------------------------------------

  // As-of timestamp: tells the operator when this snapshot was taken.
  // The dashboard does not refresh on a timer; a manual reload is the
  // only way to update it.
  if (asOf && el("as-of-value")) {
    el("as-of-value").textContent = asOf + " UTC";
  }
  if (trust && typeof trust.home === "string" && el("home-value")) {
    el("home-value").textContent = trust.home;
  }

  // ---- overview metrics ---------------------------------------------------

  // Armed metric: count of armed packs, plus paper vs. live split.
  (function renderArmedMetric() {
    var count = armed.length;
    if (count === 0) {
      setBind("armed", "0", "is-zero");
      setText(document.querySelector('[data-metric="armed"]'), '[data-bind="armed_sub"]', "no packs armed");
      return;
    }
    var paperN = 0, liveN = 0;
    for (var i = 0; i < armed.length; i++) {
      if (armed[i] && armed[i].mode === "paper") paperN++;
      else if (armed[i] && armed[i].mode === "live") liveN++;
    }
    var subParts = [];
    if (paperN) subParts.push(paperN + " paper");
    if (liveN) subParts.push(liveN + " live");
    setBind("armed", String(count), count > 0 ? "is-ok" : "is-zero");
    setText(document.querySelector('[data-metric="armed"]'), '[data-bind="armed_sub"]', subParts.join(" · ") || "—");
  })();

  // Paper metric: count of venues with on-disk state, plus positions
  // (open orders) summed across venues. The dashboard never invents a
  // live venue balance; if there is no paper-<venue>.json file, the
  // venue is absent from the view.
  (function renderPaperMetric() {
    var venues = Object.keys(paper);
    var totalOpen = 0;
    for (var i = 0; i < venues.length; i++) {
      var s = paper[venues[i]] || {};
      var orders = Array.isArray(s.open_orders) ? s.open_orders : [];
      totalOpen += orders.length;
    }
    if (venues.length === 0) {
      setBind("paper", "0", "is-empty");
      setText(document.querySelector('[data-metric="paper"]'), '[data-bind="paper_sub"]', "no paper venues armed");
      return;
    }
    setBind("paper", String(totalOpen), totalOpen > 0 ? "is-ok" : "is-empty");
    setText(
      document.querySelector('[data-metric="paper"]'),
      '[data-bind="paper_sub"]',
      totalOpen + " open · " + venues.length + " venue" + (venues.length === 1 ? "" : "s")
    );
  })();

  // Tick metric: most-recent tick journal entry. The dashboard does
  // not invent a heartbeat; if there is no tick record, it says so
  // explicitly. A tick older than 2 hours is rendered as stale.
  (function renderTickMetric() {
    if (!tickState || !tickState.present) {
      setBind("tick", "stopped", "is-empty");
      setText(document.querySelector('[data-metric="tick"]'), '[data-bind="tick_sub"]', "no tick journal entry; not measured locally");
      return;
    }
    var age = tickState.age_seconds;
    var klass = (typeof age === "number" && age >= 7200) ? "is-stale" : "is-ok";
    setBind("tick", fmtAge(age), klass);
    setText(
      document.querySelector('[data-metric="tick"]'),
      '[data-bind="tick_sub"]',
      "last record at " + fmtTs(tickState.last_ts) + " (server clock)"
    );
  })();

  // Install readiness metric: aggregate boolean from the readiness
  // rows the server computed.
  (function renderReadyMetric() {
    if (!readiness || !Array.isArray(readiness.rows)) {
      setBind("ready", "unknown", "is-empty");
      setText(document.querySelector('[data-metric="ready"]'), '[data-bind="ready_sub"]', "readiness not computed");
      return;
    }
    if (readiness.install_ready) {
      setBind("ready", "ready", "is-ok");
      setText(document.querySelector('[data-metric="ready"]'), '[data-bind="ready_sub"]', "runtime can serve the local UI");
    } else {
      var fails = 0;
      for (var i = 0; i < readiness.rows.length; i++) {
        if (readiness.rows[i] && readiness.rows[i].ok === false) fails++;
      }
      setBind("ready", "blocked", "is-fail");
      setText(
        document.querySelector('[data-metric="ready"]'),
        '[data-bind="ready_sub"]',
        fails + " check" + (fails === 1 ? "" : "s") + " failing — run `krellbot doctor`"
      );
    }
  })();

  // ---- readiness detail block --------------------------------------------

  (function renderReadinessList() {
    var list = el("readiness-list");
    if (!list) return;
    list.innerHTML = ""; // safe: container is empty; we build rows via DOM.
    if (!readiness || !Array.isArray(readiness.rows) || readiness.rows.length === 0) {
      var li = document.createElement("li");
      li.className = "muted";
      li.textContent = "no readiness rows reported";
      list.appendChild(li);
      return;
    }
    readiness.rows.forEach(function (row) {
      if (!row || typeof row.label !== "string") return;
      var li = document.createElement("li");
      var pill = document.createElement("span");
      pill.className = "pill " + (row.ok ? "ok" : "fail");
      pill.textContent = row.ok ? "ok" : "fail";
      var label = document.createElement("span");
      label.textContent = row.label;
      var why = document.createElement("span");
      why.className = "muted";
      why.textContent = row.why ? "— " + row.why : "";
      li.appendChild(pill);
      li.appendChild(label);
      li.appendChild(why);
      list.appendChild(li);
    });
  })();

  // ---- per-venue key verification ----------------------------------------

  // The dashboard never reads the keyring on a GET. Every value here
  // comes from the durable status file the wizard POST writes.
  (function renderKeyStatus() {
    var ddK = document.querySelector('[data-venue="kraken"]');
    var ddC = document.querySelector('[data-venue="coinbase"]');
    function row(venue) {
      var r = keysStatus && keysStatus[venue];
      if (!r) return "unknown; not currently verified";
      if (r.stored && typeof r.verified_at === "string" && r.verified_at) {
        return "last stored through wizard at " + r.verified_at + "; current key presence not checked";
      }
      return "unknown; not currently verified";
    }
    if (ddK) ddK.textContent = row("kraken");
    if (ddC) ddC.textContent = row("coinbase");
  })();

  // ---- license summary ----------------------------------------------------

  (function renderLicense() {
    var pre = el("license-readout");
    if (!pre) return;
    if (!licenseSummary || typeof licenseSummary !== "object" || licenseSummary.status === "missing") {
      pre.textContent = "license cache: missing\nstatus: missing";
      return;
    }
    var lines = [];
    lines.push("status: " + (licenseSummary.status || "missing"));
    if (typeof licenseSummary.period_end === "number") {
      lines.push("period_end: " + fmtTs(licenseSummary.period_end));
    }
    if (typeof licenseSummary.grace_until === "number") {
      lines.push("grace_until: " + fmtTs(licenseSummary.grace_until));
    }
    pre.textContent = lines.join("\n");
  })();

  // ---- trust posture section ---------------------------------------------

  if (trust) {
    var backendNode = el("status-backend");
    if (backendNode) {
      if (typeof trust.keychain_backend === "string" && trust.keychain_backend) {
        backendNode.textContent = trust.keychain_backend;
      } else if (trust.keychain_ok === false) {
        backendNode.textContent = "(no persistent keychain detected)";
        backendNode.setAttribute("aria-invalid", "true");
      } else {
        backendNode.textContent = "(unknown)";
        backendNode.setAttribute("aria-invalid", "true");
      }
    }
    var homeNode = el("status-home");
    if (homeNode && typeof trust.home === "string") homeNode.textContent = trust.home;
    var homeModeNode = el("status-home-mode");
    if (homeModeNode) {
      homeModeNode.textContent = trust.home_mode ? String(trust.home_mode) : "unknown on this OS";
    }
  }

  var schedulerNode = el("status-scheduler");
  if (schedulerNode) {
    if (schedulerInstalled === true) {
      schedulerNode.textContent = "unit file present";
    } else if (schedulerInstalled === false) {
      schedulerNode.textContent = "no unit installed (run `krellbot service install`)";
    } else {
      schedulerNode.textContent = "scheduler not modelled on this OS";
    }
  }

  var tickNode = el("status-tick");
  if (tickNode) {
    if (!tickState || !tickState.present) {
      tickNode.textContent = "no tick journal entry on disk";
    } else {
      tickNode.textContent = "last tick " + fmtAge(tickState.age_seconds) + " (" + fmtTs(tickState.last_ts) + ")";
    }
  }

  var licNode = el("status-license");
  if (licNode) {
    if (licenseSummary && licenseSummary.status && licenseSummary.status !== "missing") {
      licNode.textContent = licenseSummary.status + " (cache present)";
    } else {
      licNode.textContent = "missing";
    }
  }

  var tradingNode = el("status-trading");
  if (tradingNode) tradingNode.textContent = tradingReadiness;

  var diag = el("status-diagnostic");
  if (diag && trust) {
    if (trust.posture_ok) {
      diag.className = "trust-ok";
      diag.textContent = "All posture checks passed.";
    } else {
      diag.className = "trust-fail";
      var w = trust.posture_warning ? String(trust.posture_warning) : "";
      diag.textContent = w + " Run `krellbot doctor` for a real diagnostic.";
    }
  }

  // ---- armed packs table --------------------------------------------------

  var armedTable = el("armed-table");
  var armedEmpty = el("armed-empty");
  var armedBody = el("armed-body");
  if (armedTable && armedEmpty && armedBody) {
    if (armed.length === 0) {
      armedEmpty.hidden = false;
    } else {
      armedTable.hidden = false;
      armed.forEach(function (a) {
        if (!a || typeof a !== "object") return;
        var tr = document.createElement("tr");
        function cell(text, klass) {
          var td = document.createElement("td");
          td.textContent = text == null ? "" : String(text);
          if (klass) td.className = klass;
          tr.appendChild(td);
        }
        cell(a.pack_id);
        cell(a.pack_version);
        cell(a.pending_version || "");
        cell(a.venue);
        cell(a.pair);
        var modeCell = a.mode === "paper" ? "paper" : (a.mode === "live" ? "live" : (a.mode || ""));
        cell(modeCell, a.mode === "live" ? "is-stale" : "");
        cell(a.cap);
        cell(a.stop);
        cell(a.owned_qty);
        cell(typeof a.armed_at_ts === "number" && a.armed_at_ts > 0 ? fmtTs(a.armed_at_ts) : "");

        var actionsTd = document.createElement("td");
        var disarmBtn = document.createElement("button");
        disarmBtn.type = "button";
        disarmBtn.textContent = "disarm";
        disarmBtn.dataset.venue = a.venue || "";
        disarmBtn.dataset.pair = a.pair || "";
        disarmBtn.addEventListener("click", function () {
          submitForm(document.getElementById("form-disarm"), {
            venue: a.venue || "",
            pair: a.pair || "",
          });
        });
        actionsTd.appendChild(disarmBtn);
        if (a.pending_version) {
          var adoptBtn = document.createElement("button");
          adoptBtn.type = "button";
          adoptBtn.textContent = "adopt v" + a.pending_version;
          adoptBtn.style.marginLeft = ".25rem";
          adoptBtn.addEventListener("click", function () {
            submitForm(document.getElementById("form-adopt"), { pack_id: a.pack_id || "" });
          });
          actionsTd.appendChild(adoptBtn);
        }
        tr.appendChild(actionsTd);
        armedBody.appendChild(tr);
      });
    }
  }

  // ---- paper state --------------------------------------------------------

  var paperBlocks = el("paper-blocks");
  var paperEmpty = el("paper-empty");
  if (paperBlocks && paperEmpty) {
    var venues = Object.keys(paper);
    if (venues.length === 0) {
      paperEmpty.hidden = false;
    } else {
      venues.forEach(function (venue) {
        var s = paper[venue] || {};
        var balances = s.balances || {};
        var orders = Array.isArray(s.open_orders) ? s.open_orders : [];
        var fills = Array.isArray(s.recent_fills) ? s.recent_fills : [];

        var card = document.createElement("div");
        card.className = "card";

        var h = document.createElement("h3");
        h.textContent = venue;
        card.appendChild(h);

        // Balances: render as a small grid, never invented.
        var bal = document.createElement("p");
        bal.className = "muted";
        var balKeys = Object.keys(balances);
        if (balKeys.length === 0) {
          bal.textContent = "balances: (none recorded)";
        } else {
          bal.textContent = "balances: " + balKeys.map(function (k) {
            return k + "=" + (balances[k] == null ? "" : String(balances[k]));
          }).join(", ");
        }
        card.appendChild(bal);

        // Open orders table (readable rows).
        var ordersH = document.createElement("p");
        ordersH.className = "muted";
        ordersH.textContent = "open orders: " + orders.length;
        card.appendChild(ordersH);

        if (orders.length > 0) {
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
            if (!o || typeof o !== "object") return;
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
        }

        // Recent fills: last 5 only; rendered as plain rows.
        if (fills.length > 0) {
          var fillsH = document.createElement("p");
          fillsH.className = "muted";
          fillsH.textContent = "recent fills (last " + Math.min(fills.length, 5) + "):";
          card.appendChild(fillsH);

          var fTbl = document.createElement("table");
          var fHead = document.createElement("thead");
          var fTrh = document.createElement("tr");
          ["ts", "pair", "side", "qty", "price"].forEach(function (label) {
            var th = document.createElement("th");
            th.scope = "col";
            th.textContent = label;
            fTrh.appendChild(th);
          });
          fHead.appendChild(fTrh);
          fTbl.appendChild(fHead);
          var fTb = document.createElement("tbody");
          var tail = fills.slice(-5);
          tail.forEach(function (f) {
            if (!f || typeof f !== "object") return;
            var tr = document.createElement("tr");
            var tsText = (typeof f.ts_ms === "number") ? fmtTs(Math.floor(f.ts_ms / 1000)) : "";
            [tsText, f.pair, f.side, f.qty, f.price].forEach(function (v) {
              var td = document.createElement("td");
              td.textContent = v == null ? "" : String(v);
              tr.appendChild(td);
            });
            fTb.appendChild(tr);
          });
          fTbl.appendChild(fTb);
          card.appendChild(fTbl);
        }

        paperBlocks.appendChild(card);
      });
    }
  }

  // ---- journal tail: readable rows, not raw JSON -------------------------

  var journalTable = el("journal-table");
  var journalEmpty = el("journal-empty");
  var journalBody = el("journal-body");
  if (journalTable && journalEmpty && journalBody) {
    if (journal.length === 0) {
      journalEmpty.hidden = false;
    } else {
      journalTable.hidden = false;
      journal.forEach(function (r) {
        if (!r || typeof r !== "object") return;
        var tr = document.createElement("tr");
        var tsText = (typeof r.ts === "number") ? fmtTs(r.ts) : "";
        function td(text) {
          var node = document.createElement("td");
          node.textContent = text == null ? "" : String(text);
          tr.appendChild(node);
        }
        td(tsText);
        td(r.kind);
        td(r.venue);
        td(r.pack);
        // Detail: surface the most informative scalar fields; everything
        // else is dropped, never invented.
        var detail = r.detail;
        var detailText = "";
        if (detail && typeof detail === "object") {
          var parts = [];
          if (detail.pair) parts.push("pair=" + detail.pair);
          if (detail.qty != null) parts.push("qty=" + detail.qty);
          if (detail.price != null) parts.push("price=" + detail.price);
          if (detail.reason) parts.push("reason=" + detail.reason);
          if (detail.message) parts.push("msg=" + detail.message);
          detailText = parts.join(" · ");
        }
        td(detailText);
        journalBody.appendChild(tr);
      });
    }
  }

  // ---- receipts ----------------------------------------------------------

  var receiptsList = el("receipts-list");
  var receiptsEmpty = el("receipts-empty");
  if (receiptsList && receiptsEmpty) {
    if (receipts.length === 0) {
      receiptsEmpty.hidden = false;
    } else {
      receipts.forEach(function (r) {
        if (!r || typeof r !== "object") return;
        var li = document.createElement("li");
        li.textContent = (r.name || "(unnamed)") + " (" + (r.size == null ? "?" : r.size) + " bytes)";
        receiptsList.appendChild(li);
      });
    }
  }

  // ---- ops-nav: smooth scroll + active section highlight ----------------

  // ---- wizard stepper order (kept in sync with server.py) ---------------
  // The server-side stepper in krellbot.ui.server._wizard_html is:
  //   welcome → security → keys → next
  // The dashboard shell does not render the stepper itself (the
  // wizard template does), but the literal list below is kept here so
  // the dashboard JS and the wizard JS share one source of truth for
  // step ordering. The dashboard's nav does not consult it directly;
  // the wizard template sets aria-current server-side.
  var stepperOrder = ["welcome", "security", "keys", "next"];

  (function () {
    var navLinks = document.querySelectorAll(".ops-nav a[data-ops]");
    navLinks.forEach(function (a) {
      a.addEventListener("click", function (ev) {
        var href = a.getAttribute("href") || "";
        if (href.charAt(0) !== "#") return;
        var target = document.getElementById(href.slice(1));
        if (!target) return;
        ev.preventDefault();
        target.scrollIntoView({ behavior: "smooth", block: "start" });
        navLinks.forEach(function (n) { n.setAttribute("aria-current", "false"); });
        a.setAttribute("aria-current", "true");
        history.replaceState(null, "", href);
      });
    });
  })();

  // ---- form helpers ------------------------------------------------------

  function readCsrf() {
    var first = document.querySelector('input[name="csrf"]');
    return first ? first.value : "";
  }

  document.querySelectorAll('input[name="csrf"]').forEach(function (el2) {
    if (!el2.value) {
      el2.value = readCsrf();
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
