/**
 * eSupport SEO Platform • Admin Application Logic & Component Engine
 * Handles Admin SaaS Dashboard, Client Management, Live Audit Execution,
 * Full Technical Report Rendering, and Public Report Publishing.
 */

// Global setStatus fallback to ensure no ReferenceError: setStatus is not defined occurs
window.setStatus = function(msg) {
    const el = document.getElementById("statusline") || document.getElementById("auditStatusLine");
    if (el) el.textContent = msg;
    console.log("[eSupport Status]", msg);
};

const API_BASE = (window.location.port && window.location.port !== "8000" && (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"))
    ? `http://${window.location.hostname}:8000/api`
    : "/api";
const WHATSAPP_NUMBER = "94710690715";
const EMAIL_ADDRESS = "prasad@esupport.live";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[m]));
const fmt = n => Number(n || 0).toLocaleString();
const safe = n => Number(n || 0);

// Display only: the grade itself always comes from the backend engine payload (spec C.3 bands).
function getScoreColor(score) {
    if (score === null || score === undefined) return "#94A3B8";
    const s = safe(score);
    if (s >= 90) return "#10B981"; // Excellent
    if (s >= 80) return "#06B6D4"; // Very Good
    if (s >= 70) return "#2563EB"; // Good
    if (s >= 60) return "#F59E0B"; // Needs Improvement
    if (s >= 40) return "#F97316"; // Poor
    return "#EF4444";              // Critical
}

function getScoreLabel(score, grade) {
    if (grade) return grade;
    if (score === null || score === undefined) return "Not scored";
    const s = safe(score);
    if (s >= 90) return "Excellent";
    if (s >= 80) return "Very Good";
    if (s >= 70) return "Good";
    if (s >= 60) return "Needs Improvement";
    if (s >= 40) return "Poor";
    return "Critical";
}

let csrfToken = localStorage.getItem("esupport_csrf_token") || "";

async function jsonFetch(url, opts = {}) {
    const headers = {
        "X-Requested-With": "XMLHttpRequest",
        ...(opts.headers || {})
    };
    if (csrfToken) {
        headers["X-CSRF-Token"] = csrfToken;
    }
    const finalOpts = {
        credentials: "include",
        ...opts,
        headers
    };
    const r = await fetch(url, finalOpts);
    let d;
    try {
        d = await r.json();
    } catch {
        d = {};
    }
    if (!r.ok) {
        const err = new Error(d.detail || d.error || `HTTP error ${r.status}`);
        err.status = r.status;
        throw err;
    }
    return d;
}

class SEOAdminApp {
    constructor() {
        this.state = {
            authenticated: false,
            adminEmail: "prasad@esupport.live",
            adminName: "Admin",
            role: "SUPER_ADMIN",
            permissions: [],
            currentView: "dashboard",
            clients: [],
            leads: [],
            users: [],
            activityLogs: [],
            selectedClientId: null,
            selectedLeadId: null,
            currentJobId: null,
            pollTimer: null,
            pollDelay: 3500,
            currentAudit: null,
            currentTechTab: "overview",
            previewToken: null,
            editingClientId: null,
            inviteToken: null
        };
        this.init();
    }

    hasPermission(permission) {
        if (!permission) return true;
        if (this.state.role === "SUPER_ADMIN") return true;
        return Array.isArray(this.state.permissions) && this.state.permissions.includes(permission);
    }

    updateUserInterface() {
        // 1. Sidebar Profile & Role Badge
        if ($("sidebarAdminEmail")) $("sidebarAdminEmail").textContent = this.state.adminEmail;
        if ($("sidebarAdminName")) $("sidebarAdminName").textContent = this.state.adminName || "Admin";

        const badge = $("sidebarRoleBadge");
        if (badge) {
            const roleNorm = (this.state.role || "SUPER_ADMIN").toLowerCase().replace(/_/g, "-");
            badge.className = `role-badge role-${roleNorm}`;
            badge.textContent = (this.state.role || "SUPER_ADMIN").replace(/_/g, " ");
        }

        const avatar = $("sidebarAvatar");
        if (avatar) {
            const initials = (this.state.adminName || this.state.adminEmail || "ES").substring(0, 2).toUpperCase();
            avatar.textContent = initials;
        }

        // 2. Dynamic Sidebar Module Filtering (RBAC)
        document.querySelectorAll(".nav-item[data-permission]").forEach(item => {
            const perm = item.dataset.permission;
            item.style.display = this.hasPermission(perm) ? "flex" : "none";
        });

        document.querySelectorAll(".nav-section-title[data-permission]").forEach(sec => {
            const perm = sec.dataset.permission;
            sec.style.display = this.hasPermission(perm) ? "block" : "none";
        });

        // 3. Header Action Buttons
        const addClientBtn = document.querySelector('button[onclick*="openClientModal"]');
        if (addClientBtn) {
            addClientBtn.style.display = this.hasPermission("clients.create") ? "inline-flex" : "none";
        }
        const runAuditBtn = document.querySelector('button[onclick*="auditUrlInput"]');
        if (runAuditBtn) {
            runAuditBtn.style.display = this.hasPermission("audits.run") ? "inline-flex" : "none";
        }
    }

    async init() {
        this.setupPopState();

        // 1. Check if single-use invitation token is present in URL
        const urlParams = new URLSearchParams(window.location.search);
        const inviteToken = urlParams.get("invite_token");
        if (inviteToken) {
            this.state.inviteToken = inviteToken;
            await this.verifyInvitation(inviteToken);
            return;
        }

        // 2. Fetch authenticated user profile & permissions
        try {
            const me = await jsonFetch(`${API_BASE}/admin/me`);
            this.state.authenticated = true;
            this.state.adminEmail = me.email || "prasad@esupport.live";
            this.state.adminName = me.name || "Admin";
            this.state.role = me.role || "SUPER_ADMIN";
            this.state.permissions = me.permissions || [];
            this.updateUserInterface();

            if ($("adminLoginScreen")) $("adminLoginScreen").style.display = "none";
            if ($("acceptInviteScreen")) $("acceptInviteScreen").style.display = "none";
            if ($("appLayout")) $("appLayout").style.display = "flex";
        } catch (err) {
            this.state.authenticated = false;
            if ($("adminLoginScreen")) $("adminLoginScreen").style.display = "flex";
            if ($("acceptInviteScreen")) $("acceptInviteScreen").style.display = "none";
            if ($("appLayout")) $("appLayout").style.display = "none";
            return;
        }

        this.checkHealth();
        const initialView = urlParams.get("view") || "dashboard";
        this.navigate(initialView, false);
    }

    async verifyInvitation(token) {
        if ($("adminLoginScreen")) $("adminLoginScreen").style.display = "none";
        if ($("appLayout")) $("appLayout").style.display = "none";
        const screen = $("acceptInviteScreen");
        if (screen) screen.style.display = "flex";

        try {
            const data = await jsonFetch(`${API_BASE}/auth/invitations/verify?token=${encodeURIComponent(token)}`);
            if ($("acceptInviteEmailText")) $("acceptInviteEmailText").textContent = data.email;
            if ($("acceptInviteNameInput")) $("acceptInviteNameInput").value = data.name || "";
            const roleBadge = $("acceptInviteRoleBadge");
            if (roleBadge) {
                const roleNorm = (data.role || "SALES").toLowerCase().replace(/_/g, "-");
                roleBadge.className = `role-badge role-${roleNorm}`;
                roleBadge.textContent = data.role.replace(/_/g, " ");
            }
        } catch (err) {
            const alertBox = $("acceptInviteAlertBox");
            if (alertBox) {
                alertBox.style.display = "block";
                alertBox.className = "login-alert-danger";
                alertBox.textContent = "Invalid or expired invitation token: " + (err.message || "Please contact your Super Admin.");
            }
            if ($("acceptInviteSubmitBtn")) $("acceptInviteSubmitBtn").disabled = true;
        }
    }

    async handleAcceptInvite(e) {
        if (e) e.preventDefault();
        const token = this.state.inviteToken;
        const name = $("acceptInviteNameInput").value.trim();
        const password = $("acceptInvitePasswordInput").value;
        const confirm = $("acceptInviteConfirmInput").value;
        const alertBox = $("acceptInviteAlertBox");
        const submitBtn = $("acceptInviteSubmitBtn");

        if (password !== confirm) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = "Passwords do not match.";
            return;
        }

        alertBox.style.display = "none";
        submitBtn.disabled = true;
        submitBtn.innerHTML = "<span>Activating Account...</span>";

        try {
            const resp = await jsonFetch(`${API_BASE}/auth/invitations/accept`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ token, name, password })
            });

            if (resp.csrf_token) {
                csrfToken = resp.csrf_token;
                localStorage.setItem("esupport_csrf_token", csrfToken);
            }
            alert("Account successfully activated! Welcome to eSupport SEO.");
            window.location.href = "/admin";
        } catch (err) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = err.message || "Failed to activate invitation.";
            submitBtn.disabled = false;
            submitBtn.innerHTML = "<span>Activate Account &amp; Sign In</span>";
        }
    }

    async handleLogin(e) {
        if (e) e.preventDefault();
        const email = $("loginEmail").value.trim();
        const password = $("loginPassword").value;
        const alertBox = $("loginAlertBox");
        const submitBtn = $("loginSubmitBtn");

        alertBox.style.display = "none";
        alertBox.className = "";
        submitBtn.disabled = true;
        submitBtn.innerHTML = "<span>Signing in...</span>";

        try {
            const resp = await jsonFetch(`${API_BASE}/admin/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password })
            });
            if (resp.csrf_token) {
                csrfToken = resp.csrf_token;
                localStorage.setItem("esupport_csrf_token", csrfToken);
            }
            this.state.authenticated = true;
            this.state.adminEmail = resp.email || email;
            this.state.adminName = resp.name || "Admin";
            this.state.role = resp.role || "SUPER_ADMIN";
            this.state.permissions = resp.permissions || [];
            this.updateUserInterface();

            if ($("adminLoginScreen")) $("adminLoginScreen").style.display = "none";
            if ($("appLayout")) $("appLayout").style.display = "flex";

            this.checkHealth();
            this.navigate("dashboard", false);
        } catch (err) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = err.message || "Failed to authenticate. Please check your credentials.";
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = "<span>Sign In to Admin Portal</span>";
        }
    }

    async handleLogout() {
        if (!confirm("Are you sure you want to sign out of the Admin Portal?")) return;
        try {
            await jsonFetch(`${API_BASE}/admin/logout`, { method: "POST" });
        } catch (e) {
            console.warn("Logout error:", e);
        }
        csrfToken = "";
        localStorage.removeItem("esupport_csrf_token");
        this.state.authenticated = false;
        if ($("adminLoginScreen")) $("adminLoginScreen").style.display = "flex";
        if ($("appLayout")) $("appLayout").style.display = "none";
    }

    setupPopState() {
        window.onpopstate = () => {
            const params = new URLSearchParams(window.location.search);
            const view = params.get("view") || "dashboard";
            this.navigate(view, false);
        };
    }

    navigate(view, push = true) {
        // RBAC Access Guard
        const viewPermissions = {
            dashboard: "dashboard.view",
            clients: "clients.view",
            client_detail: "clients.view",
            audits: "audits.view",
            leads: "leads.view",
            reports: "reports.view",
            technical_report: "audits.view",
            team_users: "admin_users.view",
            activity_logs: "activity_logs.view",
            profile: null,
            source_audit: "audits.run",
            technology_detector: "tech_detector.view"
        };

        const requiredPerm = viewPermissions[view];
        if (requiredPerm && !this.hasPermission(requiredPerm)) {
            // Permission Denied - Show Access Restricted View
            this.state.currentView = "access_restricted";
            document.querySelectorAll(".nav-item").forEach(item => item.classList.remove("active"));
            document.querySelectorAll(".admin-view").forEach(v => v.classList.remove("active"));
            if ($("viewAccessRestricted")) $("viewAccessRestricted").classList.add("active");
            $("pageTitle").textContent = "Access Restricted";
            $("pageBreadcrumb").textContent = "Security • Insufficient Permissions";
            return;
        }

        this.state.currentView = view;
        if (push) {
            try {
                const url = new URL(window.location.href);
                url.searchParams.set("view", view);
                window.history.pushState({}, "", url.toString());
            } catch (err) {
                console.warn("[eSupport] Failed to push state:", err);
            }
        }

        // Close mobile sidebar and backdrop on navigation
        const sb = $("adminSidebar");
        const bd = $("sidebarBackdrop");
        if (sb) sb.classList.remove("open");
        if (bd) bd.classList.remove("active");

        // Update active class on sidebar items
        document.querySelectorAll(".nav-item").forEach(item => {
            item.classList.toggle("active", item.dataset.view === view);
        });

        // Hide all views and show target
        document.querySelectorAll(".admin-view").forEach(v => v.classList.remove("active"));

        const viewMap = {
            dashboard: { id: "viewDashboard", title: "Dashboard", breadcrumb: "Overview • SEO Performance Management" },
            clients: { id: "viewClients", title: "Client Management", breadcrumb: "Portal • Clients & Websites" },
            client_detail: { id: "viewClientDetail", title: "Client Details", breadcrumb: "Clients • Performance Profile" },
            audits: { id: "viewAudits", title: "Audit History", breadcrumb: "Analysis • Historical Inspections" },
            leads: { id: "viewLeads", title: "SEO Leads", breadcrumb: "Leads • Public SEO Check Requests" },
            reports: { id: "viewReports", title: "Public Report Manager", breadcrumb: "Sharing • Client Access Tokens" },
            technical_report: { id: "viewTechnicalReport", title: "Technical Audit Inspection", breadcrumb: "Audit • Deep Technical Findings" },
            team_users: { id: "viewTeamUsers", title: "Team Members", breadcrumb: "Administration • Role & Access Control" },
            activity_logs: { id: "viewActivityLogs", title: "Activity Logs", breadcrumb: "Administration • Immutable Audit Trail" },
            profile: { id: "viewProfile", title: "My Profile", breadcrumb: "Account • Credentials & Settings" },
            source_audit: { id: "viewSourceAudit", title: "Source Code ZIP Analysis", breadcrumb: "Static Code • Framework Audit" },
            technology_detector: { id: "viewTechDetector", title: "Website Technology Detector", breadcrumb: "Analysis • CMS, Framework & Platform Detection" }
        };

        const target = viewMap[view] || viewMap.dashboard;
        const el = $(target.id);
        if (el) el.classList.add("active");

        $("pageTitle").textContent = target.title;
        $("pageBreadcrumb").textContent = target.breadcrumb;

        // View-specific data fetching
        if (view === "dashboard") {
            this.loadDashboardStats();
            this.loadClients();
        }
        else if (view === "clients") this.loadClients();
        else if (view === "audits") this.loadAudits();
        else if (view === "leads") this.loadLeads();
        else if (view === "reports") this.loadReports();
        else if (view === "technical_report") this.renderTechnicalReport();
        else if (view === "team_users") this.loadTeamUsers();
        else if (view === "activity_logs") this.loadActivityLogs();
        else if (view === "profile") this.loadProfile();
        else if (view === "technology_detector") {
            if (window.techDetector) {
                window.techDetector.initView();
            } else {
                setTimeout(() => {
                    if (window.techDetector) window.techDetector.initView();
                }, 100);
            }
        }
    }

    toggleSidebar() {
        const sb = $("adminSidebar");
        const bd = $("sidebarBackdrop");
        if (sb) sb.classList.toggle("open");
        if (bd) bd.classList.toggle("active");
    }

    async checkHealth() {
        try {
            const d = await jsonFetch(`${API_BASE}/health`);
            $("healthBadge").innerHTML = `<span style="color:var(--success)">●</span> API Ready • v${esc(d.version || "10.4.0")}`;
        } catch {
            $("healthBadge").innerHTML = `<span style="color:var(--danger)">●</span> Backend Offline`;
        }
    }

    /* -------------------------------------------------------------
       DASHBOARD & KPI STATS
    -------------------------------------------------------------- */
    async loadDashboardStats() {
        // 1. Fast-path: Instant zero-delay cache render
        try {
            const cached = localStorage.getItem("esupport_dashboard_stats_cache");
            if (cached) {
                const parsed = JSON.parse(cached);
                this.renderDashboardStats(parsed);
            }
        } catch (_) {}

        // 2. Fetch fresh stats in background and update smoothly
        try {
            const stats = await jsonFetch(`${API_BASE}/dashboard/stats`);
            this.renderDashboardStats(stats);
            try {
                localStorage.setItem("esupport_dashboard_stats_cache", JSON.stringify(stats));
            } catch (_) {}
        } catch (e) {
            console.error("Dashboard stats error:", e);
        }
    }

    renderDashboardStats(stats) {
        if (!stats) return;
        if ($("kpiClients")) $("kpiClients").textContent = fmt(stats.total_clients);
        if ($("kpiAudits")) $("kpiAudits").textContent = fmt(stats.total_audits);
        if ($("kpiAvgScore")) $("kpiAvgScore").textContent = `${Math.round(stats.avg_score || 0)}%`;
        if ($("kpiPublished")) $("kpiPublished").textContent = fmt(stats.reports_published);
        if ($("kpiLeads")) $("kpiLeads").textContent = fmt(stats.leads_new);
        if ($("kpiLeadsLabel")) $("kpiLeadsLabel").textContent = `${fmt(stats.leads_new)} New (${fmt(stats.leads_total)} total)`;
        if ($("kpiPublicChecks")) $("kpiPublicChecks").textContent = fmt(stats.public_scans_total || stats.total_audits || 0);
        if ($("kpiPublicChecksSub")) $("kpiPublicChecksSub").textContent = `Checks on /seo-check page`;
        if ($("kpiAuditsSub")) $("kpiAuditsSub").textContent = `Across ${fmt(stats.websites_audited || stats.total_websites || 1)} unique websites`;
        if ($("kpiScoreSub")) $("kpiScoreSub").textContent = `${fmt(stats.excellent_websites)} Excellent • ${fmt(stats.needs_improvement)} Needs Attention`;

        if ($("kpiExcellent")) $("kpiExcellent").textContent = fmt(stats.excellent_websites);
        if ($("kpiNeedsImp")) $("kpiNeedsImp").textContent = fmt(stats.needs_improvement);
        if ($("kpiWebsites")) $("kpiWebsites").textContent = fmt(stats.websites_audited);
        if ($("kpiPages")) $("kpiPages").textContent = fmt(stats.pages_crawled);
        if ($("kpiLinks")) $("kpiLinks").textContent = fmt(safe(stats.links_checked) + safe(stats.resources_checked));
        if ($("kpiBroken")) $("kpiBroken").textContent = fmt(stats.broken_links);
        if ($("kpiCritical")) $("kpiCritical").textContent = fmt(stats.open_critical_issues);

        this.renderDashboardInsights(stats);

        // Populate recent audits table in dashboard
        const recentAuditsBody = $("dashRecentAuditsBody");
        if (recentAuditsBody) {
            if (stats.recent_audits && stats.recent_audits.length) {
                recentAuditsBody.innerHTML = stats.recent_audits.map(a => {
                    const score = safe(a.score);
                    const color = getScoreColor(score);
                    const when = a.created_at ? new Date(a.created_at + (a.created_at.endsWith("Z") ? "" : "Z")).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—";
                    return `
                        <tr>
                            <td><b>${esc(a.target_url)}</b></td>
                            <td><span class="pill" style="background:${color}20; color:${color}; border:1px solid ${color}40;">${score.toFixed(0)}%</span></td>
                            <td title="${a.elapsed_seconds != null ? "Crawled in " + esc(a.elapsed_seconds) + " s" : ""}">${fmt(a.pages_crawled)}</td>
                            <td style="color:${a.critical ? "var(--danger)" : "inherit"}; font-weight:${a.critical ? 700 : 400};">${fmt(a.critical)}</td>
                            <td style="color:${a.warnings ? "var(--warning)" : "inherit"};">${fmt(a.warnings)}</td>
                            <td>${esc(a.client_name)}</td>
                            <td style="font-size:12px; color:var(--text-muted); white-space:nowrap;">${esc(when)}</td>
                            <td>
                                <button class="btn btn-secondary btn-sm" onclick="app.loadSavedAudit(${a.id})">Inspect</button>
                            </td>
                        </tr>
                    `;
                }).join("");
            } else {
                recentAuditsBody.innerHTML = `<tr><td colspan="8" class="empty-state">No audits completed yet.</td></tr>`;
            }
        }
    }

    renderDashboardInsights(stats) {
        const cats = stats.category_averages || [];
        $("dashCategoryHealth").innerHTML = cats.length ? cats.map(c => {
            const color = getScoreColor(c.average);
            return `
                <div style="margin-bottom:10px;">
                    <div style="display:flex; justify-content:space-between; font-size:13px; font-weight:600; margin-bottom:4px;">
                        <span>${esc(c.name)}</span>
                        <span style="color:${color};">${esc(c.average)}% <small style="color:var(--text-muted); font-weight:400;">(${fmt(c.websites)} site${c.websites === 1 ? "" : "s"})</small></span>
                    </div>
                    <div style="height:6px; background:#E2E8F0; border-radius:999px; overflow:hidden;">
                        <div style="height:100%; width:${Math.min(100, safe(c.average))}%; background:${color};"></div>
                    </div>
                </div>`;
        }).join("") : '<div class="empty-state">Run an audit to see category health.</div>';

        const issues = stats.top_issues || [];
        const maxSites = Math.max(1, safe(stats.websites_audited));
        $("dashTopIssues").innerHTML = issues.length ? issues.map(i => `
            <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; padding:8px 0; border-bottom:1px solid var(--border); font-size:13px;">
                <span>${esc(i.title)}</span>
                <span class="pill pill-warning" title="${fmt(i.websites)} of ${fmt(maxSites)} websites" style="white-space:nowrap;">${fmt(i.websites)} / ${fmt(maxSites)} sites</span>
            </div>`).join("") : '<div class="empty-state">No critical issues or warnings found.</div>';

        const ds = stats.data_sources || {};
        const source = (label, ok, hint) => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; font-size:13px;">
                <span>${esc(label)}</span>
                <span title="${esc(hint)}" style="font-weight:600; color:${ok ? "var(--success, #10B981)" : "var(--text-muted)"};">${ok ? "● Connected" : "○ Not set up"}</span>
            </div>`;
        $("dashDataSources").innerHTML = `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:14px;">
                <div style="background:#F8FAFC; border:1px solid var(--border); border-radius:10px; padding:10px; text-align:center;">
                    <b style="font-size:22px; color:var(--primary);">${fmt(stats.audits_last_7_days)}</b><div style="font-size:12px; color:var(--text-muted);">Audits, last 7 days</div>
                </div>
                <div style="background:#F8FAFC; border:1px solid var(--border); border-radius:10px; padding:10px; text-align:center;">
                    <b style="font-size:22px; color:var(--primary);">${fmt(stats.audits_last_30_days)}</b><div style="font-size:12px; color:var(--text-muted);">Audits, last 30 days</div>
                </div>
            </div>
            ${source(ds.pagespeed_mode === "local_lighthouse" ? "Google Lighthouse (local, no key)" : "Google PageSpeed / Core Web Vitals", ds.pagespeed, "Set PAGESPEED_API_KEY in .env for real-user Core Web Vitals")}
            ${source("Google Search Console", ds.search_console, "Set GSC_SERVICE_ACCOUNT_FILE in .env")}
            ${source("Open PageRank (backlinks)", ds.openpagerank, "Set OPENPAGERANK_API_KEY in .env")}
            ${source(`Ollama AI (${ds.ollama_model || "model"})`, ds.ollama, "Run: ollama pull " + (ds.ollama_model || "gemma3"))}
        `;
    }

    /* -------------------------------------------------------------
       CLIENT MANAGEMENT
    -------------------------------------------------------------- */
    async loadClients() {
        if (this.state.clients && this.state.clients.length) {
            this.renderClientsTable(this.state.clients);
            this.renderRecentClientsWidget(this.state.clients);
        }
        try {
            this.state.clients = await jsonFetch(`${API_BASE}/clients`);
            this.renderClientsTable(this.state.clients);
            this.renderRecentClientsWidget(this.state.clients);
            this.populateClientSelects();
        } catch (e) {
            console.error("Load clients error:", e);
        }
    }

    renderRecentClientsWidget(clients) {
        const dashClientsBody = $("dashRecentClientsBody");
        if (!dashClientsBody || !clients) return;
        if (clients.length) {
            dashClientsBody.innerHTML = clients.slice(0, 5).map(c => {
                const score = c.latest_score !== null ? safe(c.latest_score) : null;
                const scoreHtml = score !== null 
                    ? `<span class="pill" style="background:${getScoreColor(score)}20; color:${getScoreColor(score)}; border:1px solid ${getScoreColor(score)}40;">${score.toFixed(0)}%</span>`
                    : '<span class="pill pill-disabled">No Audit</span>';
                return `
                    <tr>
                        <td><b>${esc(c.name)}</b></td>
                        <td><span style="color:var(--text-muted); font-size:12px;">${esc(c.target_url || "N/A")}</span></td>
                        <td>${scoreHtml}</td>
                        <td><button class="btn btn-secondary btn-sm" onclick="app.viewClientDetail(${c.id})">View</button></td>
                    </tr>
                `;
            }).join("");
        } else {
            dashClientsBody.innerHTML = `<tr><td colspan="4" class="empty-state">No clients added yet.</td></tr>`;
        }
    }

    renderClientsTable(clients) {
        const tbody = $("clientsTableBody");
        if (!tbody) return;

        if (!clients || !clients.length) {
            tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No clients found. Click "+ Add New Client" to create one.</td></tr>`;
            return;
        }

        tbody.innerHTML = clients.map(c => {
            const score = c.latest_score !== null ? safe(c.latest_score) : null;
            const scorePill = score !== null
                ? `<span class="pill" style="background:${getScoreColor(score)}20; color:${getScoreColor(score)}; border:1px solid ${getScoreColor(score)}40;">${score.toFixed(0)}% - ${getScoreLabel(score)}</span>`
                : `<span class="pill pill-disabled">Unchecked</span>`;

            const auditDate = c.latest_audit_date 
                ? new Date(c.latest_audit_date).toLocaleDateString()
                : "None";

            const reportBadge = c.latest_report_token
                ? `<span class="pill pill-success">${esc(c.latest_report_status || "PUBLISHED")}</span>`
                : `<span class="pill pill-disabled">None</span>`;

            return `
                <tr>
                    <td><b>${esc(c.name)}</b></td>
                    <td>${esc(c.company || "-")}</td>
                    <td><a href="${esc(c.target_url)}" target="_blank" style="color:var(--primary); font-weight:500;">${esc(c.target_url || "No website")}</a></td>
                    <td>
                        <div style="font-size:12px; color:var(--text-muted);">
                            ${c.email ? `<div>${esc(c.email)}</div>` : ""}
                            ${c.phone ? `<div>${esc(c.phone)}</div>` : ""}
                        </div>
                    </td>
                    <td>${scorePill}</td>
                    <td><span style="font-size:12px; color:var(--text-muted);">${auditDate}</span></td>
                    <td>${reportBadge}</td>
                    <td>
                        <div style="display:flex; gap:6px;">
                            <button class="btn btn-secondary btn-sm" onclick="app.viewClientDetail(${c.id})">Details</button>
                            ${this.hasPermission("audits.run") ? `
                                <button class="btn btn-primary btn-sm" onclick="app.auditClientPrompt(${c.id}, '${esc(c.target_url)}')">Audit</button>
                            ` : ''}
                            ${this.hasPermission("clients.delete") ? `
                                <button class="btn btn-danger btn-sm" onclick="app.deleteClient(${c.id})">Delete</button>
                            ` : ''}
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    populateClientSelects() {
        const sel = $("auditClientSelect");
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = `<option value="">-- Assign to Client (Optional) --</option>` +
            this.state.clients.map(c => `<option value="${c.id}">${esc(c.name)} (${esc(c.company || c.target_url || "Client")})</option>`).join("");
        sel.value = current;
    }

    filterClients() {
        const q = ($("clientSearchInput")?.value || "").toLowerCase().trim();
        if (!q) {
            this.renderClientsTable(this.state.clients);
            return;
        }
        const filtered = this.state.clients.filter(c => 
            (c.name || "").toLowerCase().includes(q) ||
            (c.company || "").toLowerCase().includes(q) ||
            (c.target_url || "").toLowerCase().includes(q) ||
            (c.email || "").toLowerCase().includes(q)
        );
        this.renderClientsTable(filtered);
    }

    openClientModal(clientId = null) {
        this.state.editingClientId = clientId;
        if (clientId) {
            const client = this.state.clients.find(c => c.id === clientId);
            $("clientModalTitle").textContent = "Edit Client";
            $("modalClientName").value = client?.name || "";
            $("modalCompany").value = client?.company || "";
            $("modalTargetUrl").value = client?.target_url || "";
            $("modalEmail").value = client?.email || "";
            $("modalPhone").value = client?.phone || "";
        } else {
            $("clientModalTitle").textContent = "Add New Client";
            $("modalClientName").value = "";
            $("modalCompany").value = "";
            $("modalTargetUrl").value = "";
            $("modalEmail").value = "";
            $("modalPhone").value = "";
        }
        $("clientModal").classList.remove("hidden");
    }

    closeClientModal() {
        $("clientModal").classList.add("hidden");
        this.state.editingClientId = null;
    }

    async saveClient() {
        const name = $("modalClientName").value.trim();
        if (!name) return alert("Client name is required.");

        const payload = {
            name: name,
            company: $("modalCompany").value.trim(),
            target_url: $("modalTargetUrl").value.trim(),
            email: $("modalEmail").value.trim(),
            phone: $("modalPhone").value.trim()
        };

        try {
            if (this.state.editingClientId) {
                await jsonFetch(`${API_BASE}/clients/${this.state.editingClientId}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
            } else {
                await jsonFetch(`${API_BASE}/clients`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
            }
            this.closeClientModal();
            await this.loadClients();
            await this.loadDashboardStats();
        } catch (e) {
            alert("Error saving client: " + e.message);
        }
    }

    async deleteClient(id) {
        if (!confirm("Are you sure you want to delete this client and all associated audits/reports?")) return;
        try {
            await jsonFetch(`${API_BASE}/clients/${id}`, { method: "DELETE" });
            await this.loadClients();
            await this.loadDashboardStats();
        } catch (e) {
            alert("Failed to delete client: " + e.message);
        }
    }

    async viewClientDetail(id) {
        this.state.selectedClientId = id;
        try {
            const client = await jsonFetch(`${API_BASE}/clients/${id}`);
            $("cdName").textContent = client.name;
            $("cdCompany").textContent = client.company || "Not specified";
            $("cdEmail").textContent = client.email || "Not specified";
            $("cdPhone").textContent = client.phone || "Not specified";
            
            const urlEl = $("cdUrl");
            urlEl.textContent = client.target_url || "No website";
            urlEl.href = client.target_url || "#";

            // Audits table
            const auditsBody = $("cdAuditsBody");
            if (client.audits && client.audits.length) {
                auditsBody.innerHTML = client.audits.map(a => {
                    const score = safe(a.score);
                    const color = getScoreColor(score);
                    const d = a.created_at ? new Date(a.created_at).toLocaleDateString() : "-";
                    return `
                        <tr>
                            <td>${d}</td>
                            <td><span class="pill" style="background:${color}20; color:${color}; border:1px solid ${color}40;">${score.toFixed(0)}%</span></td>
                            <td><span class="pill pill-success">${esc(a.status)}</span></td>
                            <td>
                                <button class="btn btn-secondary btn-sm" onclick="app.loadSavedAudit(${a.id})">Review Report</button>
                            </td>
                        </tr>
                    `;
                }).join("");
            } else {
                auditsBody.innerHTML = `<tr><td colspan="4" class="empty-state">No audits run for this client yet.</td></tr>`;
            }

            // Reports table
            const reportsBody = $("cdReportsBody");
            if (client.reports && client.reports.length) {
                reportsBody.innerHTML = client.reports.map(r => {
                    const d = r.created_at ? new Date(r.created_at).toLocaleDateString() : "-";
                    const isPub = r.status === "PUBLISHED";
                    return `
                        <tr>
                            <td>${d}</td>
                            <td><b>${safe(r.score).toFixed(0)}%</b></td>
                            <td>
                                <span class="pill ${isPub ? 'pill-success' : 'pill-disabled'}">${esc(r.status)}</span>
                            </td>
                            <td>
                                <div style="display:flex; gap:6px;">
                                    <button class="btn btn-secondary btn-sm" onclick="app.openPreview('${r.token}')">Preview</button>
                                    <button class="btn btn-secondary btn-sm" onclick="app.copyReportLink('${r.token}')">Copy Link</button>
                                    <button class="btn btn-secondary btn-sm" onclick="window.open('/report/${r.token}', '_blank')">Open Report</button>
                                    <button class="btn btn-sm ${isPub ? 'btn-danger' : 'btn-success'}" onclick="app.toggleReportStatus(${r.id}, '${r.status}')">
                                        ${isPub ? 'Disable' : 'Publish'}
                                    </button>
                                </div>
                            </td>
                        </tr>
                    `;
                }).join("");
            } else {
                reportsBody.innerHTML = `<tr><td colspan="4" class="empty-state">No public reports generated for this client yet.</td></tr>`;
            }

            this.navigate("client_detail");
        } catch (e) {
            alert("Error loading client: " + e.message);
        }
    }

    auditClientPrompt(clientId, targetUrl) {
        $("auditUrlInput").value = targetUrl || "";
        $("auditClientSelect").value = String(clientId);
        this.navigate("dashboard");
        $("auditUrlInput").focus();
    }

    auditCurrentClient() {
        const client = this.state.clients.find(c => c.id === this.state.selectedClientId);
        if (client) {
            this.auditClientPrompt(client.id, client.target_url);
        }
    }

    async generateReportForClient() {
        const client = this.state.clients.find(c => c.id === this.state.selectedClientId);
        if (!client || !client.latest_audit_id) {
            alert("This client does not have any completed audits yet. Please run an audit first.");
            return;
        }
        await this.generateReport(client.latest_audit_id, client.id);
        await this.viewClientDetail(client.id);
    }

    /* -------------------------------------------------------------
       AUDIT EXECUTION & POLLING
    -------------------------------------------------------------- */
    async runPreflight() {
        const url = $("auditUrlInput").value.trim();
        if (!url) return alert("Please enter a website URL.");

        const btn = $("preflightBtn");
        btn.disabled = true;
        btn.textContent = "Testing...";
        const box = $("preflightBox");
        box.classList.remove("hidden");
        box.innerHTML = `<div style="font-size:13px; color:var(--text-muted);">Sending preflight probe to target...</div>`;

        try {
            const data = await jsonFetch(`${API_BASE}/preflight`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url, max_pages: 5000 })
            });

            box.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <b>Preflight Check: <span class="${data.http_ok ? 'text-success' : 'text-danger'}">${data.http_ok ? 'Target Reachable' : 'Connection Warning'}</span></b>
                    <span style="font-size:12px; color:var(--text-muted);">${fmt(data.response_ms)} ms response</span>
                </div>
                <div class="grid" style="grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; font-size:12px;">
                    <div>HTTP Status: <b>${data.http_status}</b></div>
                    <div>robots.txt: <b>${data.robots?.found ? 'Found' : 'Missing'}</b></div>
                    <div>Sitemaps Found: <b>${(data.sitemaps || []).length}</b></div>
                    <div>Payload: <b>${fmt(data.content_bytes)} bytes</b></div>
                </div>
            `;
        } catch (e) {
            box.innerHTML = `<div class="text-danger">Preflight failed: ${esc(e.message)}</div>`;
        } finally {
            btn.disabled = false;
            btn.textContent = "Test Live Site";
        }
    }

    async startAudit() {
        const url = $("auditUrlInput").value.trim();
        if (!url) return alert("Please enter a website URL to audit.");

        this.stopPolling();
        $("runAuditBtn").disabled = true;
        $("runAuditBtn").textContent = "Auditing...";
        $("cancelAuditBtn").classList.remove("hidden");
        $("auditProgressBar").style.width = "5%";
        $("auditStatusLine").textContent = "Initializing crawler and DNS probes...";

        const payload = {
            url,
            max_pages: 5000,
            respect_robots: $("optRobots").checked,
            check_links: $("optLinks").checked,
            check_resources: $("optResources").checked,
            check_external_links: false,
            crawl_delay_ms: 0,
            run_ai: $("optAi").checked,
            use_pagespeed: $("optPagespeed").checked,
            use_search_console: $("optGsc").checked,
            use_dataforseo: $("optDataforseo").checked,
            crawl_mode: $("crawlModeSelect").value,
            render_max_pages: 40,
            follow_subdomains: $("optSubdomains").checked,
            query_policy: "safe",
            max_depth: 50
        };

        try {
            const data = await jsonFetch(`${API_BASE}/audit/start`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            this.state.currentJobId = data.job_id;
            this.state.pollDelay = 3500;
            $("auditStatusLine").textContent = "Audit queued on crawler engine...";
            this.scheduleNextPoll(100);
        } catch (e) {
            alert("Audit start failed: " + e.message);
            this.resetAuditUI();
        }
    }

    scheduleNextPoll(delayMs = 3500) {
        this.stopPolling();
        this.state.pollTimer = setTimeout(() => this.pollAudit(), delayMs);
    }

    async pollAudit() {
        if (!this.state.currentJobId) return;

        try {
            const data = await jsonFetch(`${API_BASE}/audit/status/${this.state.currentJobId}`);
            this.state.pollDelay = 3500; // Reset delay on successful response
            const p = data.progress || {};

            let pct = 10;
            if (p.phase === "preflight") pct = 15;
            else if (p.phase === "crawl") pct = Math.min(75, 20 + Math.min(55, ((p.pages || 0) / Math.max(1, (p.pages || 0) + (p.queued || 0))) * 55));
            else if (p.phase === "links") pct = 80;
            else if (p.phase === "resources") pct = 90;
            else if (p.phase === "completed") pct = 100;

            $("auditProgressBar").style.width = `${pct}%`;
            $("auditStatusLine").textContent = p.message || `Phase: ${p.phase || "working"}...`;
            $("auditTelemetry").textContent = `Pages: ${fmt(p.pages || 0)} | Links: ${fmt(p.links_checked || 0)} | Issues: ${fmt(p.issues || 0)}`;

            if (data.state === "completed") {
                this.stopPolling();
                this.resetAuditUI();
                $("auditStatusLine").textContent = "Audit completed successfully! Saving results...";
                await this.handleAuditSuccess(data.result);
            } else if (data.state === "failed" || data.state === "cancelled") {
                this.stopPolling();
                this.resetAuditUI();
                $("auditStatusLine").textContent = `Audit ${data.state}: ${data.error || "Stopped."}`;
            } else {
                this.scheduleNextPoll(this.state.pollDelay);
            }
        } catch (e) {
            console.error("Poll error:", e);
            if (e.status === 429) {
                // Exponential backoff on rate limiting
                this.state.pollDelay = Math.min(15000, (this.state.pollDelay || 3500) * 1.5);
                $("auditStatusLine").textContent = `Rate limited (429). Backing off for ${(this.state.pollDelay / 1000).toFixed(1)}s...`;
                this.scheduleNextPoll(this.state.pollDelay);
            } else if (this.state.currentJobId) {
                this.scheduleNextPoll(5000);
            }
        }
    }

    async cancelAudit() {
        if (!this.state.currentJobId) return;
        try {
            await jsonFetch(`${API_BASE}/audit/cancel/${this.state.currentJobId}`, { method: "POST" });
            $("auditStatusLine").textContent = "Cancelling audit...";
        } catch (e) {
            alert("Cancel failed: " + e.message);
        }
    }

    stopPolling() {
        if (this.state.pollTimer) {
            clearTimeout(this.state.pollTimer);
            this.state.pollTimer = null;
        }
    }

    resetAuditUI() {
        $("runAuditBtn").disabled = false;
        $("runAuditBtn").textContent = "Run Full Audit";
        $("cancelAuditBtn").classList.add("hidden");
    }

    async handleAuditSuccess(auditResult) {
        this.state.currentAudit = auditResult;
        const clientIdStr = $("auditClientSelect").value;
        const clientId = clientIdStr ? parseInt(clientIdStr) : null;

        try {
            // Save audit to database
            const saved = await jsonFetch(`${API_BASE}/audits/save`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    client_id: clientId,
                    audit_result: auditResult,
                    score: auditResult.score,
                    target_url: auditResult.target || auditResult.url,
                    job_id: this.state.currentJobId
                })
            });

            this.state.currentAudit.db_audit_id = saved.audit_id;
            await this.loadDashboardStats();
            await this.loadClients();

            // Navigate to Technical Report view
            this.renderTechnicalReport();
            this.navigate("technical_report");
        } catch (e) {
            console.error("Failed to save audit:", e);
            this.renderTechnicalReport();
            this.navigate("technical_report");
        }
    }

    /* -------------------------------------------------------------
       AUDIT HISTORY & REPORT LOADING
    -------------------------------------------------------------- */
    async loadAudits() {
        if (this.state.audits && this.state.audits.length) {
            this.renderAuditsTable(this.state.audits);
        }
        try {
            this.state.audits = await jsonFetch(`${API_BASE}/audits`);
            this.renderAuditsTable(this.state.audits);
        } catch (e) {
            console.error("Load audits error:", e);
        }
    }

    renderAuditsTable(audits) {
        const tbody = $("auditsTableBody");
        if (!tbody) return;

        if (!audits || !audits.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No audits in history.</td></tr>`;
            return;
        }

        tbody.innerHTML = audits.map(a => {
            const score = safe(a.score);
            const color = getScoreColor(score);
            const d = a.created_at ? new Date(a.created_at).toLocaleDateString() : "-";
            const repBadge = a.has_report
                ? `<span class="pill pill-success">${esc(a.report_status || "PUBLISHED")}</span>`
                : `<span class="pill pill-disabled">None</span>`;

            return `
                <tr>
                    <td>${d}</td>
                    <td><b>${esc(a.target_url)}</b></td>
                    <td>${esc(a.client_name)}</td>
                    <td><span class="pill" style="background:${color}20; color:${color}; border:1px solid ${color}40;">${score.toFixed(0)}%</span></td>
                    <td>${repBadge}</td>
                    <td>
                        <div style="display:flex; gap:6px;">
                            <button class="btn btn-secondary btn-sm" onclick="app.loadSavedAudit(${a.id})">Review Report</button>
                            <button class="btn btn-primary btn-sm" onclick="app.generateReport(${a.id}, ${a.client_id || 'null'})">Create Public Link</button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    async loadSavedAudit(auditId) {
        try {
            const data = await jsonFetch(`${API_BASE}/audits/${auditId}`);
            this.state.currentAudit = data.audit_result || {};
            this.state.currentAudit.db_audit_id = auditId;
            this.state.currentAudit.client_name = data.client_name;
            this.state.currentAudit.company = data.company;
            this.renderTechnicalReport();
            this.navigate("technical_report");
        } catch (e) {
            alert("Error loading audit: " + e.message);
        }
    }

    /* -------------------------------------------------------------
       PUBLIC REPORT MANAGEMENT
    -------------------------------------------------------------- */
    async loadReports() {
        if (this.state.reports && this.state.reports.length) {
            this.renderReportsTable(this.state.reports);
        }
        try {
            this.state.reports = await jsonFetch(`${API_BASE}/reports`);
            this.renderReportsTable(this.state.reports);
        } catch (e) {
            console.error("Load reports error:", e);
        }
    }

    renderReportsTable(reports) {
        const tbody = $("reportsTableBody");
        if (!tbody) return;

        if (!reports || !reports.length) {
            tbody.innerHTML = `<tr><td colspan="6" class="empty-state">No public reports generated yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = reports.map(r => {
            const isPub = r.status === "PUBLISHED";
            const d = r.created_at ? new Date(r.created_at).toLocaleDateString() : "-";
            return `
                <tr>
                    <td>
                        <b>${esc(r.client_name)}</b>
                        <div style="font-size:12px; color:var(--text-muted);">${esc(r.target_url)}</div>
                    </td>
                    <td><b>${safe(r.score).toFixed(0)}%</b></td>
                    <td>
                        <span class="pill ${isPub ? 'pill-success' : 'pill-disabled'}">${esc(r.status)}</span>
                    </td>
                    <td><span style="font-size:12px; color:var(--text-muted);">${d}</span></td>
                    <td><code style="font-size:11px; background:#F1F5F9; padding:2px 6px; border-radius:4px;">${esc(r.token.substring(0, 12))}...</code></td>
                    <td>
                        <div style="display:flex; gap:6px; flex-wrap:wrap;">
                            <button class="btn btn-secondary btn-sm" onclick="app.openPreview('${r.token}')">Preview</button>
                            <button class="btn btn-secondary btn-sm" onclick="app.copyReportLink('${r.token}')">Copy Link</button>
                            <button class="btn btn-secondary btn-sm" onclick="window.open('/report/${r.token}', '_blank')">Client View</button>
                            <button class="btn btn-secondary btn-sm" style="background:#0F172A; color:#fff; border-color:#0F172A;" onclick="window.open('/api/reports/public/${r.token}/comprehensive', '_blank')" title="View 30-Section Full Consultancy Report">30-Sec View</button>
                            <button class="btn btn-secondary btn-sm" onclick="window.open('/api/reports/public/${r.token}/comprehensive/pdf', '_blank')" title="Download 30-Section Consultancy PDF">PDF</button>
                            <button class="btn btn-sm ${isPub ? 'btn-danger' : 'btn-success'}" onclick="app.toggleReportStatus(${r.id}, '${r.status}')">
                                ${isPub ? 'Disable' : 'Publish'}
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    async generateReport(auditId, clientId = null) {
        try {
            const res = await jsonFetch(`${API_BASE}/reports/generate`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ audit_id: auditId, client_id: clientId, status: "PUBLISHED" })
            });

            this.openPreview(res.token);
            await this.loadReports();
            await this.loadDashboardStats();
        } catch (e) {
            alert("Report generation failed: " + e.message);
        }
    }

    async generateReportFromCurrentAudit() {
        if (!this.state.currentAudit) return alert("No active audit loaded.");
        const auditId = this.state.currentAudit.db_audit_id;
        if (!auditId) {
            return alert("This audit has not been saved to the database yet.");
        }
        await this.generateReport(auditId);
    }

    async toggleReportStatus(reportId, currentStatus) {
        const newStatus = currentStatus === "PUBLISHED" ? "DISABLED" : "PUBLISHED";
        try {
            await jsonFetch(`${API_BASE}/reports/${reportId}/status`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            await this.loadReports();
            await this.loadDashboardStats();
            if (this.state.selectedClientId) {
                await this.viewClientDetail(this.state.selectedClientId);
            }
        } catch (e) {
            alert("Failed to update report status: " + e.message);
        }
    }

    openPreview(token) {
        this.state.previewToken = token;
        const iframe = $("previewIframe");
        iframe.src = `/report/${token}?preview=1`;
        $("previewModal").classList.remove("hidden");
    }

    closePreviewModal() {
        $("previewModal").classList.add("hidden");
        $("previewIframe").src = "about:blank";
    }

    copyPreviewLink() {
        if (!this.state.previewToken) return;
        this.copyReportLink(this.state.previewToken);
    }

    openPreviewTab() {
        if (!this.state.previewToken) return;
        window.open(`/report/${this.state.previewToken}?preview=1`, "_blank");
    }

    downloadPreviewPdf() {
        if (!this.state.previewToken) return;
        window.open(`/api/reports/public/${this.state.previewToken}/pdf`, "_blank");
    }

    copyReportLink(token) {
        const url = `${window.location.origin}/report/${token}`;
        navigator.clipboard.writeText(url).then(() => {
            alert(`Public report link copied to clipboard:\n${url}`);
        }).catch(() => {
            prompt("Copy this public report URL:", url);
        });
    }

    /* -------------------------------------------------------------
       SEO LEADS MANAGEMENT (ADMIN ONLY)
    -------------------------------------------------------------- */
    async loadLeads() {
        if (this.state.leads && this.state.leads.length) {
            this.renderLeadsTable(this.state.leads);
        }
        try {
            const leads = await jsonFetch(`${API_BASE}/leads`);
            this.state.leads = leads || [];
            this.renderLeadsTable(this.state.leads);
        } catch (e) {
            console.error("Load leads error:", e);
        }
    }

    renderLeadsTable(leads) {
        if (!leads) return;
        // Calculate KPI counts
        const total = leads.length;
        const newCount = leads.filter(l => (l.status || "").toUpperCase() === "NEW").length;
        const contacted = leads.filter(l => (l.status || "").toUpperCase() === "CONTACTED").length;
        const converted = leads.filter(l => (l.status || "").toUpperCase() === "CONVERTED").length;

        if ($("kpiLeadsTotal")) $("kpiLeadsTotal").textContent = fmt(total);
        if ($("kpiLeadsNew")) $("kpiLeadsNew").textContent = fmt(newCount);
        if ($("kpiLeadsContacted")) $("kpiLeadsContacted").textContent = fmt(contacted);
        if ($("kpiLeadsConverted")) $("kpiLeadsConverted").textContent = fmt(converted);

        const tbody = $("leadsTableBody");
        if (!tbody) return;

        if (!leads.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No public SEO scan leads recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = leads.map(l => {
            const d = l.created_at ? new Date(l.created_at).toLocaleString() : "-";
            const st = (l.status || "NEW").toUpperCase();
            let statusBadgeClass = "pill-disabled";
            if (st === "NEW") statusBadgeClass = "pill-primary";
            else if (st === "CONTACTED") statusBadgeClass = "pill-warning";
            else if (st === "QUALIFIED") statusBadgeClass = "pill-info";
            else if (st === "CONVERTED") statusBadgeClass = "pill-success";
            else if (st === "CLOSED") statusBadgeClass = "pill-disabled";

            const score = safe(l.initial_score);
            const scoreColor = getScoreColor(score);
            const scoreLabel = getScoreLabel(score);

            const cleanPhone = (l.phone || "").replace(/[^0-9]/g, "");

            return `
                <tr>
                    <td>
                        <b>${esc(l.name)}</b>
                        <div style="font-size:12px; color:var(--text-muted);">${esc(l.company || "Individual")}</div>
                    </td>
                    <td>
                        <a href="${esc(l.website)}" target="_blank" rel="noopener" style="color:var(--primary); font-weight:600; text-decoration:none; display:inline-flex; align-items:center; gap:4px;">
                            ${esc(l.website)} ↗
                        </a>
                    </td>
                    <td>
                        <div><a href="mailto:${esc(l.email)}" style="font-size:12px; color:var(--text); text-decoration:none;">${esc(l.email)}</a></div>
                        <div style="font-size:11px; color:var(--text-muted);">${esc(l.phone || "No phone")}</div>
                    </td>
                    <td>
                        <span class="pill" style="background:${scoreColor}15; color:${scoreColor}; font-weight:700; border:1px solid ${scoreColor}30;">
                            ${score}/100 • ${scoreLabel}
                        </span>
                    </td>
                    <td><span style="font-size:12px; color:var(--text-muted);">${d}</span></td>
                    <td>
                        <span class="pill ${statusBadgeClass}">${esc(st)}</span>
                    </td>
                    <td>
                        <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                            <button class="btn btn-secondary btn-sm" onclick="app.viewLeadDetail(${l.id})">View</button>
                            ${cleanPhone ? `
                                <a href="https://wa.me/${cleanPhone}?text=${encodeURIComponent(`Hello ${l.name}, following up on your eSupport SEO score check for ${l.website}`)}" target="_blank" class="btn btn-secondary btn-sm" style="text-decoration:none; color:#10B981; border-color:#10B98140;" title="Contact on WhatsApp">
                                    WhatsApp
                                </a>
                            ` : ''}
                            ${st !== "CONVERTED" ? `
                                <button class="btn btn-primary btn-sm" onclick="app.convertLead(${l.id})">Create Client</button>
                            ` : `
                                <button class="btn btn-secondary btn-sm" onclick="app.viewClientDetail(${l.client_id})" title="View Client #${l.client_id}">Client #${l.client_id}</button>
                            `}
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    async viewLeadDetail(leadId) {
        try {
            const lead = await jsonFetch(`${API_BASE}/leads/${leadId}`);
            this.state.selectedLeadId = leadId;

            if ($("leadModalTitle")) {
                $("leadModalTitle").textContent = `${lead.name} • ${lead.website}`;
            }
            const box = $("leadDetailContent");
            if (!box) return;

            const score = safe(lead.initial_score);
            const scoreColor = getScoreColor(score);
            const scoreLabel = getScoreLabel(score);
            const cleanPhone = (lead.phone || "").replace(/[^0-9]/g, "");
            const isConverted = (lead.status || "").toUpperCase() === "CONVERTED";

            const canConvert = this.hasPermission("leads.convert");
            const canAudit = this.hasPermission("audits.run");

            const waMsg = encodeURIComponent(`Hello ${lead.name}, Prasad from eSupport here following up on your preliminary SEO score (${score}/100) for ${lead.website}. We have identified key technical optimizations to improve your Google ranking.`);
            const waUrl = cleanPhone ? `https://wa.me/${cleanPhone}?text=${waMsg}` : '';

            const mailSubject = encodeURIComponent(`eSupport SEO Consultation: ${lead.website} (Score: ${score}/100)`);
            const mailBody = encodeURIComponent(`Hello ${lead.name},\n\nThank you for checking ${lead.website} with the eSupport SEO tool.\n\nYour preliminary SEO score is ${score}/100 (${scoreLabel}). We have generated an optimization roadmap for your website.\n\nPlease let us know if you'd like to review the technical recommendations.\n\nBest regards,\neSupport Team`);
            const mailUrl = `mailto:${esc(lead.email)}?subject=${mailSubject}&body=${mailBody}`;

            const timelineHtml = (lead.timeline || []).map(evt => `
                <div style="position:relative; padding-left:24px; margin-bottom:14px; border-left:2px solid var(--border);">
                    <div style="position:absolute; left:-6px; top:2px; width:10px; height:10px; border-radius:50%; background:var(--primary);"></div>
                    <div style="display:flex; justify-content:space-between; align-items:baseline;">
                        <b style="font-size:13px; color:var(--text);">${esc(evt.title || evt.action || "Event")}</b>
                        <span style="font-size:11px; color:var(--text-muted);">${evt.time ? new Date(evt.time).toLocaleString() : ""}</span>
                    </div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">${esc(evt.detail || evt.note || "")}</div>
                </div>
            `).join("") || `<div style="font-size:12px; color:var(--text-muted);">No timeline events recorded.</div>`;

            box.innerHTML = `
                <div class="grid" style="grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px; margin-bottom:24px;">
                    <!-- LEFT COLUMN: LEAD PROFILE -->
                    <div style="background:var(--bg-main); border:1px solid var(--border); border-radius:12px; padding:18px;">
                        <h4 style="margin:0 0 12px 0; font-size:13px; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted);">Contact Details</h4>
                        <div style="display:flex; flex-direction:column; gap:10px; font-size:13px;">
                            <div><b>Name:</b> ${esc(lead.name)}</div>
                            <div><b>Company:</b> ${esc(lead.company || "Not specified")}</div>
                            <div><b>Website:</b> <a href="${esc(lead.website)}" target="_blank" rel="noopener" style="color:var(--primary); font-weight:600;">${esc(lead.website)} ↗</a></div>
                            <div><b>Email:</b> <a href="${mailUrl}" style="color:var(--text);">${esc(lead.email)}</a></div>
                            <div><b>Phone:</b> ${esc(lead.phone || "Not provided")}</div>
                            <div><b>Source:</b> ${esc(lead.source || "Public SEO Checker")}</div>
                            <div><b>Received:</b> ${lead.created_at ? new Date(lead.created_at).toLocaleString() : "-"}</div>
                        </div>

                        ${lead.message ? `
                            <div style="margin-top:16px; padding:12px; background:var(--bg-card); border-radius:8px; border:1px solid var(--border);">
                                <div style="font-size:11px; font-weight:700; text-transform:uppercase; color:var(--text-muted); margin-bottom:4px;">Inquiry Note:</div>
                                <div style="font-size:13px; color:var(--text); font-style:italic;">"${esc(lead.message)}"</div>
                            </div>
                        ` : ''}
                    </div>

                    <!-- RIGHT COLUMN: SCORE & STATUS WORKFLOW -->
                    <div style="background:var(--bg-main); border:1px solid var(--border); border-radius:12px; padding:18px;">
                        <h4 style="margin:0 0 12px 0; font-size:13px; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted);">Initial SEO Audit Score</h4>
                        <div style="display:flex; align-items:center; gap:16px; margin-bottom:18px;">
                            <div style="width:64px; height:64px; border-radius:50%; background:${scoreColor}15; border:3px solid ${scoreColor}; display:grid; place-items:center; font-size:20px; font-weight:900; color:${scoreColor};">
                                ${score}
                            </div>
                            <div>
                                <div style="font-size:15px; font-weight:700; color:var(--text);">${scoreLabel} Foundation</div>
                                <div style="font-size:12px; color:var(--text-muted);">Calculated automatically during public scan</div>
                            </div>
                        </div>

                        <div class="form-group" style="margin-bottom:16px;">
                            <label style="font-size:12px; font-weight:700; text-transform:uppercase; color:var(--text-muted); display:block; margin-bottom:6px;">Update Lead Status</label>
                            <select id="leadStatusSelect" class="form-select" onchange="app.updateLeadStatus(${lead.id}, this.value)" style="width:100%;">
                                <option value="NEW" ${lead.status === 'NEW' ? 'selected' : ''}>NEW - Uncontacted</option>
                                <option value="CONTACTED" ${lead.status === 'CONTACTED' ? 'selected' : ''}>CONTACTED - Outreach Made</option>
                                <option value="QUALIFIED" ${lead.status === 'QUALIFIED' ? 'selected' : ''}>QUALIFIED - Opportunity Identified</option>
                                <option value="CONVERTED" ${lead.status === 'CONVERTED' ? 'selected' : ''}>CONVERTED - Client Created</option>
                                <option value="CLOSED" ${lead.status === 'CLOSED' ? 'selected' : ''}>CLOSED - Closed / Unresponsive</option>
                            </select>
                        </div>

                        <div style="display:flex; flex-direction:column; gap:8px;">
                            ${waUrl ? `
                                <a href="${waUrl}" target="_blank" class="btn btn-secondary" style="justify-content:center; text-decoration:none; color:#10B981; border-color:#10B98140;">
                                    💬 Open WhatsApp Chat
                                </a>
                            ` : ''}
                            <a href="${mailUrl}" class="btn btn-secondary" style="justify-content:center; text-decoration:none;">
                                ✉️ Send Outreach Email
                            </a>
                            ${!isConverted && canConvert ? `
                                <button class="btn btn-primary" onclick="app.convertLead(${lead.id})" style="justify-content:center;">
                                    Create Client &amp; Website
                                </button>
                            ` : ''}
                            ${isConverted ? `
                                <button class="btn btn-secondary" onclick="app.closeLeadDetailModal(); app.viewClientDetail(${lead.client_id});" style="justify-content:center;">
                                    Go to Client #${lead.client_id} Profile ↗
                                </button>
                            ` : ''}
                            ${canAudit ? `
                                <button class="btn btn-secondary" onclick="app.auditLeadWebsite('${esc(lead.website)}', ${lead.client_id || 'null'})" style="justify-content:center;">
                                    Run Full Deep Audit on Website
                                </button>
                            ` : ''}
                        </div>
                    </div>
                </div>

                <!-- BOTTOM GRID: SALES NOTES & TIMELINE -->
                <div class="grid" style="grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px;">
                    <!-- SALES NOTES SECTION -->
                    <div style="background:var(--bg-main); border:1px solid var(--border); border-radius:12px; padding:18px;">
                        <h4 style="margin:0 0 12px 0; font-size:13px; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted);">Sales Notes &amp; Follow-Ups</h4>
                        <div id="leadNotesList" style="max-height:180px; overflow-y:auto; margin-bottom:12px;">
                            <div style="font-size:12px; color:var(--text-muted);">Loading notes...</div>
                        </div>
                        <div style="display:flex; gap:8px;">
                            <input id="newLeadNoteInput" class="form-input" type="text" placeholder="Add follow-up sales note..." style="font-size:12px; flex:1;" onkeydown="if(event.key==='Enter'){event.preventDefault(); app.handleAddLeadNote(${lead.id});}">
                            <button class="btn btn-primary btn-sm" onclick="app.handleAddLeadNote(${lead.id})">Add Note</button>
                        </div>
                    </div>

                    <!-- TIMELINE SECTION -->
                    <div style="background:var(--bg-main); border:1px solid var(--border); border-radius:12px; padding:18px;">
                        <h4 style="margin:0 0 14px 0; font-size:13px; text-transform:uppercase; letter-spacing:0.5px; color:var(--text-muted);">Lead Interaction Timeline</h4>
                        <div style="margin-top:10px; max-height:220px; overflow-y:auto;">
                            ${timelineHtml}
                        </div>
                    </div>
                </div>
            `;

            $("leadDetailModal").classList.remove("hidden");
            this.loadLeadNotes(leadId);
        } catch (e) {
            alert("Error loading lead details: " + e.message);
        }
    }

    closeLeadDetailModal() {
        $("leadDetailModal").classList.add("hidden");
        this.state.selectedLeadId = null;
    }

    async updateLeadStatus(leadId, status) {
        try {
            await jsonFetch(`${API_BASE}/leads/${leadId}/status`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status })
            });
            await this.loadLeads();
            if (this.state.selectedLeadId === leadId) {
                await this.viewLeadDetail(leadId);
            }
        } catch (e) {
            alert("Failed to update status: " + e.message);
        }
    }

    async convertLead(leadId) {
        if (!confirm("Convert this inquiry into an active eSupport Client & Website?")) return;
        try {
            const res = await jsonFetch(`${API_BASE}/leads/${leadId}/convert`, {
                method: "POST"
            });
            alert(res.message || "Lead converted to client successfully!");
            await this.loadLeads();
            await this.loadClients();
            await this.loadDashboardStats();
            this.closeLeadDetailModal();
            if (res.client_id) {
                await this.viewClientDetail(res.client_id);
            }
        } catch (e) {
            alert("Lead conversion failed: " + e.message);
        }
    }

    auditLeadWebsite(targetUrl, clientId) {
        this.closeLeadDetailModal();
        $("auditUrlInput").value = targetUrl || "";
        if (clientId && $("auditClientSelect")) {
            $("auditClientSelect").value = String(clientId);
        }
        this.navigate("dashboard");
        $("auditUrlInput").focus();
    }

    /* -------------------------------------------------------------
       FULL TECHNICAL REPORT RENDERING (ADMIN ONLY)
    -------------------------------------------------------------- */
    renderTechnicalReport() {
        const audit = this.state.currentAudit;
        const notice = $("noAuditNotice");
        const content = $("technicalReportContent");

        if (!audit || !audit.target) {
            notice.classList.remove("hidden");
            content.classList.add("hidden");
            return;
        }

        notice.classList.add("hidden");
        content.classList.remove("hidden");

        $("techTargetUrl").textContent = audit.target || audit.url || "Target Site";
        $("techAuditMeta").textContent = `Audit Date: ${new Date(audit.created_at || Date.now()).toLocaleString()} • Total Pages: ${fmt(audit.page_count || 1)} • Health Score: ${safe(audit.score).toFixed(1)}/100`;

        this.renderTechTabContent(this.state.currentTechTab);
    }

    renderRealDataTab(audit) {
        const rd = audit.real_data || {};
        const prov = audit.data_provenance || {};
        const errors = prov.integration_errors || {};
        const ratingColor = r => r === "good" ? "var(--success, #10B981)" : r === "poor" ? "var(--danger)" : "var(--warning)";
        const metricVal = (k, m) => k === "CLS" ? Number(m.p75).toFixed(2) : (Number(m.p75) / 1000).toFixed(2) + " s";
        const psiCard = (label, p) => {
            if (!p) return "";
            if (!p.ok) return `<div class="card"><b>${esc(label)}</b><p style="color:var(--danger)">${esc(p.error)}</p></div>`;
            const f = p.field_url || p.field_origin;
            const lh = p.lighthouse_scores || {};
            return `
                <div class="card">
                    <b>${esc(label)}</b>
                    ${f ? `<p>Core Web Vitals (real users, ${esc(f.scope)}-level): <b style="color:${f.core_web_vitals_assessment === "passed" ? "var(--success, #10B981)" : "var(--danger)"}">${esc(f.core_web_vitals_assessment)}</b></p>
                    <table><tbody>${Object.entries(f.metrics).map(([k, m]) => `<tr><td>${esc(k)}</td><td><b style="color:${ratingColor(m.rating)}">${esc(metricVal(k, m))}</b></td><td>${esc(m.rating)}</td></tr>`).join("")}</tbody></table>`
                    : `<p style="color:var(--text-muted)">No CrUX field data (not enough real Chrome traffic).</p>`}
                    <p style="margin-top:8px;">Lighthouse lab: ${Object.entries(lh).map(([k, v]) => `${esc(k)} <b>${esc(v)}</b>`).join(" • ")}</p>
                    ${(p.failed_seo_audits || []).length ? `<p style="font-size:12px;">Failed Lighthouse SEO audits: ${p.failed_seo_audits.map(a => esc(a.title)).join("; ")}</p>` : ""}
                </div>`;
        };
        const psi = rd.pagespeed || {};
        const gsc = rd.search_console;
        const dfs = rd.dataforseo || {};
        const rk = dfs.ranked_keywords, bl = dfs.backlinks;
        const table = (heads, rows) => `<div class="table-container"><table><thead><tr>${heads.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${heads.length}" class="empty-state">No data.</td></tr>`}</tbody></table></div>`;
        return `
            <h3>Real Measured Data</h3>
            <div style="font-size:13px; color:var(--text-muted); margin-bottom:16px;">Everything on this tab comes directly from Google PageSpeed Insights / CrUX, the Google Search Console API and DataForSEO. The health score and category scores elsewhere are <b>estimates</b>.</div>
            ${Object.keys(errors).length ? `<div class="card" style="border-left:4px solid var(--warning); margin-bottom:16px;"><b>Integration problems</b>${Object.entries(errors).map(([k, v]) => `<p style="font-size:12px;"><code>${esc(k)}</code>: ${esc(v)}</p>`).join("")}</div>` : ""}
            <h4>Page Speed &amp; Core Web Vitals</h4>
            <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; margin-bottom:24px;">
                ${psiCard("Mobile", psi.mobile) + psiCard("Desktop", psi.desktop) || '<div class="empty-state">PageSpeed was not run for this audit.</div>'}
            </div>
            <h4>Google Search Console</h4>
            ${gsc && gsc.ok ? `
                <p>Property <code>${esc(gsc.property)}</code> • ${esc(gsc.start_date)} → ${esc(gsc.end_date)}</p>
                <div class="grid grid-stats" style="margin-bottom:16px;">
                    <div class="card stat-card"><b class="stat-value">${fmt(gsc.totals.clicks)}</b><span class="stat-label">Clicks</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(gsc.totals.impressions)}</b><span class="stat-label">Impressions</span></div>
                    <div class="card stat-card"><b class="stat-value">${esc(gsc.totals.ctr)}%</b><span class="stat-label">CTR</span></div>
                    <div class="card stat-card"><b class="stat-value">${esc(gsc.totals.position)}</b><span class="stat-label">Avg. Position</span></div>
                </div>
                ${table(["Query", "Clicks", "Impressions", "CTR %", "Avg. Position"], (gsc.top_queries || []).slice(0, 50).map(q => `<tr><td><b>${esc(q.query)}</b></td><td>${fmt(q.clicks)}</td><td>${fmt(q.impressions)}</td><td>${esc(q.ctr)}</td><td>${esc(q.position)}</td></tr>`).join(""))}
                ${table(["Page", "Clicks", "Impressions", "CTR %", "Avg. Position"], (gsc.top_pages || []).slice(0, 30).map(q => `<tr><td style="font-size:12px;">${esc(q.page)}</td><td>${fmt(q.clicks)}</td><td>${fmt(q.impressions)}</td><td>${esc(q.ctr)}</td><td>${esc(q.position)}</td></tr>`).join(""))}
            ` : `<div class="empty-state" style="margin-bottom:24px;">${esc((gsc && gsc.error) || "Search Console not connected for this audit.")}</div>`}
            <h4>Google Rankings (DataForSEO)</h4>
            ${rk && rk.ok ? `<p>${fmt(rk.total_count)} ranking keywords • location ${esc(rk.location_code)} / ${esc(rk.language_code)}</p>` +
                table(["Keyword", "Position", "Volume", "KD", "Intent", "URL"], (rk.keywords || []).map(k => `<tr><td><b>${esc(k.keyword)}</b></td><td>#${esc(k.position)}</td><td>${k.search_volume != null ? fmt(k.search_volume) : "—"}</td><td>${k.keyword_difficulty ?? "—"}</td><td>${esc(k.intent || "—")}</td><td style="font-size:12px;">${esc(k.url)}</td></tr>`).join(""))
                : `<div class="empty-state" style="margin-bottom:24px;">${esc((rk && rk.error) || dfs.error || "DataForSEO not enabled for this audit (tick 'DataForSEO' before running).")}</div>`}
            <h4>Backlinks (DataForSEO)</h4>
            ${bl && bl.ok ? `
                <div class="grid grid-stats" style="margin-bottom:16px;">
                    <div class="card stat-card"><b class="stat-value">${fmt(bl.referring_domains)}</b><span class="stat-label">Referring Domains</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(bl.backlinks)}</b><span class="stat-label">Backlinks</span></div>
                    <div class="card stat-card"><b class="stat-value">${bl.domain_rank ?? "—"}/${esc(bl.domain_rank_scale)}</b><span class="stat-label">Domain Rank</span></div>
                    <div class="card stat-card"><b class="stat-value">${bl.spam_score ?? "—"}</b><span class="stat-label">Spam Score</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(bl.broken_backlinks)}</b><span class="stat-label">Broken Backlinks</span></div>
                </div>
                ${table(["Referring Domain", "Rank", "Backlinks", "First Seen"], (bl.top_referring_domains || []).map(d => `<tr><td>${esc(d.domain)}</td><td>${esc(d.rank)}</td><td>${fmt(d.backlinks)}</td><td>${esc(d.first_seen || "")}</td></tr>`).join(""))}
            ` : `<div class="empty-state">${esc((bl && bl.error) || "Backlink data not enabled for this audit.")}</div>`}
            ${dfs.cost_usd != null ? `<p style="font-size:12px; color:var(--text-muted); margin-top:12px;">DataForSEO cost for this audit: $${esc(dfs.cost_usd)} (cached results are free).</p>` : ""}
        `;
    }

    /* Engine payload views: presentation only. Every number is read from audit.seo_engine (backend = source of truth). */
    renderEngineOverview(audit, eng) {
        const sc = eng.score || {};
        if (eng.error) return `<div class="card" style="border-left:4px solid var(--danger)"><b>${esc(eng.error)}</b><p>No score was produced.</p></div>`;
        const color = getScoreColor(sc.overall);
        const summ = eng.issue_summary || {};
        const pot = sc.potential || null;
        const caps = eng.capabilities || {};
        const cats = eng.categories || [];
        return `
            <div style="font-size:12px; color:var(--text-muted); background:#F8FAFC; border:1px solid var(--border); border-radius:10px; padding:10px 12px; margin-bottom:18px;">${esc((eng.integrity || {}).statement || "")}</div>
            <div class="grid" style="grid-template-columns: 260px 1fr; align-items:start; gap:24px; margin-bottom:24px;">
                <div style="text-align:center;">
                    <div style="font-size:64px; font-weight:900; color:${color}; line-height:1;">${sc.overall ?? "–"}<small style="font-size:24px; color:var(--text-muted);">/100</small></div>
                    <div style="font-weight:800; font-size:18px; margin-top:6px; color:${color};">${esc(sc.grade || "")}</div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Maturity level ${esc(sc.maturity_level)} — ${esc(sc.maturity_label || "")}</div>
                    <div style="font-size:11px; color:var(--text-muted); margin-top:8px;">round_half_up(${fmt(sc.weighted_sum)} / 100) • ruleset ${esc(eng.ruleset_version)}</div>
                    ${pot ? `<div style="margin-top:14px; padding:10px; border:1px dashed var(--border); border-radius:10px; font-size:12px;">
                        <b>Potential: ${esc(pot.overall)}/100 (${esc(pot.grade)})</b>, +${esc(pot.improvement_absolute)}<br>
                        <span style="color:var(--text-muted);">${esc(pot.disclaimer)}</span></div>` : ""}
                </div>
                <div>
                    <table>
                        <thead><tr><th>Category</th><th>Weight</th><th>Score</th><th>W×S</th><th>Grade</th><th>Checks</th><th>Potential</th></tr></thead>
                        <tbody>
                        ${cats.map(c => `<tr title="${esc(c.provisional_note || c.summary)}">
                            <td><b>${esc(c.name)}</b>${c.provisional ? ' <span style="color:var(--warning)" title="Provisional: some checks could not be measured">*</span>' : ""}</td>
                            <td>${esc(c.weight)}</td>
                            <td><b style="color:${getScoreColor(c.score)}">${c.score ?? "Unscorable"}</b></td>
                            <td>${c.weighted_contribution ?? "–"}</td>
                            <td>${esc(c.grade)}</td>
                            <td style="font-size:12px;">${esc(c.checks_passed)} of ${esc(c.checks_measured)} passed${c.unmeasured_points ? `, ${esc(c.unmeasured_points)} pts not measured` : ""}</td>
                            <td>${esc(c.potential_score)}</td></tr>`).join("")}
                        <tr><td><b>Total</b></td><td><b>${cats.reduce((a, c) => a + c.weight, 0)}</b></td><td></td><td><b>${fmt(sc.weighted_sum)}</b></td><td><b>${esc(sc.grade)}</b></td><td></td><td>${pot ? esc(pot.overall) : ""}</td></tr>
                        </tbody>
                    </table>
                    <div style="font-size:11px; color:var(--text-muted); margin-top:6px;">* Provisional: part of the category could not be measured; the score is capped until that data is connected and may move either way.</div>
                </div>
            </div>
            <div class="grid grid-stats" style="margin-bottom:24px;">
                <div class="card stat-card"><b class="stat-value">${fmt(audit.page_count)}</b><span class="stat-label">Pages Audited</span></div>
                <div class="card stat-card"><b class="stat-value" style="color:var(--danger)">${fmt(summ.critical)}</b><span class="stat-label">Critical (P1)</span></div>
                <div class="card stat-card"><b class="stat-value" style="color:#F97316">${fmt(summ.high)}</b><span class="stat-label">High (P2)</span></div>
                <div class="card stat-card"><b class="stat-value" style="color:var(--warning)">${fmt(summ.medium)}</b><span class="stat-label">Medium (P3)</span></div>
                <div class="card stat-card"><b class="stat-value">${fmt(summ.low)}</b><span class="stat-label">Low (P4)</span></div>
                <div class="card stat-card"><b class="stat-value">${fmt((eng.unmeasured || []).length)}</b><span class="stat-label">Checks not measured</span></div>
            </div>
            <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px;">
                <div class="card"><h4 style="margin-top:0;">Quick wins (${fmt((eng.quick_win_totals || {}).item_count)} • ${esc((eng.quick_win_totals || {}).total_hours)} h total)</h4>
                    ${(eng.quick_wins || []).slice(0, 8).map(q => `<div style="font-size:13px; padding:6px 0; border-bottom:1px solid var(--border);"><b>${esc(q.priority)}</b> ${esc(q.task)} <span style="color:var(--text-muted)">(${esc(q.check_id)}, ${esc(q.effort_minutes)} min)</span></div>`).join("") || '<div class="empty-state">None.</div>'}
                </div>
                <div class="card"><h4 style="margin-top:0;">Data sources for this audit</h4>
                    ${["html_raw", "probes", "render", "psi", "gsc", "ga4", "backlink"].map(k => `<div style="display:flex; justify-content:space-between; font-size:13px; padding:3px 0;"><span>${esc({html_raw: "Raw HTML (JSON-LD readable)", probes: "Host / redirect / 404 probes", render: "Browser render (mobile)", psi: "PageSpeed Insights (Core Web Vitals)", gsc: "Search Console", ga4: "Google Analytics 4", backlink: "Backlink data"}[k])}</span><b style="color:${caps[k] ? "var(--success, #10B981)" : "var(--text-muted)"}">${caps[k] ? "Measured" : "Not available"}</b></div>`).join("")}
                    ${(caps.notes || []).map(n => `<p style="font-size:11px; color:var(--text-muted); margin:6px 0 0;">${esc(n)}</p>`).join("")}
                </div>
            </div>
            ${(eng.missing_pages || []).length ? `<div class="card" style="margin-top:16px;"><b>Missing pages (not broken links):</b> ${(eng.missing_pages || []).map(m => esc(m.url)).join(", ")}</div>` : ""}
        `;
    }

    renderEngineChecks(eng) {
        const color = { PASS: "var(--success, #10B981)", WARN: "var(--warning)", FAIL: "var(--danger)", UNMEASURED: "var(--text-muted)", NOT_APPLICABLE: "var(--text-muted)" };
        const byCat = {};
        (eng.checks || []).forEach(c => (byCat[c.category] = byCat[c.category] || []).push(c));
        return `
            <h3>Check-level evidence (${fmt((eng.checks || []).length)} checks)</h3>
            <div style="font-size:13px; color:var(--text-muted); margin-bottom:12px;">Every category score is the weighted result of these checks. Not-measured checks earn no points and are excluded from the denominator; they never count as failures.</div>
            ${(eng.categories || []).map(cat => `
                <h4 style="margin:18px 0 8px;">${esc(cat.name)} — ${cat.score ?? "Unscorable"} (weight ${esc(cat.weight)})${cat.provisional ? " *" : ""}</h4>
                <div class="table-container"><table>
                    <thead><tr><th>Check</th><th>Name</th><th>Status</th><th>Points</th><th>Evidence</th></tr></thead>
                    <tbody>${(byCat[cat.id] || []).map(c => `<tr>
                        <td><code>${esc(c.id)}</code></td><td>${esc(c.name)}</td>
                        <td><b style="color:${color[c.status]}">${esc(c.display_as || c.status)}</b></td>
                        <td>${esc(c.points_earned)} / ${esc(c.points_available)}</td>
                        <td style="font-size:12px;"><span class="pill pill-info">${esc(c.evidence.label)}</span> ${esc(c.evidence.statement)}
                            ${(c.evidence.urls || []).length ? `<br><span style="color:var(--text-muted);">${c.evidence.urls.slice(0, 3).map(esc).join(" • ")}</span>` : ""}
                            ${c.resolution ? `<br><span style="color:var(--text-muted);">Resolve with: ${esc(c.resolution.tool)}</span>` : ""}</td>
                    </tr>`).join("")}</tbody>
                </table></div>`).join("")}
        `;
    }

    switchTechTab(tab) {
        this.state.currentTechTab = tab;
        document.querySelectorAll("#techTabsHeader .tab-btn").forEach(btn => {
            btn.classList.toggle("active", (btn.getAttribute("onclick") || "").includes(`'${tab}'`));
        });
        this.renderTechTabContent(tab);
    }

    renderTechTabContent(tab) {
        const audit = this.state.currentAudit || {};
        const container = $("techTabContent");
        const s = audit.scores || {};
        const st = audit.stats || {};
        const pages = audit.pages || [];
        const issues = audit.issues || [];
        const recs = audit.recommendations || {};
        const ki = audit.keyword_intelligence || {};

        const eng = audit.seo_engine || null;
        if (tab === "overview") {
            container.innerHTML = eng ? this.renderEngineOverview(audit, eng) : `<div class="empty-state">This audit has no scoring payload. Re-run the audit.</div>`;
        }
        else if (tab === "checks") {
            container.innerHTML = eng ? this.renderEngineChecks(eng) : `<div class="empty-state">No check data.</div>`;
        }
        else if (tab === "technical") {
            const robots = audit.site?.robots || {};
            const sm = audit.site?.sitemap || {};
            container.innerHTML = `
                <h3>Technical Infrastructure & Crawlability</h3>
                <div class="grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:16px; margin-bottom:24px;">
                    <div class="card"><b>HTTPS Protocol</b><p>${audit.target?.startsWith("https://") ? "✓ Secure HTTPS" : "✗ Insecure HTTP"}</p></div>
                    <div class="card"><b>robots.txt</b><p>${robots.found ? "✓ robots.txt Found" : "✗ robots.txt Missing"}</p></div>
                    <div class="card"><b>XML Sitemaps</b><p>${(sm.files || []).length} sitemap(s) discovered</p></div>
                    <div class="card"><b>Average Response</b><p>${fmt(st.average_response_ms)} ms</p></div>
                </div>
                <h4>Robots &amp; Sitemap Details</h4>
                <div style="background:#0F172A; color:#E2E8F0; padding:16px; border-radius:10px; font-family:monospace; font-size:12px; margin-bottom:20px;">
                    robots URL: ${esc(robots.url || "N/A")}<br>
                    HTTP Status: ${robots.status || 0}<br>
                    Referenced Sitemaps: ${(robots.sitemaps || []).join(", ") || "None"}
                </div>
            `;
        }
        else if (tab === "onpage") {
            container.innerHTML = `
                <h3>On-Page SEO Fundamentals</h3>
                <div class="grid grid-stats" style="margin-bottom:24px;">
                    <div class="card stat-card"><b class="stat-value">${fmt(st.missing_title_pages)}</b><span class="stat-label">Missing Titles</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.missing_meta_description_pages)}</b><span class="stat-label">Missing Descriptions</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.missing_h1_pages)}</b><span class="stat-label">Missing H1 Tags</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.missing_canonical_pages)}</b><span class="stat-label">Missing Canonical</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.pages_with_schema)}</b><span class="stat-label">Pages with Schema</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.pages_with_open_graph)}</b><span class="stat-label">Pages with Open Graph</span></div>
                </div>
            `;
        }
        else if (tab === "content") {
            container.innerHTML = `
                <h3>Content Quality Signals</h3>
                <div class="grid grid-stats" style="margin-bottom:24px;">
                    <div class="card stat-card"><b class="stat-value">${fmt(st.average_html_kb)} KB</b><span class="stat-label">Average HTML Size</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.js_heavy_pages)}</b><span class="stat-label">JavaScript Heavy Pages</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.slow_pages)}</b><span class="stat-label">Slow Pages (>800ms)</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.large_html_pages)}</b><span class="stat-label">Large HTML Pages (>1MB)</span></div>
                </div>
            `;
        }
        else if (tab === "keywords") {
            const terms = ki.observed_keywords || [];
            const tags = ki.hashtags || [];
            container.innerHTML = `
                <h3>Keyword &amp; Topic Intelligence</h3>
                <div style="font-size:13px; color:var(--text-muted); margin-bottom:16px;">${esc(ki.data_boundary || "Directly observed terms extracted from crawled page HTML.")} Blank cells (—) mean the provider had no data; nothing is estimated.</div>
                <div class="table-container" style="margin-bottom:24px;">
                    <table>
                        <thead>
                            <tr><th>Keyword Term</th><th>Observed Count</th><th>Pages</th><th>Search Intent</th><th>Monthly Volume</th><th>KD</th><th>Google Pos.</th><th>GSC Clicks</th><th>GSC Impr.</th></tr>
                        </thead>
                        <tbody>
                            ${terms.slice(0, 50).map(t => `
                                <tr>
                                    <td><b>${esc(t.keyword)}</b></td>
                                    <td>${fmt(t.observed_count)}</td>
                                    <td>${fmt(t.pages)}</td>
                                    <td><span class="pill pill-info" title="${t.intent_source ? "Source: " + esc(t.intent_source) : "Rule-based guess from wording"}">${esc(t.intent || "informational")}${t.intent_source ? "" : " (est.)"}</span></td>
                                    <td>${t.search_volume != null ? fmt(t.search_volume) : "—"}</td>
                                    <td>${t.keyword_difficulty != null ? esc(t.keyword_difficulty) : "—"}</td>
                                    <td>${t.google_position != null ? "#" + esc(t.google_position) : (t.gsc_position != null ? esc(t.gsc_position) + " (GSC avg)" : "—")}</td>
                                    <td>${t.gsc_clicks != null ? fmt(t.gsc_clicks) : "—"}</td>
                                    <td>${t.gsc_impressions != null ? fmt(t.gsc_impressions) : "—"}</td>
                                </tr>
                            `).join("") || '<tr><td colspan="9" class="empty-state">No keywords extracted.</td></tr>'}
                        </tbody>
                    </table>
                </div>
                <h4>Suggested Hashtags</h4>
                <div style="display:flex; flex-wrap:wrap; gap:8px;">
                    ${tags.slice(0, 25).map(tg => `<span class="pill pill-info">${esc(tg.hashtag)} (${fmt(tg.pages)})</span>`).join("") || '<div class="empty-state">None.</div>'}
                </div>
            `;
        }
        else if (tab === "links") {
            const checks = audit.link_checks || [];
            container.innerHTML = `
                <h3>Internal Linking &amp; Architecture</h3>
                <div class="grid grid-stats" style="margin-bottom:24px;">
                    <div class="card stat-card"><b class="stat-value">${fmt(st.checked_links)}</b><span class="stat-label">Checked Links</span></div>
                    <div class="card stat-card"><b class="stat-value" style="color:var(--danger)">${fmt(st.broken_links)}</b><span class="stat-label">Broken Links</span></div>
                    <div class="card stat-card"><b class="stat-value">${fmt(st.max_crawl_depth)}</b><span class="stat-label">Max Crawl Depth</span></div>
                </div>
                <h4>Sample Link Targets</h4>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr><th>URL</th><th>Status</th><th>Response Time</th><th>Error</th></tr>
                        </thead>
                        <tbody>
                            ${checks.slice(0, 25).map(l => `
                                <tr>
                                    <td>${esc(l.url)}</td>
                                    <td>${l.status}</td>
                                    <td>${l.elapsed_ms} ms</td>
                                    <td>${esc(l.error || "-")}</td>
                                </tr>
                            `).join("") || '<tr><td colspan="4" class="empty-state">No link checks recorded.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            `;
        }
        else if (tab === "local") {
            container.innerHTML = eng ? this.renderEngineChecks({ ...eng, categories: (eng.categories || []).filter(c => c.id === "local") }) : '<div class="empty-state">No check data.</div>';
        }
        else if (tab === "ecommerce") {
            container.innerHTML = eng ? `<div style="font-size:13px; color:var(--text-muted);">Industry profile: <b>${esc((eng.audit || {}).vertical_profile)}</b> — ${esc((eng.audit || {}).vertical_profile_reason || "")}</div>` +
                this.renderEngineChecks({ ...eng, categories: (eng.categories || []).filter(c => c.id === "vertical") }) : '<div class="empty-state">No check data.</div>';
        }
        else if (tab === "realdata") {
            container.innerHTML = this.renderRealDataTab(audit);
        }
        else if (tab === "issues") {
            container.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                    <h3 style="margin:0;">SEO Issues Master Table (${fmt(issues.length)})</h3>
                    <button class="btn btn-secondary btn-sm" onclick="app.downloadCsv('issues')">Export Issues CSV</button>
                </div>
                <div style="font-size:12px; color:var(--text-muted); margin-bottom:10px;">Every issue comes from a failed or partially-passed check (see Checks &amp; Evidence). Severity orders the work; it does not deduct extra points.</div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr><th>ID</th><th>Severity</th><th>Priority</th><th>Check</th><th>Category</th><th>Evidence</th><th>Pages</th><th>Recommended fix</th></tr>
                        </thead>
                        <tbody>
                            ${issues.map(i => {
                                const sev = i.severity || "low";
                                const pillClass = sev === "critical" ? "pill-critical" : (sev === "high" || sev === "medium") ? "pill-warning" : "pill-info";
                                return `
                                    <tr>
                                        <td>${esc(i.id || "")}</td>
                                        <td><span class="pill ${pillClass}">${esc(sev)}</span></td>
                                        <td><b>${esc(i.priority || "")}</b></td>
                                        <td><code>${esc(i.check_id || i.code)}</code><br><span style="font-size:12px;">${esc(i.check_name || "")}</span></td>
                                        <td>${esc(i.category_name || i.category)}</td>
                                        <td style="font-size:12px;"><span class="pill pill-info">${esc(i.evidence_label || "")}</span> ${esc(i.message)}</td>
                                        <td><span style="font-size:11px; color:var(--text-muted);">${(i.urls || [i.url]).filter(Boolean).slice(0, 3).map(esc).join("<br>")}</span></td>
                                        <td style="font-size:12px;">${esc(i.recommended_fix || i.recommendation || "")}${i.effort_minutes ? `<br><span style="color:var(--text-muted);">~${esc(i.effort_minutes)} min</span>` : ""}</td>
                                    </tr>
                                `;
                            }).join("") || '<tr><td colspan="8" class="empty-state">No issues found.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            `;
        }
        else if (tab === "pages") {
            container.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                    <h3 style="margin:0;">Page-by-Page Audit (${fmt(pages.length)})</h3>
                    <button class="btn btn-secondary btn-sm" onclick="app.downloadCsv('pages')">Export Pages CSV</button>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr><th>Status</th><th>URL</th><th>Title</th><th>Words</th><th>H1</th><th>Images</th><th>Links</th><th>Time</th><th>Findings</th></tr>
                        </thead>
                        <tbody>
                            ${pages.slice(0, 50).map(p => `
                                <tr>
                                    <td>${p.status}</td>
                                    <td><span style="font-size:12px;">${esc(p.url)}</span></td>
                                    <td>${esc(p.title || "(none)")}</td>
                                    <td>${fmt(p.word_count)}</td>
                                    <td>${(p.h1 || []).length}</td>
                                    <td>${(p.images || []).length}</td>
                                    <td>${(p.internal_links || []).length}</td>
                                    <td>${p.response_time_ms} ms</td>
                                    <td>${(p.issues || []).length}</td>
                                </tr>
                            `).join("") || '<tr><td colspan="9" class="empty-state">No pages.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            `;
        }
        else if (tab === "recommendations") {
            const devPlan = recs.developer_plan || recs.priorities || [];
            container.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                    <h3 style="margin:0;">Developer Action Plan (${fmt(devPlan.length)})</h3>
                    <button class="btn btn-secondary btn-sm" onclick="app.downloadSpecialPdf('developer')">Download Developer PDF</button>
                </div>
                <div class="grid" style="gap:16px;">
                    ${devPlan.map(dp => `
                        <div class="card" style="border-left: 4px solid var(--primary);">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                                <div>
                                    <span class="pill pill-info">${esc(dp.priority)}</span>
                                    <b style="margin-left:8px;">${esc(dp.category)} • ${esc(dp.code)}</b>
                                </div>
                                <span style="font-size:12px; color:var(--text-muted);">${fmt(dp.affected)} affected URL(s)</span>
                            </div>
                            <h4 style="margin:4px 0 8px 0;">${esc(dp.issue)}</h4>
                            <p style="font-size:14px; margin:0 0 10px 0;"><b>Action:</b> ${esc(dp.action)}</p>
                            <div style="background:#0F172A; color:#E2E8F0; padding:12px; border-radius:8px; font-family:monospace; font-size:12px; white-space:pre-wrap;">${esc(dp.fix || dp.developer_fix || "Apply standard optimization.")}</div>
                            <div style="font-size:12px; color:var(--text-muted); margin-top:8px;"><b>Validation:</b> ${esc(dp.validation || "")}</div>
                        </div>
                    `).join("") || '<div class="empty-state">No developer items.</div>'}
                </div>
            `;
        }
        else if (tab === "export") {
            container.innerHTML = `
                <h3>Report Center • Exports &amp; Downloads</h3>
                <p style="color:var(--text-muted);">Download publication-grade PDFs, full CSV tables, and the complete zipped report bundle.</p>
                <div class="grid" style="grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:16px; margin-top:20px;">
                    <div class="card" style="text-align:center; border:2px solid var(--primary); background:#EFF6FF;">
                        <span class="pill pill-primary" style="margin-bottom:6px; font-weight:700;">CLIENT READY</span>
                        <h4>Client Summary PDF (2-3 Pages)</h4>
                        <p style="font-size:12px; color:var(--text-muted); margin-bottom:12px;">Executive report featuring circular SEO gauge, category breakdown, high-impact fixes, and strategic roadmap.</p>
                        <button class="btn btn-primary" onclick="app.downloadSpecialPdf('client')">Download Client PDF</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Full A-Z Audit PDF</h4>
                        <button class="btn btn-primary" onclick="app.downloadSpecialPdf('full')">Download PDF</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Developer Handover PDF</h4>
                        <button class="btn btn-primary" onclick="app.downloadSpecialPdf('developer')">Download PDF</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Executive Summary PDF</h4>
                        <button class="btn btn-primary" onclick="app.downloadSpecialPdf('executive')">Download PDF</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>All Recommendations PDF</h4>
                        <button class="btn btn-primary" onclick="app.downloadSpecialPdf('recommendations_all')">Download PDF</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Keywords &amp; Topics PDF</h4>
                        <button class="btn btn-primary" onclick="app.downloadSpecialPdf('keywords')">Download PDF</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Complete Report Pack ZIP</h4>
                        <button class="btn btn-success" onclick="app.downloadBundleZip()">Download ZIP Pack</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Pages CSV Export</h4>
                        <button class="btn btn-secondary" onclick="app.downloadCsv('pages')">Download CSV</button>
                    </div>
                    <div class="card" style="text-align:center;">
                        <h4>Issues CSV Export</h4>
                        <button class="btn btn-secondary" onclick="app.downloadCsv('issues')">Download CSV</button>
                    </div>
                </div>
            `;
        }
        else if (tab === "raw") {
            container.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; flex-wrap:wrap; gap:10px;">
                    <h3 style="margin:0;">Raw Audit JSON</h3>
                    <button class="btn btn-secondary btn-sm" onclick="app.downloadRawJson()">Download JSON File</button>
                </div>
                <pre style="background:#0F172A; color:#E2E8F0; padding:18px; border-radius:10px; font-family:monospace; font-size:12px; max-height:600px; overflow:auto;">${esc(JSON.stringify(audit, null, 2))}</pre>
            `;
        }
    }

    /* -------------------------------------------------------------
       EXPORT DOWNLOADS
    -------------------------------------------------------------- */
    async downloadSpecialPdf(reportType) {
        if (!this.state.currentAudit) return alert("No audit loaded.");
        try {
            const headers = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
            if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
            const resp = await fetch(`${API_BASE}/report/pdf`, {
                method: "POST",
                credentials: "include",
                headers,
                body: JSON.stringify({ audit: this.state.currentAudit, report_type: reportType })
            });
            if (!resp.ok) {
                const errText = await resp.text().catch(() => "");
                throw new Error(errText || "PDF download failed");
            }
            const blob = await resp.blob();
            this.triggerDownload(blob, `esupport-seo-${reportType}-report.pdf`);
        } catch (e) {
            alert("PDF export failed: " + e.message);
        }
    }

    async downloadBundleZip() {
        if (!this.state.currentAudit) return alert("No audit loaded.");
        try {
            const headers = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
            if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
            const resp = await fetch(`${API_BASE}/report/bundle`, {
                method: "POST",
                credentials: "include",
                headers,
                body: JSON.stringify({ audit: this.state.currentAudit })
            });
            if (!resp.ok) throw new Error("ZIP bundle download failed");
            const blob = await resp.blob();
            this.triggerDownload(blob, `esupport-seo-report-pack.zip`);
        } catch (e) {
            alert("Bundle export failed: " + e.message);
        }
    }

    async downloadCsv(kind) {
        if (!this.state.currentAudit) return alert("No audit loaded.");
        try {
            const headers = { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" };
            if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
            const resp = await fetch(`${API_BASE}/report/csv`, {
                method: "POST",
                credentials: "include",
                headers,
                body: JSON.stringify({ audit: this.state.currentAudit, kind: kind })
            });
            if (!resp.ok) throw new Error("CSV download failed");
            const blob = await resp.blob();
            this.triggerDownload(blob, `esupport-seo-${kind}.csv`);
        } catch (e) {
            alert("CSV export failed: " + e.message);
        }
    }

    downloadRawJson() {
        if (!this.state.currentAudit) return alert("No audit loaded.");
        const str = JSON.stringify(this.state.currentAudit, null, 2);
        const blob = new Blob([str], { type: "application/json" });
        this.triggerDownload(blob, `esupport-seo-audit-raw.json`);
    }

    triggerDownload(blob, filename) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    }

    /* -------------------------------------------------------------
       SOURCE AUDIT
    -------------------------------------------------------------- */
    async runSourceAudit() {
        const input = $("sourceZipInput");
        if (!input.files || !input.files[0]) return alert("Please select a ZIP file.");

        const formData = new FormData();
        formData.append("file", input.files[0]);

        const resBox = $("sourceAuditResults");
        resBox.classList.remove("hidden");
        resBox.innerHTML = `<div style="color:var(--text-muted); font-size:13px;">Analyzing source code archive...</div>`;

        try {
            const resp = await fetch(`${API_BASE}/source-audit`, {
                method: "POST",
                body: formData
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || "Source audit failed");

            resBox.innerHTML = `
                <div style="margin-top:16px;">
                    <h3>Source Audit Findings (${fmt(data.files_scanned)} files scanned)</h3>
                    <div style="font-size:13px; margin-bottom:12px;"><b>Frameworks:</b> ${Object.entries(data.frameworks || {}).map(([k, v]) => `${k} (${v})`).join(", ") || "None"}</div>
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr><th>Severity</th><th>Category</th><th>File</th><th>Message</th></tr>
                            </thead>
                            <tbody>
                                ${(data.findings || []).slice(0, 40).map(f => `
                                    <tr>
                                        <td><span class="pill pill-${f.severity || 'info'}">${esc(f.severity)}</span></td>
                                        <td>${esc(f.category)}</td>
                                        <td><code>${esc(f.file)}</code></td>
                                        <td>${esc(f.message)}</td>
                                    </tr>
                                `).join("") || '<tr><td colspan="4" class="empty-state">No source findings.</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        } catch (e) {
            resBox.innerHTML = `<div class="text-danger">Source audit error: ${esc(e.message)}</div>`;
        }
    }

    /* -------------------------------------------------------------
       SALES LEAD NOTES
    -------------------------------------------------------------- */
    async loadLeadNotes(leadId) {
        try {
            const notes = await jsonFetch(`${API_BASE}/leads/${leadId}/notes`);
            const notesListEl = $("leadNotesList");
            if (!notesListEl) return;
            if (!notes || !notes.length) {
                notesListEl.innerHTML = `<div style="font-size:12px; color:var(--text-muted); font-style:italic;">No sales notes recorded yet. Add a note below.</div>`;
                return;
            }
            notesListEl.innerHTML = notes.map(n => `
                <div style="background:#FFFFFF; border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <b style="font-size:12px; color:var(--text);">${esc(n.author_name || n.author_email || 'Team Member')}</b>
                        <span style="font-size:11px; color:var(--text-muted);">${n.created_at ? new Date(n.created_at).toLocaleString() : ''}</span>
                    </div>
                    <div style="font-size:13px; color:var(--text); white-space:pre-wrap;">${esc(n.note)}</div>
                </div>
            `).join("");
        } catch (err) {
            console.error("Load lead notes error:", err);
            const notesListEl = $("leadNotesList");
            if (notesListEl) notesListEl.innerHTML = `<div style="font-size:12px; color:var(--text-muted);">Could not load notes.</div>`;
        }
    }

    async handleAddLeadNote(leadId) {
        const input = $("newLeadNoteInput");
        const note = input ? input.value.trim() : "";
        if (!note) return;
        try {
            await jsonFetch(`${API_BASE}/leads/${leadId}/notes`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ note })
            });
            if (input) input.value = "";
            await this.loadLeadNotes(leadId);
        } catch (err) {
            alert("Failed to add note: " + err.message);
        }
    }

    /* -------------------------------------------------------------
       TEAM MEMBERS & USER MANAGEMENT (SUPER ADMIN / ADMIN)
    -------------------------------------------------------------- */
    async loadTeamUsers() {
        if (!this.hasPermission("admin_users.view")) return;
        const tbody = $("usersTableBody");
        if (!tbody) return;

        try {
            const users = await jsonFetch(`${API_BASE}/admin/users`);
            this.state.users = users || [];
            this.renderUsersTable(this.state.users);
        } catch (err) {
            console.error("Load users error:", err);
            tbody.innerHTML = `<tr><td colspan="7" class="empty-state text-danger">Failed to load team members: ${esc(err.message)}</td></tr>`;
        }
    }

    renderUsersTable(users) {
        const tbody = $("usersTableBody");
        if (!tbody) return;
        if (!users || !users.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No team members found.</td></tr>`;
            return;
        }

        const isSuperAdmin = this.state.role === "SUPER_ADMIN";
        const canEdit = this.hasPermission("admin_users.edit");
        const canDisable = this.hasPermission("admin_users.disable");
        const canChangeRole = this.hasPermission("admin_users.change_role");

        tbody.innerHTML = users.map(u => {
            const roleNorm = (u.role || "SALES").toLowerCase().replace(/_/g, "-");
            const roleClass = `role-${roleNorm}`;
            const roleLabel = (u.role || "").replace(/_/g, " ");

            const statusNorm = (u.status || "ACTIVE").toLowerCase();
            const statusClass = `status-${statusNorm}`;
            const statusLabel = u.status || "ACTIVE";

            const initials = (u.name || u.email || "U").substring(0, 2).toUpperCase();
            const created = u.created_at ? new Date(u.created_at).toLocaleDateString() : "-";
            const lastLogin = u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never";

            const isCurrentMe = u.email === this.state.adminEmail;

            let actionButtons = [];
            // Super Admin manages everyone; Admin manages Sales and SEO Analyst members only (enforced by the backend too).
            const manageable = !isCurrentMe && this.canManageRole(u.role);
            const nameArg = esc(JSON.stringify(u.name || u.email));

            if (canChangeRole && (manageable || (isSuperAdmin && isCurrentMe))) {
                actionButtons.push(`<button class="btn btn-secondary btn-xs" onclick="app.openChangeRoleModal(${u.id}, ${nameArg}, '${u.role}')" title="Change Role">Role</button>`);
            }

            if (canDisable && manageable) {
                if (u.status === "ACTIVE") {
                    actionButtons.push(`<button class="btn btn-secondary btn-xs text-danger" onclick="app.toggleUserStatus(${u.id}, 'SUSPENDED')" title="Block this member from signing in">Suspend</button>`);
                } else if (u.status === "SUSPENDED") {
                    actionButtons.push(`<button class="btn btn-success btn-xs" onclick="app.toggleUserStatus(${u.id}, 'ACTIVE')" title="Allow this member to sign in again">Activate</button>`);
                }
            }

            if (this.hasPermission("admin_users.reset_access") && manageable) {
                actionButtons.push(`<button class="btn btn-primary btn-xs" onclick="app.setUserPassword(${u.id}, ${nameArg})" title="Set a password and activate the account now">Set Password</button>`);
                actionButtons.push(`<button class="btn btn-secondary btn-xs" onclick="app.resetUserAccess(${u.id})" title="Create a new one-time link where they choose their own password">Invite Link</button>`);
            }

            if (this.hasPermission("admin_users.delete") && manageable) {
                actionButtons.push(`<button class="btn btn-danger btn-xs" onclick="app.deleteUser(${u.id}, ${nameArg})" title="Deactivate & Delete">Delete</button>`);
            }

            return `
                <tr>
                    <td>
                        <div class="user-cell">
                            <div class="user-avatar">${esc(initials)}</div>
                            <div>
                                <b style="font-size:13px;">${esc(u.name || "Unnamed")}</b>
                                ${isCurrentMe ? '<span style="font-size:10px; color:var(--primary); font-weight:700; margin-left:4px;">(You)</span>' : ''}
                            </div>
                        </div>
                    </td>
                    <td><a href="mailto:${esc(u.email)}" style="color:var(--text); text-decoration:none; font-size:13px;">${esc(u.email)}</a></td>
                    <td><span class="role-badge ${roleClass}">${esc(roleLabel)}</span></td>
                    <td><span class="status-badge ${statusClass}">${esc(statusLabel)}</span></td>
                    <td><span style="font-size:12px; color:var(--text-muted);">${esc(lastLogin)}</span></td>
                    <td><span style="font-size:12px; color:var(--text-muted);">${esc(created)}</span></td>
                    <td>
                        <div style="display:flex; gap:4px; flex-wrap:wrap;">
                            ${actionButtons.join("") || '<span style="font-size:11px; color:var(--text-muted);">-</span>'}
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    canManageRole(role) {
        const myRole = (this.state?.role || "SUPER_ADMIN").toUpperCase();
        if (myRole === "SUPER_ADMIN") return true;
        if (myRole === "ADMIN") return role === "SALES" || role === "SEO_ANALYST";
        return false;
    }

    async setUserPassword(userId, userName) {
        const password = prompt(`Set a new password for "${userName}" (at least 8 characters).\nTheir account will be active immediately and they will be signed out of other devices.`);
        if (password === null) return;
        if (password.length < 8) return alert("Password must be at least 8 characters.");
        try {
            const resp = await jsonFetch(`${API_BASE}/admin/users/${userId}/set-password`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password })
            });
            const details = `Login page: ${resp.login_url}\nEmail: ${resp.email}\nPassword: ${password}`;
            navigator.clipboard.writeText(details).catch(() => {});
            alert(`Password set. Send these login details to the team member (copied to clipboard):\n\n${details}`);
            await this.loadTeamUsers();
        } catch (err) {
            alert("Failed to set password: " + err.message);
        }
    }

    filterUsers() {
        const q = ($("userSearchInput")?.value || "").toLowerCase().trim();
        if (!q) {
            this.renderUsersTable(this.state.users);
            return;
        }
        const filtered = this.state.users.filter(u =>
            (u.name || "").toLowerCase().includes(q) ||
            (u.email || "").toLowerCase().includes(q) ||
            (u.role || "").toLowerCase().includes(q) ||
            (u.status || "").toLowerCase().includes(q)
        );
        this.renderUsersTable(filtered);
    }

    openInviteUserModal() {
        $("inviteAlertBox").style.display = "none";
        $("inviteNameInput").value = "";
        $("inviteEmailInput").value = "";
        $("inviteRoleSelect").value = "SALES";
        $("superAdminConfirmWrap").classList.add("hidden");
        $("inviteConfirmSuperAdmin").checked = false;
        $("inviteSuccessBanner").classList.add("hidden");
        // Only offer roles this user is allowed to create.
        Array.from($("inviteRoleSelect").options).forEach(o => { o.hidden = o.disabled = !this.canManageRole(o.value); });
        document.querySelector('input[name="inviteAccessMode"][value="password"]').checked = true;
        $("invitePasswordInput").value = "";
        this.handleInviteModeChange();
        this.handleInviteRoleChange();
        $("inviteUserModal").classList.remove("hidden");
    }

    closeInviteUserModal() {
        $("inviteUserModal").classList.add("hidden");
    }

    inviteMode() {
        return document.querySelector('input[name="inviteAccessMode"]:checked')?.value || "password";
    }

    handleInviteModeChange() {
        const mode = this.inviteMode();
        $("invitePasswordWrap").classList.toggle("hidden", mode !== "password");
        $("invitePasswordInput").required = mode === "password";
        $("sendInviteBtn").disabled = false;
        $("sendInviteBtn").innerHTML = mode === "password" ? "<span>Create Account</span>" : "<span>Create Invitation Link</span>";
    }

    generateInvitePassword() {
        const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
        const bytes = crypto.getRandomValues(new Uint32Array(12));
        $("invitePasswordInput").value = Array.from(bytes, b => chars[b % chars.length]).join("");
    }

    handleInviteRoleChange() {
        const role = $("inviteRoleSelect").value;
        const help = {
            ADMIN: "Can run audits, manage clients, leads and reports, and add Sales / SEO Analyst members. Cannot delete data or manage admins.",
            SALES: "Can see leads and clients, contact and convert leads, and view published reports. Cannot run audits or manage the team.",
            SEO_ANALYST: "Can run audits, see technical reports, keywords and issues, and generate reports. Cannot manage leads or the team.",
            SUPER_ADMIN: "Full access to everything, including deleting data and managing all team members.",
        };
        $("inviteRoleHelp").textContent = help[role] || "";
        if (role === "SUPER_ADMIN") {
            $("superAdminConfirmWrap").classList.remove("hidden");
        } else {
            $("superAdminConfirmWrap").classList.add("hidden");
        }
    }

    async handleInviteUser(e) {
        if (e) e.preventDefault();
        const name = $("inviteNameInput").value.trim();
        const email = $("inviteEmailInput").value.trim();
        const role = $("inviteRoleSelect").value;
        const confirmSuper = $("inviteConfirmSuperAdmin")?.checked || false;
        const alertBox = $("inviteAlertBox");
        const submitBtn = $("sendInviteBtn");

        if (role === "SUPER_ADMIN" && !confirmSuper) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = "Please check the box to confirm granting Super Admin privileges.";
            return;
        }

        const mode = this.inviteMode();
        const password = $("invitePasswordInput").value;
        if (mode === "password" && password.length < 8) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = "Please enter a password of at least 8 characters, or click Generate.";
            return;
        }

        alertBox.style.display = "none";
        submitBtn.disabled = true;
        submitBtn.innerHTML = "<span>Creating...</span>";

        try {
            const resp = await jsonFetch(`${API_BASE}/admin/users/invite`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, email, role, confirm_super_admin: confirmSuper, password: mode === "password" ? password : null })
            });

            $("inviteSuccessBanner").classList.remove("hidden");
            if (resp.mode === "password") {
                $("inviteSuccessTitle").textContent = "✓ Account created. They can sign in now.";
                $("inviteSuccessHint").textContent = "Send these login details to the team member:";
                $("inviteLinkBoxInput").value = `Login page: ${resp.login_url}\nEmail: ${resp.email}\nPassword: ${password}`;
            } else {
                $("inviteSuccessTitle").textContent = "✓ Invitation link created";
                $("inviteSuccessHint").textContent = "Send this one-time link to the team member (valid 48 hours). They will choose their own password:";
                $("inviteLinkBoxInput").value = this.absoluteUrl(resp.activation_url || `/admin?invite_token=${resp.invitation_token}`);
            }
            await this.loadTeamUsers();
        } catch (err) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = err.message || "Failed to add team member.";
        } finally {
            this.handleInviteModeChange();
        }
    }

    absoluteUrl(url) {
        return /^https?:\/\//i.test(url || "") ? url : `${window.location.origin}${url || ""}`;
    }

    copyInviteLink() {
        const text = $("inviteLinkBoxInput").value;
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            alert("Copied to clipboard!\n\n" + text);
        }).catch(() => {
            prompt("Copy this:", text);
        });
    }

    openChangeRoleModal(userId, userName, currentRole) {
        $("changeRoleAlertBox").style.display = "none";
        $("changeRoleUserId").value = userId;
        $("changeRoleUserName").value = userName;
        Array.from($("changeRoleSelect").options).forEach(o => { o.hidden = o.disabled = !this.canManageRole(o.value) && o.value !== currentRole; });
        $("changeRoleSelect").value = currentRole;
        $("changeRoleSuperAdminConfirmWrap").classList.add("hidden");
        $("changeRoleConfirmSuperAdmin").checked = false;
        $("changeRoleModal").classList.remove("hidden");
    }

    closeChangeRoleModal() {
        $("changeRoleModal").classList.add("hidden");
    }

    handleChangeRoleRoleChange() {
        const role = $("changeRoleSelect").value;
        if (role === "SUPER_ADMIN") {
            $("changeRoleSuperAdminConfirmWrap").classList.remove("hidden");
        } else {
            $("changeRoleSuperAdminConfirmWrap").classList.add("hidden");
        }
    }

    async handleChangeRoleSubmit(e) {
        if (e) e.preventDefault();
        const userId = $("changeRoleUserId").value;
        const newRole = $("changeRoleSelect").value;
        const confirmSuper = $("changeRoleConfirmSuperAdmin")?.checked || false;
        const alertBox = $("changeRoleAlertBox");
        const submitBtn = $("saveRoleBtn");

        if (newRole === "SUPER_ADMIN" && !confirmSuper) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = "Please confirm promoting this user to Super Admin.";
            return;
        }

        alertBox.style.display = "none";
        submitBtn.disabled = true;

        try {
            await jsonFetch(`${API_BASE}/admin/users/${userId}/role`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ new_role: newRole, confirm_super_admin: confirmSuper })
            });
            this.closeChangeRoleModal();
            await this.loadTeamUsers();
        } catch (err) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = err.message || "Failed to change user role.";
        } finally {
            submitBtn.disabled = false;
        }
    }

    async toggleUserStatus(userId, newStatus) {
        if (!confirm(`Are you sure you want to change this user status to ${newStatus}?`)) return;
        try {
            await jsonFetch(`${API_BASE}/admin/users/${userId}/status`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            await this.loadTeamUsers();
        } catch (err) {
            alert("Failed to update status: " + err.message);
        }
    }

    async resetUserAccess(userId) {
        if (!confirm("Create a new one-time invitation link for this team member?\nThey will be signed out and must open the link to choose a new password.")) return;
        try {
            const resp = await jsonFetch(`${API_BASE}/admin/users/${userId}/reset-access`, {
                method: "POST"
            });
            const url = this.absoluteUrl(resp.activation_url || `/admin?invite_token=${resp.invitation_token}`);
            navigator.clipboard.writeText(url).then(() => {
                alert(`New activation link generated and copied to clipboard!\n\n${url}`);
            }).catch(() => {
                prompt("New activation link generated! Copy below:", url);
            });
            await this.loadTeamUsers();
        } catch (err) {
            alert("Failed to reset access: " + err.message);
        }
    }

    async deleteUser(userId, userName) {
        if (!confirm(`Are you sure you want to delete and deactivate "${userName}"?\nThis user will immediately lose access to all APIs.`)) return;
        try {
            await jsonFetch(`${API_BASE}/admin/users/${userId}`, {
                method: "DELETE"
            });
            await this.loadTeamUsers();
        } catch (err) {
            alert("Failed to delete user: " + err.message);
        }
    }

    /* -------------------------------------------------------------
       ACTIVITY LOGS (IMMUTABLE AUDIT TRAIL)
    -------------------------------------------------------------- */
    async loadActivityLogs() {
        if (!this.hasPermission("activity_logs.view")) return;
        const tbody = $("activityLogsTableBody");
        if (!tbody) return;

        try {
            const logs = await jsonFetch(`${API_BASE}/admin/activity-logs`);
            this.state.activityLogs = logs || [];

            if (!logs || !logs.length) {
                tbody.innerHTML = `<tr><td colspan="8" class="empty-state">No activity logs recorded yet.</td></tr>`;
                return;
            }

            tbody.innerHTML = logs.map(l => {
                const ts = l.created_at ? new Date(l.created_at).toLocaleString() : "-";
                const roleNorm = (l.user_role || "ADMIN").toLowerCase().replace(/_/g, "-");
                const roleClass = `role-${roleNorm}`;
                const isSuccess = (l.status || "SUCCESS") === "SUCCESS";
                const statusBadge = isSuccess
                    ? '<span class="status-badge status-active">SUCCESS</span>'
                    : '<span class="status-badge status-suspended">DENIED</span>';

                return `
                    <tr>
                        <td style="font-size:12px; color:var(--text-muted);">${esc(ts)}</td>
                        <td>
                            <b>${esc(l.user_name || "System")}</b>
                            <div style="font-size:11px; color:var(--text-muted);">${esc(l.user_email || "")}</div>
                        </td>
                        <td><span class="role-badge ${roleClass}">${esc((l.user_role || "").replace(/_/g, " "))}</span></td>
                        <td><span class="pill pill-primary">${esc(l.action)}</span></td>
                        <td><code>${esc(l.resource || "-")}</code></td>
                        <td style="font-size:12px;">${esc(l.details || "")}</td>
                        <td>${statusBadge}</td>
                        <td><code style="font-size:11px;">${esc(l.ip_address || "127.0.0.1")}</code></td>
                    </tr>
                `;
            }).join("");
        } catch (err) {
            tbody.innerHTML = `<tr><td colspan="8" class="empty-state text-danger">Failed to load activity logs: ${esc(err.message)}</td></tr>`;
        }
    }

    /* -------------------------------------------------------------
       MY PROFILE & CREDENTIAL MANAGEMENT
    -------------------------------------------------------------- */
    async loadProfile() {
        try {
            const prof = await jsonFetch(`${API_BASE}/admin/profile`);
            if ($("profileDisplayName")) $("profileDisplayName").textContent = prof.name || prof.email;
            if ($("profileDisplayEmail")) $("profileDisplayEmail").textContent = prof.email;
            if ($("profileNameInput")) $("profileNameInput").value = prof.name || "";
            if ($("profileEmailInput")) $("profileEmailInput").value = prof.email;
            if ($("profileLastLogin")) $("profileLastLogin").value = prof.last_login_at ? new Date(prof.last_login_at).toLocaleString() : "Never";

            const roleBadge = $("profileRoleBadge");
            if (roleBadge) {
                const roleNorm = (prof.role || "SALES").toLowerCase().replace(/_/g, "-");
                roleBadge.className = `role-badge role-${roleNorm}`;
                roleBadge.textContent = prof.role.replace(/_/g, " ");
            }

            const statusBadge = $("profileStatusBadge");
            if (statusBadge) {
                const statusNorm = (prof.status || "ACTIVE").toLowerCase();
                statusBadge.className = `status-badge status-${statusNorm}`;
                statusBadge.textContent = prof.status;
            }

            const initials = (prof.name || prof.email || "U").substring(0, 2).toUpperCase();
            if ($("profileAvatar")) $("profileAvatar").textContent = initials;
        } catch (err) {
            console.error("Load profile error:", err);
        }
    }

    async handleSaveProfile(e) {
        if (e) e.preventDefault();
        const name = $("profileNameInput").value.trim();
        const alertBox = $("profileAlertBox");
        const submitBtn = $("saveProfileBtn");

        submitBtn.disabled = true;
        try {
            const updated = await jsonFetch(`${API_BASE}/admin/profile`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name })
            });
            this.state.adminName = updated.name;
            if ($("sidebarAdminName")) $("sidebarAdminName").textContent = updated.name;
            if ($("profileDisplayName")) $("profileDisplayName").textContent = updated.name;
            alertBox.style.display = "block";
            alertBox.className = "login-alert-success";
            alertBox.textContent = "Profile updated successfully!";
            setTimeout(() => { if (alertBox) alertBox.style.display = "none"; }, 3000);
        } catch (err) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = err.message || "Failed to update profile.";
        } finally {
            submitBtn.disabled = false;
        }
    }

    async handleChangePassword(e) {
        if (e) e.preventDefault();
        const current_password = $("currentPasswordInput").value;
        const new_password = $("newPasswordInput").value;
        const confirm = $("confirmPasswordInput").value;
        const alertBox = $("passwordAlertBox");
        const submitBtn = $("changePasswordBtn");

        if (new_password !== confirm) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = "New passwords do not match.";
            return;
        }

        submitBtn.disabled = true;
        try {
            await jsonFetch(`${API_BASE}/admin/profile/password`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ current_password, new_password })
            });
            alertBox.style.display = "block";
            alertBox.className = "login-alert-success";
            alertBox.textContent = "Password changed successfully!";
            $("currentPasswordInput").value = "";
            $("newPasswordInput").value = "";
            $("confirmPasswordInput").value = "";
            setTimeout(() => { if (alertBox) alertBox.style.display = "none"; }, 4000);
        } catch (err) {
            alertBox.style.display = "block";
            alertBox.className = "login-alert-danger";
            alertBox.textContent = err.message || "Failed to change password.";
        } finally {
            submitBtn.disabled = false;
        }
    }
}

const app = new SEOAdminApp();
window.app = app;
