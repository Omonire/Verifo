/* Superadmin console: site branding, switchboard, organizations, users.
 * Runs on a platform-scoped token issued by /api/v1/superadmin/bootstrap. */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }
  function esc(s) { return Verifo.esc(s); }
  function fmtDT(s) { return s ? new Date(s).toLocaleString() : "—"; }

  var SUPER = null;   // platform token issued after bootstrap
  var tab = "site";

  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers["Authorization"] = "Bearer " + SUPER;
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    return fetch("/api/v1" + path, opts).then(function (r) {
      return r.json().then(function (b) { return { ok: r.ok, status: r.status, body: b }; });
    });
  }

  Verifo.bootstrap().then(function () {
    return Verifo.api("/superadmin/bootstrap");
  }).then(function (r) {
    if (!r.ok || !r.body) {
      Verifo.clearToken();
      window.location.href = "/signin";
      throw new Error("not a superadmin");
    }
    SUPER = r.body.token;
    $("sa-name").textContent = (r.body.user && r.body.user.full_name) || "Superadmin";
    var tabs = $("sa-tabs");
    tabs.querySelectorAll(".tab-pill").forEach(function (b) {
      b.addEventListener("click", function () { switchTab(b.getAttribute("data-tab")); });
    });
    $("sa-signout").addEventListener("click", function () { Verifo.signOut(); });
    switchTab("site");
  }).catch(function () {});

  function switchTab(name) {
    tab = name;
    var tabs = $("sa-tabs");
    tabs.querySelectorAll(".tab-pill").forEach(function (b) {
      b.className = "tab-pill " + (b.getAttribute("data-tab") === name ? "on" : "off");
    });
    ["site", "switchboard", "orgs", "users"].forEach(function (t) {
      $("tab-" + t).hidden = t !== name;
    });
    if (name === "site") loadSite();
    if (name === "switchboard") loadSwitchboard();
    if (name === "orgs") loadOrgs();
    if (name === "users") loadUsers();
  }

  function card(html) {
    return '<div class="card"><div class="card-body" style="padding:1.5rem">' + html + "</div></div>";
  }
  function labelBox(name, field, value, opts) {
    opts = opts || {};
    return '<div><label class="label">' + esc(name) + "</label>" +
      (opts.area
        ? '<textarea class="input" rows="2" id="' + field + '">' + esc(value) + "</textarea>"
        : '<input class="input" id="' + field + '" value="' + esc(value) + '"' + ((opts.type && ' type="' + opts.type + '"') || "") + ">") +
      (opts.hint ? '<p class="text-xs text-muted" style="margin-top:0.25rem">' + esc(opts.hint) + "</p>" : "") +
      "</div>";
  }

  /* ---------- Site branding ---------- */

  function loadSite() {
    api("/superadmin/settings").then(function (r) {
      if (!r.ok) return;
      var s = r.body.settings || {};
      var html = card(
        '<h2 style="font-size:1rem">Site brand</h2>' +
        '<p class="text-xs text-muted" style="margin-top:0.25rem">Shown on the splash screen, landing page and every public footer.</p>' +
        '<div class="split-2col" style="gap:0.875rem;margin-top:1.25rem">' +
        labelBox("Site name", "site_name", s.site_name) +
        labelBox("Tagline", "tagline", s.tagline) +
        labelBox("Support email", "support_email", s.support_email, { type: "email" }) +
        labelBox("Footer text", "footer_text", s.footer_text) +
        '</div><div id="site-msg" style="margin-top:0.875rem"></div>' +
        '<button type="button" class="btn btn-primary" id="site-save" style="margin-top:0.75rem">Save settings</button>'
      );
      $("tab-site").innerHTML = html;
      $("site-save").addEventListener("click", function () {
        var body = {
          site_name: $("site_name").value.trim(),
          tagline: $("tagline").value.trim(),
          support_email: $("support_email").value.trim(),
          footer_text: $("footer_text").value.trim(),
        };
        if (!body.site_name) { msg("site-msg", "Site name is required.", true); return; }
        $("site-save").disabled = true;
        api("/superadmin/settings", { method: "PUT", body: body }).then(function (r) {
          if (r.ok) msg("site-msg", "Site settings saved. Refresh to see them on the public pages.");
          else msg("site-msg", (r.body.error && r.body.error.message) || "Save failed.", true);
        }).finally(function () { $("site-save").disabled = false; });
      });
    });
  }

  /* ---------- Switchboard ---------- */

  function loadSwitchboard() {
    api("/superadmin/settings").then(function (r) {
      if (!r.ok) return;
      var s = r.body.settings || {};
      var ann = s.announcement || "";
      var html = card(
        '<h2 style="font-size:1rem">Global switchboard</h2>' +
        '<p class="text-xs text-muted" style="margin-top:0.25rem">Platform-wide flags the app honours.</p>' +
        '<div style="display:grid;gap:0.75rem;margin-top:1.25rem">' +
        toggleCard("registration_open", s.registration_open,
          "Self-serve registration",
          "When on, anyone can create a workspace from /request-access. When off, accounts can only be created by a superadmin.") +
        toggleCard("demo_mode", s.demo_mode,
          "Demo mode",
          "Highlights demo fixtures and sample documents in the UI. Off for production-style behaviour.") +
        '<div style="margin-top:0.75rem">' + labelBox("Announcement (shown in topbar)", "announcement", ann, { area: true }) + "</div>" +
        '</div><div id="sw-msg" style="margin-top:0.875rem"></div>' +
        '<button type="button" class="btn btn-primary" id="sw-save" style="margin-top:0.75rem">Save switchboard</button>'
      );
      $("tab-switchboard").innerHTML = html;
      $("sw-save").addEventListener("click", function () {
        api("/superadmin/settings", {
          method: "PUT",
          body: {
            registration_open: $("reg-open").checked,
            demo_mode: $("demo-mode").checked,
            announcement: $("announcement").value.trim(),
          },
        }).then(function (r) {
          if (r.ok) msg("sw-msg", "Switchboard updated.");
          else msg("sw-msg", (r.body.error && r.body.error.message) || "Save failed.", true);
        });
      });
    });
  }

  function toggleCard(id, checked, title, desc) {
    return '<div style="border:1px solid var(--gray-200);border-radius:10px;padding:1rem;display:flex;align-items:flex-start;gap:0.875rem">' +
      '<input type="checkbox" id="' + id + '"' + (checked ? " checked" : "") + ' style="margin-top:0.25rem">' +
      '<div><p style="font-weight:600;color:var(--gray-800);font-size:0.875rem">' + esc(title) + "</p>" +
      '<p class="text-xs text-muted" style="margin-top:0.25rem;line-height:1.5">' + esc(desc) + "</p></div></div>";
  }

  /* ---------- Organizations ---------- */

  function loadOrgs() {
    api("/superadmin/organizations").then(function (r) {
      var orgs = r.ok && r.body ? r.body.organizations || [] : [];
      var html = card(
        '<div class="flex items-center justify-between"><h2 style="font-size:1rem">Organizations</h2>' +
        '<button type="button" class="btn btn-secondary btn-sm" id="org-new-toggle">New workspace</button></div>' +
        '<div id="org-new-form" hidden style="margin-top:1rem;border:1px solid var(--gray-200);border-radius:10px;padding:1rem;background:var(--gray-50)">' +
        '<div class="split-2col" style="gap:0.625rem">' +
        '<input class="input" id="org-name" placeholder="Organization name">' +
        '<input class="input" id="org-slug" placeholder="slug (e.g. acme-university)">' +
        '<input class="input" id="org-industry" placeholder="Industry (optional)">' +
        '<input class="input" id="org-admin-email" type="email" placeholder="Admin email (optional)">' +
        '<input class="input" id="org-admin-password" type="password" placeholder="Admin temp password (optional)">' +
        '<input class="input" id="org-admin-name" placeholder="Admin full name (optional)">' +
        '</div><div id="org-new-msg" style="margin-top:0.5rem"></div>' +
        '<button type="button" class="btn btn-primary btn-sm" id="org-new-save" style="margin-top:0.5rem">Create workspace</button></div>' +
        '<div class="table-wrap" style="margin-top:1.25rem"><table class="v-table"><thead><tr>' +
        "<th>Organization</th><th>Slug</th><th>Industry</th><th>Members</th><th>Status</th><th>Created</th><th class=\"text-right\">Actions</th>" +
        "</tr></thead><tbody>"
      );
      if (!orgs.length) {
        html += '<tr><td colspan="7" class="text-muted" style="text-align:center;padding:2rem">No organizations yet.</td></tr>';
      }
      orgs.forEach(function (o) {
        var toggle = o.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE";
        var label = o.status === "ACTIVE" ? "Suspend" : "Activate";
        html += "<tr><td style=\"font-weight:500;color:var(--gray-700)\">" + esc(o.name) + "</td>" +
          '<td class="mono text-xs text-muted">' + esc(o.slug) + "</td>" +
          '<td class="text-muted">' + esc(o.industry || "—") + "</td>" +
          "<td>" + o.member_count + "</td>" +
          "<td>" + Verifo.statusBadge(o.status) + "</td>" +
          '<td class="text-muted">' + fmtDT(o.created_at) + "</td>" +
          '<td class="text-right"><button type="button" class="btn btn-ghost btn-sm" data-org="' + esc(o.id) + '" data-status="' + toggle + '"' + (o.status === "ACTIVE" ? ' style="color:var(--red-700)"' : "") + ">" +
          label + "</button></td></tr>";
      });
      html += "</tbody></table></div></div>";
      $("tab-orgs").innerHTML = html;

      var formVisible = false;
      $("org-new-toggle").addEventListener("click", function () {
        formVisible = !formVisible;
        $("org-new-form").hidden = !formVisible;
      });
      $("org-new-save").addEventListener("click", function () {
        $("org-new-save").disabled = true;
        api("/superadmin/organizations", {
          method: "POST",
          body: {
            name: $("org-name").value.trim(),
            slug: $("org-slug").value.trim(),
            industry: $("org-industry").value.trim() || undefined,
            admin_email: $("org-admin-email").value.trim() || undefined,
            admin_password: $("org-admin-password").value || undefined,
            admin_name: $("org-admin-name").value.trim() || undefined,
          },
        }).then(function (r) {
          if (r.ok) { msg("org-new-msg", "Workspace created."); loadOrgs(); }
          else msg("org-new-msg", (r.body.error && r.body.error.message) || "Create failed.", true);
        }).finally(function () { $("org-new-save").disabled = false; });
      });
      $("tab-orgs").querySelectorAll("button[data-org]").forEach(function (b) {
        b.addEventListener("click", function () {
          api("/superadmin/organizations/" + b.getAttribute("data-org") + "/status", {
            method: "POST", body: { status: b.getAttribute("data-status") },
          }).then(function () { loadOrgs(); });
        });
      });
    });
  }

  /* ---------- Users ---------- */

  function loadUsers() {
    api("/superadmin/users").then(function (r) {
      var users = r.ok && r.body ? r.body.users || [] : [];
      var html = card(
        '<h2 style="font-size:1rem">Users</h2>' +
        '<p class="text-xs text-muted" style="margin-top:0.25rem">Every account across the platform, with its memberships.</p>' +
        '<div class="table-wrap" style="margin-top:1rem"><table class="v-table"><thead><tr>' +
        "<th>Name</th><th>Email</th><th>Roles</th><th>Status</th><th>Last login</th><th class=\"text-right\">Actions</th>" +
        "</tr></thead><tbody>"
      );
      if (!users.length) {
        html += '<tr><td colspan="6" class="text-muted" style="text-align:center;padding:2rem">No accounts yet.</td></tr>';
      }
      users.forEach(function (u) {
        var roles = (u.memberships || []).map(function (m) { return m.role + "@" + m.organization_name; }).join(", ");
        if (u.is_superadmin) roles = roles ? roles + ", SUPERADMIN" : "SUPERADMIN";
        var hasOrg = (u.memberships || []).some(function (m) { return m.organization_id; });
        var actToggle = u.status === "ACTIVE" ? "SUSPENDED" : "ACTIVE";
        var actLabel = u.status === "ACTIVE" ? "Suspend" : "Activate";
        html += "<tr><td style=\"font-weight:500;color:var(--gray-700)\">" + esc(u.full_name) + "</td>" +
          '<td class="mono text-xs text-muted">' + esc(u.email) + "</td>" +
          '<td class="text-xs">' + esc(roles || "—") + "</td>" +
          "<td>" + Verifo.statusBadge(u.status) + "</td>" +
          '<td class="text-xs text-muted">' + fmtDT(u.last_login_at) + "</td>" +
          '<td class="text-right" style="white-space:nowrap">' +
          (u.is_superadmin
            ? '<button type="button" class="btn btn-ghost btn-sm" data-sa="' + esc(u.id) + '" data-sa-val="false">Revoke superadmin</button>'
            : '<button type="button" class="btn btn-ghost btn-sm" data-sa="' + esc(u.id) + '" data-sa-val="true">Make superadmin</button>') +
          (hasOrg && u.status === "ACTIVE"
            ? '<button type="button" class="btn btn-ghost btn-sm" data-uid="' + esc(u.id) + '" data-status="SUSPENDED" style="color:var(--red-700)">Suspend</button>'
            : '<button type="button" class="btn btn-ghost btn-sm" data-uid="' + esc(u.id) + '" data-status="ACTIVE">Activate</button>') +
          "</td></tr>";
      });
      html += "</tbody></table></div></div>";
      $("tab-users").innerHTML = html;

      $("tab-users").querySelectorAll("button[data-uid]").forEach(function (b) {
        b.addEventListener("click", function () {
          api("/superadmin/users/" + b.getAttribute("data-uid") + "/status", {
            method: "POST", body: { status: b.getAttribute("data-status") },
          }).then(function () { loadUsers(); });
        });
      });
      $("tab-users").querySelectorAll("button[data-sa]").forEach(function (b) {
        b.addEventListener("click", function () {
          api("/superadmin/users/" + b.getAttribute("data-sa") + "/superadmin", {
            method: "POST", body: { is_superadmin: b.getAttribute("data-sa-val") === "true" },
          }).then(function () { loadUsers(); });
        });
      });
    });
  }

  function msg(id, text, isErr) {
    $(id).innerHTML = '<p class="alert ' + (isErr ? "alert-error" : "alert-ok") + '">' + esc(text) + "</p>";
  }
})();