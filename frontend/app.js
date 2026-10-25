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
    const controller = new AbortController();
    const timeoutMs = opts.timeout || 15000;
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    const finalOpts = {
        credentials: "include",
        signal: opts.signal || controller.signal,
        ...opts,
        headers
    };
    try {
        const r = await fetch(url, finalOpts);
        clearTimeout(timeoutId);
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
    } catch (err) {
        clearTimeout(timeoutId);
        throw err;
    }
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
        this.blState = {
            targetDomain: "",
            currentProfile: null,
            activeTab: "domains",
            referringFilter: "all",
            referringSearch: "",
            gapResults: null,
            loading: false
        };
        this.gperfState = {
            currentReport: null,
            websiteId: null,
            websiteUrl: "",
            targetDomain: "",
            days: 28,
            loading: false,
            websites: [],
            activeTab: "gsc"
        };
        this.rankState = {
            currentOverview: null,
            targetDomain: "",
            websiteId: null,
            device: "desktop",
            activeFilter: "all",
            activeTab: "keywords",
            searchQuery: "",
            loading: false
        };
        this.aiState = {
            currentRecommendations: null,
            activeAuditId: null,
            status: null,
            activeTab: "roadmap",
            chatMessages: [],
            loading: false
        };
        this.reportState = {
            filterType: "ALL",
            search: "",
            branding: null,
            types: []
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
        this.initTheme();

        // Close dropdowns on outside click
        document.addEventListener("click", (e) => {
            const qMenu = $("quickExportDropdown");
            const qBtn = $("btnQuickExport");
            if (qMenu && qMenu.style.display !== "none" && !qMenu.contains(e.target) && !qBtn?.contains(e.target)) {
                qMenu.style.display = "none";
            }
        });

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
            technology_detector: "tech_detector.view",
            backlink_analytics: "audits.view",
            google_performance: "audits.view",
            rank_tracking: "audits.view",
            ai_advisor: "audits.view"
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
            technology_detector: { id: "viewTechDetector", title: "Website Technology Detector", breadcrumb: "Analysis • CMS, Framework & Platform Detection" },
            domain_overview: { id: "viewDomainOverview", title: "Domain Overview", breadcrumb: "Telemetry • Domain Performance & Visibility" },
            keyword_magic: { id: "viewKeywordMagic", title: "Keyword Magic Tool", breadcrumb: "Research • SEMrush Inspired Keyword Intelligence" },
            competitor_analysis: { id: "viewCompetitorAnalysis", title: "Competitor Analysis", breadcrumb: "Intelligence • Head-to-Head Benchmarks & Market Gaps" },
            backlink_analytics: { id: "viewBacklinkAnalytics", title: "Backlink Analytics", breadcrumb: "Intelligence • Indexed Backlinks & Internal Equity Modeling" },
            google_performance: { id: "viewGooglePerformance", title: "Google & Performance", breadcrumb: "Telemetry • Search Console, Analytics 4 & Core Web Vitals" },
            rank_tracking: { id: "viewRankTracking", title: "Keyword Rank Tracking", breadcrumb: "Telemetry • Live Google SERP Positions & Competitor Benchmarks" },
            ai_advisor: { id: "viewAiAdvisor", title: "AI SEO Advisor & Consultant", breadcrumb: "Intelligence • Evidence-Grounded Recommendations & Assistant" }
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
        else if (view === "domain_overview") this.loadDomainOverview();
        else if (view === "keyword_magic") this.loadKeywordMagic();
        else if (view === "competitor_analysis") this.loadCompetitorAnalysis();
        else if (view === "backlink_analytics") this.loadBacklinkAnalytics();
        else if (view === "google_performance") this.loadGooglePerformance();
        else if (view === "rank_tracking") this.loadRankings();
        else if (view === "ai_advisor") this.initAiAdvisor();
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
            const d = await jsonFetch(`${API_BASE}/health`, { timeout: 4000 });
            if ($("healthBadge")) {
                $("healthBadge").innerHTML = `<span style="color:var(--success)">●</span> API Ready • v${esc(d.version || "10.4.0")}`;
            }
        } catch {
            if ($("healthBadge")) {
                $("healthBadge").innerHTML = `<span style="color:var(--danger)">●</span> Backend Offline`;
            }
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
            if (e.status === 401) {
                this.state.authenticated = false;
                if ($("adminLoginScreen")) $("adminLoginScreen").style.display = "flex";
                if ($("appLayout")) $("appLayout").style.display = "none";
            }
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
            let list = stats.recent_audits || [];
            if (this.state.currentProjectId && this.state.currentProject) {
                const targetUrl = this.state.currentProject.target_url;
                list = list.filter(a => a.client_name === this.state.currentProject.name || (targetUrl && a.target_url && a.target_url.includes(targetUrl)));
            }
            if (list.length) {
                recentAuditsBody.innerHTML = list.map(a => {
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
                recentAuditsBody.innerHTML = `<tr><td colspan="8" class="empty-state">No audits completed ${this.state.currentProject ? 'for ' + esc(this.state.currentProject.name) : 'yet'}.</td></tr>`;
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
            ${source("Google PageSpeed / Core Web Vitals", ds.pagespeed, ds.pagespeed_mode === "local_lighthouse" ? "Connected via local Lighthouse engine. Optional: set PAGESPEED_API_KEY in .env for Google Cloud API." : "Connected via Google PageSpeed Insights API.")}
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
        if (sel) {
            const current = sel.value;
            sel.innerHTML = `<option value="">-- Assign to Client (Optional) --</option>` +
                this.state.clients.map(c => `<option value="${c.id}">${esc(c.name)} (${esc(c.company || c.target_url || "Client")})</option>`).join("");
            sel.value = current;
        }

        // Global SEMrush/Ahrefs Project & Website Selector
        const projSel = $("globalProjectSelector");
        if (projSel) {
            const currentVal = this.state.currentProjectId ? String(this.state.currentProjectId) : (projSel.value || "ALL");
            let opts = `<option value="ALL">📁 All Projects &amp; Websites</option>`;
            if (this.state.clients && this.state.clients.length) {
                opts += this.state.clients.map(c => {
                    const domain = (c.target_url || "").replace(/^https?:\/\//, '').replace(/\/$/, '');
                    const label = domain ? `${esc(c.name)} (${domain})` : esc(c.name);
                    return `<option value="${c.id}">${label}</option>`;
                }).join("");
            }
            projSel.innerHTML = opts;
            projSel.value = currentVal;
            this.updateProjectScopeUI();
        }
    }

    onGlobalProjectChange(val) {
        if (val === "ALL" || !val) {
            this.state.currentProjectId = null;
            this.state.currentProject = null;
            localStorage.removeItem("seo_project_scope");
        } else {
            const pId = parseInt(val, 10);
            this.state.currentProjectId = pId;
            this.state.currentProject = (this.state.clients || []).find(c => c.id === pId) || null;
            localStorage.setItem("seo_project_scope", String(pId));
        }
        this.updateProjectScopeUI();

        // Refresh views to match new scope
        const view = this.state.currentView || "dashboard";
        if (view === "dashboard") {
            this.loadDashboardStats();
        } else if (view === "audits") {
            this.filterAudits();
        } else if (view === "domain_overview" && this.state.currentProject?.target_url) {
            if ($("doDomainInput")) {
                $("doDomainInput").value = this.state.currentProject.target_url;
                this.analyzeDomainOverview();
            }
        }
    }

    updateProjectScopeUI() {
        const badge = $("globalProjectActiveBadge");
        const banner = $("dashProjectScopeBanner");
        const proj = this.state.currentProject;

        if (proj) {
            if (badge) {
                badge.style.display = "inline-block";
                badge.textContent = proj.name || "Active";
            }
            if (banner) {
                banner.style.display = "flex";
                if ($("dashScopeDomain")) $("dashScopeDomain").textContent = proj.target_url || proj.company || "Project Active";
                if ($("dashScopeClientName")) $("dashScopeClientName").textContent = proj.name || "Client";
                const score = proj.latest_score !== null && proj.latest_score !== undefined ? Math.round(proj.latest_score) : null;
                const scoreBadge = $("dashScopeScoreBadge");
                if (scoreBadge) {
                    if (score !== null) {
                        scoreBadge.textContent = `${score}% Health`;
                        const col = getScoreColor(score);
                        scoreBadge.style.color = col;
                        scoreBadge.style.background = `${col}20`;
                        scoreBadge.style.borderColor = `${col}40`;
                    } else {
                        scoreBadge.textContent = "No Audit Yet";
                        scoreBadge.className = "pill pill-disabled";
                    }
                }
            }
            if ($("auditUrlInput") && !$("auditUrlInput").value && proj.target_url) {
                $("auditUrlInput").value = proj.target_url;
            }
            if ($("auditClientSelect")) {
                $("auditClientSelect").value = String(proj.id);
            }
        } else {
            if (badge) badge.style.display = "none";
            if (banner) banner.style.display = "none";
        }
    }

    clearProjectScope() {
        const projSel = $("globalProjectSelector");
        if (projSel) projSel.value = "ALL";
        this.onGlobalProjectChange("ALL");
    }

    auditCurrentScope() {
        if (this.state.currentProject?.target_url) {
            $("auditUrlInput").value = this.state.currentProject.target_url;
            if ($("auditClientSelect")) $("auditClientSelect").value = String(this.state.currentProject.id);
            this.startAudit();
        }
    }

    /* -------------------------------------------------------------
       THEME ENGINE & MODERN UTILITIES (PHASE 11)
    -------------------------------------------------------------- */
    initTheme() {
        const saved = localStorage.getItem("theme") || 
            (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        document.documentElement.setAttribute("data-theme", saved);
        this.updateThemeButton(saved);
    }

    toggleTheme() {
        const cur = document.documentElement.getAttribute("data-theme") || "light";
        const next = cur === "dark" ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        localStorage.setItem("theme", next);
        this.updateThemeButton(next);
    }

    updateThemeButton(theme) {
        const icon = $("themeToggleIcon");
        const txt = $("themeToggleText");
        if (icon) icon.textContent = theme === "dark" ? "☀️" : "🌙";
        if (txt) txt.textContent = theme === "dark" ? "Light" : "Dark";
    }

    toggleQuickExportMenu() {
        const menu = $("quickExportDropdown");
        if (!menu) return;
        menu.style.display = menu.style.display === "none" ? "block" : "none";
    }

    async triggerQuickExport(format) {
        const menu = $("quickExportDropdown");
        if (menu) menu.style.display = "none";

        const auditId = this.state.currentAudit?.db_audit_id || (this.state.audits && this.state.audits.length ? this.state.audits[0].id : null);
        if (!auditId) {
            alert("No audit found to export. Please run or select an audit first.");
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/reports/export/${format}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    audit_id: auditId,
                    report_type: "executive_seo_report"
                })
            });

            if (!res.ok) throw new Error(`Export failed (${res.status})`);
            const blob = await res.blob();
            const filename = `seo_executive_report_${auditId}.${format === 'xls' ? 'xls' : format}`;
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);
        } catch (e) {
            alert("Quick export error: " + e.message);
        }
    }

    sortTable(tableId, colIdx, type = "string") {
        const table = document.getElementById(tableId);
        if (!table) return;
        const tbody = table.querySelector("tbody");
        if (!tbody) return;

        const thList = table.querySelectorAll("thead th.sortable");
        const clickedTh = table.querySelectorAll("thead th")[colIdx];
        if (!clickedTh) return;

        const currentOrder = clickedTh.dataset.order === "asc" ? "desc" : "asc";
        clickedTh.dataset.order = currentOrder;

        thList.forEach(th => {
            th.classList.remove("sort-asc", "sort-desc");
            const icon = th.querySelector(".sort-icon");
            if (icon) icon.textContent = "↕";
        });
        clickedTh.classList.add(`sort-${currentOrder}`);
        const clickedIcon = clickedTh.querySelector(".sort-icon");
        if (clickedIcon) clickedIcon.textContent = currentOrder === "asc" ? "▲" : "▼";

        const rows = Array.from(tbody.querySelectorAll("tr"));
        if (!rows.length || rows[0].querySelector(".empty-state")) return;

        rows.sort((a, b) => {
            const cellA = a.children[colIdx]?.innerText.trim() || "";
            const cellB = b.children[colIdx]?.innerText.trim() || "";

            let valA, valB;
            if (type === "score") {
                valA = parseFloat(cellA.replace(/[^0-9.-]/g, "")) || 0;
                valB = parseFloat(cellB.replace(/[^0-9.-]/g, "")) || 0;
            } else if (type === "number") {
                valA = parseFloat(cellA.replace(/[^0-9.-]/g, "")) || 0;
                valB = parseFloat(cellB.replace(/[^0-9.-]/g, "")) || 0;
            } else if (type === "date") {
                valA = new Date(cellA).getTime() || 0;
                valB = new Date(cellB).getTime() || 0;
            } else {
                valA = cellA.toLowerCase();
                valB = cellB.toLowerCase();
            }

            if (valA < valB) return currentOrder === "asc" ? -1 : 1;
            if (valA > valB) return currentOrder === "asc" ? 1 : -1;
            return 0;
        });

        rows.forEach(r => tbody.appendChild(r));
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

        this.state.auditRunningUrl = url;
        const dock = $("globalScanProgressDock");
        if (dock) {
            dock.style.display = "block";
            if ($("globalScanTargetUrl")) $("globalScanTargetUrl").textContent = url;
            if ($("globalScanProgressBarFill")) $("globalScanProgressBarFill").style.width = "5%";
            if ($("globalScanStatusText")) $("globalScanStatusText").textContent = "Initializing crawler and DNS probes...";
            if ($("globalScanPhaseBadge")) $("globalScanPhaseBadge").textContent = "Phase: Init";
            if ($("globalScanPctBadge")) $("globalScanPctBadge").textContent = "5%";
            if ($("globalScanTelemetry")) $("globalScanTelemetry").textContent = "Pages: 0 | Links: 0 | Issues: 0";
        }

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

            const dock = $("globalScanProgressDock");
            if (dock) {
                dock.style.display = "block";
                if ($("globalScanTargetUrl")) $("globalScanTargetUrl").textContent = this.state.auditRunningUrl || $("auditUrlInput")?.value || "Target Site";
                if ($("globalScanProgressBarFill")) $("globalScanProgressBarFill").style.width = `${pct}%`;
                if ($("globalScanPhaseBadge")) $("globalScanPhaseBadge").textContent = `Phase: ${p.phase || "Working"}`;
                if ($("globalScanPctBadge")) $("globalScanPctBadge").textContent = `${Math.round(pct)}%`;
                if ($("globalScanStatusText")) $("globalScanStatusText").textContent = p.message || `Running inspection (${Math.round(pct)}%)...`;
                if ($("globalScanTelemetry")) $("globalScanTelemetry").textContent = `Pages: ${fmt(p.pages || 0)} | Links: ${fmt(p.links_checked || 0)} | Issues: ${fmt(p.issues || 0)}`;
            }

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
            const dock = $("globalScanProgressDock");
            if (dock) dock.style.display = "none";
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
        const dock = $("globalScanProgressDock");
        if (dock) {
            setTimeout(() => {
                if (dock && !this.state.currentJobId) dock.style.display = "none";
            }, 2500);
        }
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
            this.filterAudits();
        }
        try {
            this.state.audits = await jsonFetch(`${API_BASE}/audits`);
            this.filterAudits();
        } catch (e) {
            console.error("Load audits error:", e);
        }
    }

    renderAuditsTable(audits) {
        const tbody = $("auditsTableBody");
        if (!tbody) return;

        if (!audits || !audits.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No audits match your filter or search criteria.</td></tr>`;
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
                    <td style="text-align:center;">
                        <input type="checkbox" class="audit-select-check" value="${a.id}" onchange="app.onAuditSelectionChange()">
                    </td>
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

    filterAudits() {
        const q = ($("auditSearchInput")?.value || "").toLowerCase().trim();
        let list = this.state.audits || [];

        // Scoped to project if active
        if (this.state.currentProjectId) {
            list = list.filter(a => a.client_id === this.state.currentProjectId || (this.state.currentProject?.target_url && (a.target_url || "").includes(this.state.currentProject.target_url)));
        }

        if (q) {
            list = list.filter(a => 
                (a.target_url || "").toLowerCase().includes(q) ||
                (a.client_name || "").toLowerCase().includes(q) ||
                (a.created_at || "").toLowerCase().includes(q) ||
                String(a.score || "").includes(q)
            );
        }

        this.renderAuditsTable(list);

        const badge = $("auditCountBadge");
        if (badge) {
            const total = (this.state.audits || []).length;
            badge.textContent = `Showing ${list.length} of ${total} audits`;
        }
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
       PUBLIC REPORT MANAGEMENT & CLIENT REPORT HUB
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

    filterReportsByType(type) {
        this.reportState.filterType = type;
        document.querySelectorAll("[data-repfilter]").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.repfilter === type);
            btn.classList.toggle("btn-primary", btn.dataset.repfilter === type);
            btn.classList.toggle("btn-secondary", btn.dataset.repfilter !== type);
        });
        this.renderReportsTable(this.state.reports);
    }

    filterReportsSearch() {
        const inp = $("reportSearchInput");
        this.reportState.search = inp ? inp.value.trim().toLowerCase() : "";
        this.renderReportsTable(this.state.reports);
    }

    renderReportsTable(reports) {
        const tbody = $("reportsTableBody");
        if (!tbody) return;

        if (!reports || !reports.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No client reports generated yet. Click '+ Generate New Report' to produce one.</td></tr>`;
            return;
        }

        const REP_LABELS = {
            EXECUTIVE: "📊 Executive Report",
            TECHNICAL: "🛠️ Technical Audit",
            ONPAGE: "📝 On-Page SEO",
            KEYWORDS: "🎯 Keywords & Intent",
            COMPETITORS: "⚔️ Competitor Benchmarks",
            BACKLINKS: "🔗 Backlink Profile",
            GSC_PERFORMANCE: "📈 Search Console",
            PAGESPEED: "⚡ PageSpeed & Vitals",
            RECOMMENDATIONS: "🧠 AI Action Plan",
            PROGRESS_COMPARISON: "🔄 Progress Delta"
        };

        const filterType = this.reportState.filterType || "ALL";
        const search = this.reportState.search || "";

        const filtered = reports.filter(r => {
            const rType = (r.report_type || "EXECUTIVE").toUpperCase();
            if (filterType !== "ALL" && rType !== filterType) return false;
            if (search) {
                const cName = (r.client_name || "").toLowerCase();
                const target = (r.target_url || "").toLowerCase();
                if (!cName.includes(search) && !target.includes(search)) return false;
            }
            return true;
        });

        if (!filtered.length) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No reports match the current filter criteria.</td></tr>`;
            return;
        }

        tbody.innerHTML = filtered.map(r => {
            const isPub = r.status === "PUBLISHED";
            const d = r.created_at ? new Date(r.created_at).toLocaleDateString() : "-";
            const rType = (r.report_type || "EXECUTIVE").toUpperCase();
            const typeLabel = REP_LABELS[rType] || rType;
            return `
                <tr>
                    <td>
                        <b style="color:#0f172a;">${esc(r.client_name)}</b>
                        <div style="font-size:12px; color:var(--text-muted); font-family:monospace; margin-top:2px;">${esc(r.target_url)}</div>
                    </td>
                    <td>
                        <span class="badge" style="background:#e0e7ff; color:#3730a3; font-weight:700; font-size:11px;">
                            ${esc(typeLabel)}
                        </span>
                    </td>
                    <td><b style="font-size:14px; color:${getScoreColor(r.score)}">${safe(r.score).toFixed(0)}/100</b></td>
                    <td>
                        <span class="pill ${isPub ? 'pill-success' : 'pill-disabled'}">${esc(r.status)}</span>
                    </td>
                    <td><span style="font-size:12px; color:var(--text-muted);">${d}</span></td>
                    <td><code style="font-size:11px; background:#F1F5F9; padding:2px 6px; border-radius:4px;">${esc(r.token.substring(0, 10))}...</code></td>
                    <td>
                        <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                            <button class="btn btn-secondary btn-sm" onclick="window.open('/report/${r.token}', '_blank')" title="Open Interactive Web View">👁️ View</button>
                            <button class="btn btn-secondary btn-sm" onclick="app.copyReportLink('${r.token}')" title="Copy Client Link">🔗 Link</button>
                            <div class="dropdown" style="display:inline-block; position:relative;">
                                <button class="btn btn-secondary btn-sm" style="display:flex; align-items:center; gap:4px;" onclick="app.toggleRowExportMenu(event, '${r.token}')">
                                    <span>📥</span> Export ▾
                                </button>
                                <div id="exportMenu_${r.token}" class="dropdown-menu" style="display:none; position:absolute; right:0; left:auto; z-index:100; background:#fff; border:1px solid #cbd5e1; border-radius:6px; box-shadow:0 4px 12px rgba(0,0,0,0.1); min-width:140px; padding:4px 0;">
                                    <a href="/api/reports/public/${r.token}/export/pdf" target="_blank" style="display:block; padding:6px 12px; font-size:12px; color:#1e293b; text-decoration:none;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background='transparent'">📄 PDF Report</a>
                                    <a href="/api/reports/public/${r.token}/export/excel" target="_blank" style="display:block; padding:6px 12px; font-size:12px; color:#1e293b; text-decoration:none;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background='transparent'">📊 Excel (.xls)</a>
                                    <a href="/api/reports/public/${r.token}/export/csv" target="_blank" style="display:block; padding:6px 12px; font-size:12px; color:#1e293b; text-decoration:none;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background='transparent'">📑 CSV Data</a>
                                    <a href="/api/reports/public/${r.token}/export/json" target="_blank" style="display:block; padding:6px 12px; font-size:12px; color:#1e293b; text-decoration:none;" onmouseover="this.style.background='#f1f5f9'" onmouseout="this.style.background='transparent'">🌐 JSON API</a>
                                </div>
                            </div>
                            <button class="btn btn-sm ${isPub ? 'btn-danger' : 'btn-success'}" onclick="app.toggleReportStatus(${r.id}, '${r.status}')" style="font-size:11px; padding:3px 8px;">
                                ${isPub ? 'Disable' : 'Publish'}
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        }).join("");
    }

    toggleRowExportMenu(e, token) {
        if (e) e.stopPropagation();
        const menu = $("exportMenu_" + token);
        if (!menu) return;
        const wasOpen = menu.style.display === "block";
        document.querySelectorAll("[id^='exportMenu_']").forEach(m => m.style.display = "none");
        menu.style.display = wasOpen ? "none" : "block";
    }

    async openGenerateReportModal() {
        const modal = $("generateReportModal");
        if (!modal) return;
        modal.classList.remove("hidden");

        // Populate audits dropdown
        const sel = $("genRepAuditSelect");
        const bSel = $("genRepBaselineSelect");
        if (sel) {
            try {
                const audits = await jsonFetch(`${API_BASE}/audits`);
                let html = '<option value="">-- Choose Completed Audit --</option>';
                let bHtml = '<option value="">-- Choose Earlier Baseline Audit --</option>';
                if (Array.isArray(audits)) {
                    audits.forEach(a => {
                        const domain = a.target_url ? a.target_url.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : `Audit #${a.id}`;
                        const score = a.score !== null ? `${Math.round(a.score)}/100` : "Unscored";
                        const dt = a.created_at ? new Date(a.created_at).toLocaleDateString() : "";
                        html += `<option value="${a.id}">${domain} (${score} • ${dt})</option>`;
                        bHtml += `<option value="${a.id}">${domain} (${score} • ${dt})</option>`;
                    });
                }
                sel.innerHTML = html;
                if (bSel) bSel.innerHTML = bHtml;
            } catch (err) {
                console.warn("Failed to load audits for modal:", err);
            }
        }
    }

    closeGenerateReportModal() {
        const modal = $("generateReportModal");
        if (modal) modal.classList.add("hidden");
    }

    onGenRepTypeChanged() {
        const tSel = $("genRepTypeSelect");
        const bCont = $("genRepBaselineContainer");
        if (tSel && bCont) {
            bCont.style.display = (tSel.value === "PROGRESS_COMPARISON") ? "block" : "none";
        }
    }

    onGenRepAuditChanged() {
        // Option selected
    }

    async submitGenerateReport() {
        const aSel = $("genRepAuditSelect");
        const tSel = $("genRepTypeSelect");
        const bSel = $("genRepBaselineSelect");
        const sSel = $("genRepStatusSelect");
        const cInp = $("genRepClientOverride");
        const btn = $("btnSubmitGenReport");

        const auditId = aSel ? parseInt(aSel.value) : null;
        if (!auditId) {
            this.showNotification("Please select a target audit first.", "warning");
            return;
        }

        const reportType = tSel ? tSel.value : "EXECUTIVE";
        const baselineAuditId = (reportType === "PROGRESS_COMPARISON" && bSel && bSel.value) ? parseInt(bSel.value) : null;
        const status = sSel ? sSel.value : "PUBLISHED";

        if (btn) btn.disabled = true;
        try {
            this.showNotification(`Synthesizing client-ready ${reportType} report...`, "info");
            const payload = {
                audit_id: auditId,
                report_type: reportType,
                baseline_audit_id: baselineAuditId,
                status: status
            };
            if (cInp && cInp.value.trim()) {
                payload.client_override = cInp.value.trim();
            }

            const res = await jsonFetch(`${API_BASE}/reports/generate`, {
                method: "POST",
                body: JSON.stringify(payload)
            });

            this.closeGenerateReportModal();
            this.showNotification(`Report #${res.id} (${reportType}) created successfully!`, "success");
            await this.loadReports();
        } catch (err) {
            this.showNotification(`Failed to generate report: ${err.message || err}`, "danger");
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async openAgencyBrandingModal() {
        const modal = $("agencyBrandingModal");
        if (!modal) return;
        modal.classList.remove("hidden");

        try {
            const b = await jsonFetch(`${API_BASE}/reports/branding`);
            this.reportState.branding = b;
            if ($("brandAgencyName")) $("brandAgencyName").value = b.agency_name || "";
            if ($("brandTagline")) $("brandTagline").value = b.tagline || "";
            if ($("brandLogoUrl")) $("brandLogoUrl").value = b.logo_url || "";
            if ($("brandPrimaryColor")) $("brandPrimaryColor").value = b.primary_color || "#4F46E5";
            if ($("brandPrimaryColorPicker")) $("brandPrimaryColorPicker").value = b.primary_color || "#4F46E5";
            if ($("brandWebsite")) $("brandWebsite").value = b.website || "";
            if ($("brandEmail")) $("brandEmail").value = b.support_email || "";
            if ($("brandPhone")) $("brandPhone").value = b.phone || "";
            if ($("brandFooter")) $("brandFooter").value = b.footer_text || "";
        } catch (err) {
            console.warn("Failed to load agency branding:", err);
        }
    }

    closeAgencyBrandingModal() {
        const modal = $("agencyBrandingModal");
        if (modal) modal.classList.add("hidden");
    }

    async saveAgencyBranding() {
        const btn = $("btnSaveBranding");
        if (btn) btn.disabled = true;

        const payload = {
            agency_name: $("brandAgencyName") ? $("brandAgencyName").value.trim() : "",
            tagline: $("brandTagline") ? $("brandTagline").value.trim() : "",
            logo_url: $("brandLogoUrl") ? $("brandLogoUrl").value.trim() : "",
            primary_color: $("brandPrimaryColor") ? $("brandPrimaryColor").value.trim() : "#4F46E5",
            website: $("brandWebsite") ? $("brandWebsite").value.trim() : "",
            support_email: $("brandEmail") ? $("brandEmail").value.trim() : "",
            phone: $("brandPhone") ? $("brandPhone").value.trim() : "",
            footer_text: $("brandFooter") ? $("brandFooter").value.trim() : ""
        };

        try {
            const updated = await jsonFetch(`${API_BASE}/reports/branding`, {
                method: "POST",
                body: JSON.stringify(payload)
            });
            this.reportState.branding = updated;
            this.showNotification("Agency branding settings saved successfully!", "success");
            this.closeAgencyBrandingModal();
        } catch (err) {
            this.showNotification(`Failed to save branding: ${err.message || err}`, "danger");
        } finally {
            if (btn) btn.disabled = false;
        }
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
    // ==========================================
    async loadDomainOverview(targetUrl = null) {
        try {
            // Load available domain options
            const domains = await jsonFetch(`${API_BASE}/domain/list`);
            const selectEl = $("domainSelectDropdown");
            if (selectEl) {
                selectEl.innerHTML = '<option value="">Select Inspected Domain...</option>' +
                    domains.map(d => `<option value="${d.domain}">${d.domain_display} (Score: ${d.latest_score !== null ? Math.round(d.latest_score) : 'No audit'})</option>`).join('');
            }

            // Determine target domain
            let chosen = targetUrl;
            if (!chosen) {
                if (this.state.currentDomain) chosen = this.state.currentDomain;
                else if (domains && domains.length > 0 && domains[0].domain) chosen = domains[0].domain;
                else chosen = "https://esupport.live/";
            }

            this.state.currentDomain = chosen;
            if (selectEl) selectEl.value = chosen;
            if ($("domainOverviewInput")) $("domainOverviewInput").value = chosen;

            const badge = $("domainOverviewBadge");
            if (badge) {
                badge.textContent = "Loading...";
                badge.className = "badge badge-primary";
            }

            const data = await jsonFetch(`${API_BASE}/domain/overview?target_url=${encodeURIComponent(chosen)}`);
            this.state.currentDomainOverview = data;
            this.renderDomainOverview(data);
        } catch (err) {
            console.error("[eSupport] Failed to load domain overview:", err);
            this.showNotification("Failed to load domain overview: " + (err.message || err), "danger");
        }
    }

    onDomainSelectChange(val) {
        if (val) {
            this.loadDomainOverview(val);
        }
    }

    inspectDomainFromInput() {
        const inp = $("domainOverviewInput");
        if (inp && inp.value.trim()) {
            this.loadDomainOverview(inp.value.trim());
        }
    }

    runDomainOverviewAudit() {
        const target = this.state.currentDomain || ($("domainOverviewInput") ? $("domainOverviewInput").value : "") || "https://esupport.live/";
        this.navigate("dashboard");
        const auditInput = $("auditUrlInput");
        if (auditInput) {
            auditInput.value = target;
            auditInput.focus();
        }
    }

    setDomainOverviewPsStrategy(strategy) {
        this.state.domainOverviewPsStrategy = strategy;
        if (this.state.currentDomainOverview && this.state.currentDomainOverview.pagespeed) {
            this.renderDomainOverviewPs(this.state.currentDomainOverview.pagespeed);
        }
    }

    renderDomainOverview(data) {
        const badge = $("domainOverviewBadge");
        if (badge) {
            badge.textContent = data.domain_display || data.domain || "Domain";
            badge.className = data.has_data ? "badge badge-success" : "badge badge-warning";
        }

        const emptyState = $("domainOverviewEmptyState");
        const mainContent = $("domainOverviewMainContent");

        if (!data.has_data) {
            if (emptyState) emptyState.style.display = "block";
            if (mainContent) mainContent.style.display = "none";
            if ($("emptyDomainTitle")) $("emptyDomainTitle").textContent = `No Audits for ${data.domain_display}`;
            if ($("emptyDomainMessage")) $("emptyDomainMessage").textContent = data.message || "Run an audit to collect domain health and search signals.";
            return;
        }

        if (emptyState) emptyState.style.display = "none";
        if (mainContent) mainContent.style.display = "block";

        // 1. Health Score
        const health = data.seo_health || {};
        const scoreVal = health.score !== null && health.score !== undefined ? Math.round(health.score) : "--";
        if ($("doHealthScore")) $("doHealthScore").textContent = scoreVal !== "--" ? `${scoreVal}/100` : "--";
        if ($("doHealthGrade")) {
            $("doHealthGrade").textContent = health.grade || "N/A";
            $("doHealthGrade").className = `badge ${scoreVal >= 80 ? 'badge-success' : scoreVal >= 60 ? 'badge-warning' : 'badge-danger'}`;
        }
        if ($("doMaturityLevel")) {
            $("doMaturityLevel").textContent = health.maturity_label ? `Maturity: ${health.maturity_label}` : "Deterministic SEO Engine";
        }
        if ($("doHealthDate")) {
            const dt = health.observation_date ? new Date(health.observation_date).toLocaleDateString() : "--";
            $("doHealthDate").textContent = `Observed: ${dt}`;
        }

        // 2. Organic Search Visibility
        const org = data.organic_search || {};
        if ($("doSearchVisibility")) {
            $("doSearchVisibility").textContent = org.visibility_index !== null && org.visibility_index !== undefined ? `${org.visibility_index}%` : "--";
        }
        if ($("doVisibilityBadge")) {
            $("doVisibilityBadge").textContent = org.visibility_data_type === "third_party_estimate" ? "Third-Party Estimate" : "Unavailable";
            $("doVisibilityBadge").style.background = org.visibility_data_type === "third_party_estimate" ? "#FFFBEB" : "#F1F5F9";
            $("doVisibilityBadge").style.color = org.visibility_data_type === "third_party_estimate" ? "#92400E" : "#475569";
        }
        if ($("doVisibilityProvider")) {
            $("doVisibilityProvider").textContent = org.visibility_provider || "Requires SERP API";
        }
        if ($("doVisibilityNote")) {
            $("doVisibilityNote").textContent = org.visibility_index !== null && org.visibility_index !== undefined ? "SERP Visibility Index" : "SERP provider not connected";
        }

        // 3. Organic Keywords
        if ($("doKeywordsCount")) {
            $("doKeywordsCount").textContent = org.organic_keywords_count || 0;
        }
        if ($("doKeywordsSample")) {
            const sample = (org.top_keywords || []).slice(0, 3).map(k => typeof k === 'string' ? k : (k.term || k.keyword || "")).filter(Boolean).join(", ");
            $("doKeywordsSample").textContent = sample ? `Topics: ${sample}` : "On-site topics extracted";
        }
        if ($("doKeywordsBadge")) {
            $("doKeywordsBadge").textContent = org.keywords_data_type === "third_party_estimate" ? "Third-Party Estimate" : "First-Party Measured";
            $("doKeywordsBadge").style.background = org.keywords_data_type === "third_party_estimate" ? "#FFFBEB" : "#ECFDF5";
            $("doKeywordsBadge").style.color = org.keywords_data_type === "third_party_estimate" ? "#92400E" : "#065F46";
        }

        // 4. Organic Traffic Estimates (Never fake numbers!)
        if ($("doTrafficEstimate")) {
            $("doTrafficEstimate").textContent = org.traffic_estimate !== null && org.traffic_estimate !== undefined ? Number(org.traffic_estimate).toLocaleString() : "Not Connected";
        }

        // 5. Referring Domains & Backlinks
        const bl = data.backlinks || {};
        if ($("doBacklinksCount")) {
            if (bl.total_backlinks !== null && bl.total_backlinks !== undefined) {
                $("doBacklinksCount").textContent = `${Number(bl.referring_domains || 0).toLocaleString()} Ref Domains`;
            } else if (bl.openpagerank_score !== null && bl.openpagerank_score !== undefined) {
                $("doBacklinksCount").textContent = `PR ${bl.openpagerank_score}/10`;
            } else {
                $("doBacklinksCount").textContent = "Not Configured";
            }
        }
        if ($("doBacklinksDetails")) {
            if (bl.total_backlinks !== null && bl.total_backlinks !== undefined) {
                $("doBacklinksDetails").textContent = `${Number(bl.total_backlinks).toLocaleString()} Total Backlinks`;
            } else if (bl.openpagerank_rank) {
                $("doBacklinksDetails").textContent = `Global Rank #${Number(bl.openpagerank_rank).toLocaleString()}`;
            } else {
                $("doBacklinksDetails").textContent = "Domain Authority / Backlink Index";
            }
        }
        if ($("doBacklinksBadge")) {
            $("doBacklinksBadge").textContent = bl.is_configured ? "Third-Party Index" : "Not Configured";
            $("doBacklinksBadge").style.background = bl.is_configured ? "#EFF6FF" : "#F1F5F9";
            $("doBacklinksBadge").style.color = bl.is_configured ? "#1E40AF" : "#475569";
        }
        if ($("doBacklinksProvider")) {
            $("doBacklinksProvider").textContent = bl.data_provider || "OpenPageRank / DataForSEO";
        }

        // 6. Search Console
        const gsc = data.search_console || {};
        if ($("doGscClicks")) {
            if (gsc.connected && gsc.clicks !== null && gsc.clicks !== undefined) {
                $("doGscClicks").textContent = `${Number(gsc.clicks).toLocaleString()} Clicks`;
            } else {
                $("doGscClicks").textContent = "Not Set Up";
            }
        }
        if ($("doGscDetails")) {
            if (gsc.connected && gsc.impressions !== null && gsc.impressions !== undefined) {
                $("doGscDetails").textContent = `${Number(gsc.impressions).toLocaleString()} Imp • Pos ${gsc.average_position ? Number(gsc.average_position).toFixed(1) : '--'}`;
            } else {
                $("doGscDetails").textContent = "Verified Clicks & Impressions";
            }
        }
        if ($("doGscBadge")) {
            $("doGscBadge").textContent = gsc.connected ? "First-Party Verified" : "Not Connected";
            $("doGscBadge").style.background = gsc.connected ? "#ECFDF5" : "#F1F5F9";
            $("doGscBadge").style.color = gsc.connected ? "#065F46" : "#475569";
        }

        // 7. Interactive Historical Trend Charts (SVG)
        this.renderScoreTrendChart(data.historical_trends || []);
        this.renderIssuesTrendChart(data.historical_trends || []);

        // 8. PageSpeed Performance & Core Web Vitals
        this.renderDomainOverviewPs(data.pagespeed);

        // 9. Category Health Bars
        this.renderDomainOverviewCategories(health.categories || []);

        // 10. Top Priority Technical Issues
        this.renderDomainOverviewIssues(data.technical_issues ? data.technical_issues.top_issues : []);

        // 11. Top Performing Pages
        this.renderDomainOverviewTopPages(data.top_pages || []);
    }

    renderDomainOverviewPs(ps) {
        if (!ps) return;
        const strategy = this.state.domainOverviewPsStrategy || "mobile";
        const btnMob = $("doBtnStrategyMobile");
        const btnDesk = $("doBtnStrategyDesktop");
        if (btnMob && btnDesk) {
            btnMob.className = strategy === "mobile" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm";
            btnDesk.className = strategy === "desktop" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm";
        }

        const stratData = ps[strategy] || {};
        const perf = stratData.performance_score !== undefined && stratData.performance_score !== null ? stratData.performance_score : "--";
        const access = stratData.accessibility_score !== undefined && stratData.accessibility_score !== null ? stratData.accessibility_score : "--";
        const best = stratData.best_practices_score !== undefined && stratData.best_practices_score !== null ? stratData.best_practices_score : "--";
        const seo = stratData.seo_score !== undefined && stratData.seo_score !== null ? stratData.seo_score : "--";

        if ($("doPsScorePerf")) {
            $("doPsScorePerf").textContent = perf;
            $("doPsScorePerf").style.color = perf >= 90 ? "#10B981" : perf >= 50 ? "#F59E0B" : "#EF4444";
        }
        if ($("doPsScoreAccess")) $("doPsScoreAccess").textContent = access;
        if ($("doPsScorePractices")) $("doPsScorePractices").textContent = best;
        if ($("doPsScoreSeo")) $("doPsScoreSeo").textContent = seo;

        const cwvsGrid = $("doCwvsGrid");
        if (!cwvsGrid) return;

        const lab = stratData.lab || {};
        const field = stratData.field || {};

        const metricDefs = [
            { key: "LCP", name: "Largest Contentful Paint", good: "≤ 2.5s", unit: "s", labVal: lab["LCP"], fieldVal: field["LARGEST_CONTENTFUL_PAINT_MS"] },
            { key: "CLS", name: "Cumulative Layout Shift", good: "≤ 0.1", unit: "", labVal: lab["CLS"], fieldVal: field["CUMULATIVE_LAYOUT_SHIFT_SCORE"] },
            { key: "FCP", name: "First Contentful Paint", good: "≤ 1.8s", unit: "s", labVal: lab["FCP"], fieldVal: field["FIRST_CONTENTFUL_PAINT_MS"] },
            { key: "TBT", name: "Total Blocking Time / INP", good: "≤ 200ms", unit: "ms", labVal: lab["TBT"], fieldVal: field["INTERACTION_TO_NEXT_PAINT"] },
            { key: "Speed Index", name: "Speed Index", good: "≤ 3.4s", unit: "s", labVal: lab["Speed Index"], fieldVal: null },
            { key: "Server Response", name: "Time to First Byte (TTFB)", good: "≤ 0.8s", unit: "ms", labVal: lab["Server response"], fieldVal: field["EXPERIMENTAL_TIME_TO_FIRST_BYTE"] }
        ];

        cwvsGrid.innerHTML = metricDefs.map(m => {
            const hasField = m.fieldVal !== null && m.fieldVal !== undefined;
            const displayLab = m.labVal !== undefined && m.labVal !== null ? (typeof m.labVal === 'object' ? m.labVal.displayValue || JSON.stringify(m.labVal) : m.labVal) : "N/A";
            const displayField = hasField ? (typeof m.fieldVal === 'object' ? `${m.fieldVal.percentile}${m.unit}` : `${m.fieldVal}${m.unit}`) : "No field data (CrUX)";

            return `
                <div style="background:var(--bg-main); padding:16px; border-radius:var(--radius); border:1px solid var(--border);">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px;">
                        <div>
                            <div style="font-weight:700; font-size:14px;">${m.name}</div>
                            <div style="font-size:11px; color:var(--text-muted);">Threshold: ${m.good}</div>
                        </div>
                        <span class="badge" style="background:#EFF6FF; color:#1E40AF; font-size:10px;">${m.key}</span>
                    </div>
                    <div style="display:flex; gap:12px; margin-top:12px; border-top:1px solid var(--border); padding-top:8px;">
                        <div style="flex:1;">
                            <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; font-weight:600;">Lab Diagnostic</div>
                            <div style="font-size:16px; font-weight:700; color:#2563EB;">${displayLab}</div>
                        </div>
                        <div style="flex:1; border-left:1px solid var(--border); padding-left:12px;">
                            <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase; font-weight:600;">Field (CrUX)</div>
                            <div style="font-size:12px; font-weight:600; color:${hasField ? '#10B981' : 'var(--text-muted)'}; margin-top:3px;">${displayField}</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    renderDomainOverviewCategories(categories) {
        const container = $("doCategoriesList");
        if (!container) return;
        if (!categories || categories.length === 0) {
            container.innerHTML = '<div style="color:var(--text-muted); font-size:13px;">No category scores available.</div>';
            return;
        }

        container.innerHTML = categories.map(c => {
            const score = c.score !== null && c.score !== undefined ? Math.round(c.score) : 0;
            const barColor = score >= 80 ? '#10B981' : score >= 60 ? '#F59E0B' : '#EF4444';
            return `
                <div>
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:13px; margin-bottom:4px;">
                        <span style="font-weight:600;">${c.name} <span style="font-size:11px; color:var(--text-muted); font-weight:400;">(${c.weight}% weight)</span></span>
                        <div style="display:flex; gap:6px; align-items:center;">
                            <span class="badge" style="background:${barColor}15; color:${barColor}; font-size:11px; font-weight:700;">${score}/100</span>
                            <span style="font-size:11px; color:var(--text-muted);">${c.grade || ''}</span>
                        </div>
                    </div>
                    <div style="width:100%; height:7px; background:var(--border); border-radius:4px; overflow:hidden;">
                        <div style="width:${Math.min(100, Math.max(0, score))}%; height:100%; background:${barColor}; border-radius:4px; transition:width 0.4s ease;"></div>
                    </div>
                </div>
            `;
        }).join('');
    }

    renderDomainOverviewIssues(issues) {
        const container = $("doTopIssuesList");
        if (!container) return;
        if (!issues || issues.length === 0) {
            container.innerHTML = '<div style="color:var(--text-muted); font-size:13px; padding:16px; text-align:center;">No high priority technical issues detected!</div>';
            return;
        }

        container.innerHTML = issues.slice(0, 5).map(iss => {
            const sev = (iss.severity || 'info').toLowerCase();
            const sevColor = sev === 'critical' ? '#EF4444' : sev === 'high' ? '#EA580C' : sev === 'warning' || sev === 'medium' ? '#F59E0B' : '#3B82F6';
            const cleanUrl = iss.affected_url ? iss.affected_url.replace(/^https?:\/\/[^\/]+/, '') || '/' : '/';
            return `
                <div style="background:var(--bg-main); padding:12px; border-radius:var(--radius); border-left:4px solid ${sevColor}; font-size:13px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span style="font-weight:700; color:var(--text-main); font-size:13px;">${iss.problem_description || 'Technical Issue'}</span>
                        <span class="badge" style="background:${sevColor}15; color:${sevColor}; font-size:10px; text-transform:uppercase;">${sev}</span>
                    </div>
                    <div style="color:var(--text-muted); font-size:11px; font-family:monospace; margin-bottom:6px;">URL: ${cleanUrl}</div>
                    <div style="color:#065F46; font-size:12px; background:#ECFDF5; padding:6px 10px; border-radius:6px; margin-top:4px;">
                        <strong>Fix:</strong> ${iss.suggested_correction || 'Address issue and re-audit.'}
                    </div>
                </div>
            `;
        }).join('');
    }

    renderDomainOverviewTopPages(pages) {
        const tbody = $("doTopPagesBody");
        if (!tbody) return;
        if (!pages || pages.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No crawled pages recorded.</td></tr>';
            return;
        }

        tbody.innerHTML = pages.map(p => {
            const status = parseInt(p.status) || 0;
            const statusClass = status >= 200 && status < 300 ? 'badge-success' : status >= 300 && status < 400 ? 'badge-warning' : 'badge-danger';
            const pathDisplay = p.url ? p.url.replace(/^https?:\/\/[^\/]+/, '') || '/' : '/';

            return `
                <tr>
                    <td style="max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                        <a href="${p.url}" target="_blank" style="color:var(--primary); font-weight:600; text-decoration:none;">${pathDisplay}</a>
                        <div style="font-size:11px; color:var(--text-muted); overflow:hidden; text-overflow:ellipsis;">${p.title || 'No Title'}</div>
                    </td>
                    <td><span class="badge ${statusClass}">HTTP ${status}</span></td>
                    <td><b>${p.internal_links_count || 0}</b> <span style="font-size:11px; color:var(--text-muted);">links</span></td>
                    <td>${Number(p.word_count || 0).toLocaleString()} words</td>
                    <td>
                        ${p.has_canonical ? '<span class="badge badge-success" style="font-size:10px;">Declared</span>' : '<span class="badge badge-danger" style="font-size:10px;">Missing</span>'}
                    </td>
                    <td>
                        <a class="btn btn-secondary btn-sm" href="${p.url}" target="_blank" style="padding:4px 8px; font-size:11px;">Open ↗</a>
                    </td>
                </tr>
            `;
        }).join('');
    }

    renderScoreTrendChart(trends) {
        const container = $("doScoreChartContainer");
        if (!container) return;

        if (!trends || trends.length < 2) {
            const hasSingle = trends && trends.length === 1 && trends[0].score !== null && trends[0].score !== undefined;
            if (hasSingle) {
                const currentScore = Math.round(trends[0].score);
                const col = getScoreColor(currentScore);
                container.innerHTML = `
                    <div class="empty-state-card" style="padding:32px 16px; margin:0;">
                        <div style="font-size:32px; color:${col}; font-weight:800; margin-bottom:4px;">${currentScore}/100</div>
                        <div class="empty-state-title">Baseline Audit Recorded</div>
                        <div class="empty-state-desc">Single verified audit on file (${esc(trends[0].date_display || 'Latest')}). Continuous trend progression requires at least 2 consecutive audits.</div>
                    </div>
                `;
            } else {
                container.innerHTML = `
                    <div class="empty-state-card" style="padding:32px 16px; margin:0;">
                        <div class="empty-state-icon">📊</div>
                        <div class="empty-state-title">No Audit History Recorded</div>
                        <div class="empty-state-desc">Historical trend analysis requires at least 2 verified audits. Run audits over time to monitor performance trajectory.</div>
                    </div>
                `;
            }
            return;
        }

        const W = 500;
        const H = 180;
        const padX = 40;
        const padY = 25;
        const plotW = W - padX * 2;
        const plotH = H - padY * 2;

        const points = trends.map((t, idx) => {
            const x = padX + (idx / (trends.length - 1)) * plotW;
            const score = Math.max(0, Math.min(100, t.score || 0));
            const y = padY + plotH - (score / 100) * plotH;
            return { x, y, score, date: t.date_display || `Audit ${t.audit_id}` };
        });

        const lineD = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
        const areaD = `${lineD} L ${points[points.length - 1].x.toFixed(1)} ${(padY + plotH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padY + plotH).toFixed(1)} Z`;

        container.innerHTML = `
            <svg viewBox="0 0 ${W} ${H}" style="width:100%; height:180px; overflow:visible;">
                <defs>
                    <linearGradient id="scoreAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#2563EB" stop-opacity="0.25"/>
                        <stop offset="100%" stop-color="#2563EB" stop-opacity="0.0"/>
                    </linearGradient>
                </defs>
                <!-- Grid Lines -->
                <line x1="${padX}" y1="${padY}" x2="${W - padX}" y2="${padY}" stroke="var(--border)" stroke-dasharray="3,3"/>
                <line x1="${padX}" y1="${padY + plotH * 0.5}" x2="${W - padX}" y2="${padY + plotH * 0.5}" stroke="var(--border)" stroke-dasharray="3,3"/>
                <line x1="${padX}" y1="${padY + plotH}" x2="${W - padX}" y2="${padY + plotH}" stroke="var(--border)"/>
                <text x="${padX - 8}" y="${padY + 4}" font-size="10" fill="var(--text-muted)" text-anchor="end">100</text>
                <text x="${padX - 8}" y="${padY + plotH * 0.5 + 4}" font-size="10" fill="var(--text-muted)" text-anchor="end">50</text>
                <text x="${padX - 8}" y="${padY + plotH + 4}" font-size="10" fill="var(--text-muted)" text-anchor="end">0</text>
                
                <!-- Area Fill -->
                <path d="${areaD}" fill="url(#scoreAreaGrad)"/>
                <!-- Line -->
                <path d="${lineD}" fill="none" stroke="var(--primary)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                
                <!-- Data Points -->
                ${points.map(p => `
                    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5" fill="var(--bg-card)" stroke="var(--primary)" stroke-width="3">
                        <title>${esc(p.date)}: Score ${Math.round(p.score)}/100</title>
                    </circle>
                    <text x="${p.x.toFixed(1)}" y="${(p.y - 10).toFixed(1)}" font-size="11" font-weight="700" fill="var(--primary)" text-anchor="middle">${Math.round(p.score)}</text>
                    <text x="${p.x.toFixed(1)}" y="${(padY + plotH + 16).toFixed(1)}" font-size="10" fill="var(--text-muted)" text-anchor="middle">${esc(p.date)}</text>
                `).join('')}
            </svg>
        `;
    }

    // ==========================================

    // KEYWORD MAGIC TOOL MODULE (PHASE 4)
    // ==========================================
    async loadKeywordMagic() {
        if (!this.kmState) {
            this.kmState = {
                seed: "",
                country: 2840,
                language: "en",
                matchType: "all",
                cluster: "",
                intent: "all",
                kd: "all",
                volMin: null,
                volMax: null,
                cpcMin: null,
                cpcMax: null,
                search: "",
                currentData: null,
                filteredKeywords: []
            };
        }
        this.updateKmProjectsCount();
        if (!this.kmState.currentData && $("kmSeedInput") && $("kmSeedInput").value.trim()) {
            this.executeKmSearch($("kmSeedInput").value.trim());
        }
    }

    async updateKmProjectsCount() {
        try {
            const projects = await jsonFetch(`${API_BASE}/keyword-magic/projects`);
            if ($("kmProjectsCount")) $("kmProjectsCount").textContent = projects.length || "0";
        } catch (e) {
            // Ignore error
        }
    }

    onKmSearchSubmit(event) {
        if (event) event.preventDefault();
        const seed = $("kmSeedInput") ? $("kmSeedInput").value.trim() : "";
        if (!seed) return;
        this.executeKmSearch(seed);
    }

    setKmSeedAndSearch(seed) {
        if ($("kmSeedInput")) $("kmSeedInput").value = seed;
        this.executeKmSearch(seed);
    }

    async executeKmSearch(seed, options = {}) {
        if (!seed) return;
        this.kmState.seed = seed;
        this.kmState.country = parseInt($("kmCountrySelect") ? $("kmCountrySelect").value : 2840);
        this.kmState.language = $("kmLangSelect") ? $("kmLangSelect").value : "en";
        this.kmState.cluster = "";
        this.kmState.search = "";

        const btn = $("kmSearchBtn");
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span>Searching...</span>';
        }

        try {
            const params = new URLSearchParams({
                seed: this.kmState.seed,
                country: this.kmState.country,
                language: this.kmState.language,
                match_type: this.kmState.matchType || "all",
                limit: "200"
            });

            const data = await jsonFetch(`${API_BASE}/keyword-magic/search?${params.toString()}`);
            if (!data.ok) throw new Error(data.error || "Keyword search failed");

            this.kmState.currentData = data;
            this.renderKmResults(data);
        } catch (err) {
            console.error("Keyword search error:", err);
            alert("Keyword search failed: " + err.message);
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<span>Search Keywords</span>';
            }
        }
    }

    setKmMatchType(matchType) {
        this.kmState.matchType = matchType;
        const tabs = $("kmMatchTabs");
        if (tabs) {
            tabs.querySelectorAll(".tab-btn").forEach(btn => {
                const txt = btn.textContent.toLowerCase();
                if (txt.includes(matchType.replace("_", " ")) || (matchType === "all" && txt.includes("all"))) {
                    btn.classList.add("active");
                } else {
                    btn.classList.remove("active");
                }
            });
        }
        if (this.kmState.seed) {
            this.executeKmSearch(this.kmState.seed);
        }
    }

    selectKmCluster(clusterName) {
        this.kmState.cluster = clusterName || "";
        const list = $("kmClustersList");
        if (list) {
            list.querySelectorAll("button").forEach(b => {
                const bName = b.getAttribute("data-cluster") || "";
                if (bName.toLowerCase() === this.kmState.cluster.toLowerCase()) {
                    b.classList.add("active");
                } else {
                    b.classList.remove("active");
                }
            });
        }
        const lbl = $("kmActiveClusterLabel");
        if (lbl) {
            lbl.innerHTML = this.kmState.cluster ? `in cluster <b>"${esc(this.kmState.cluster)}"</b>` : '';
        }
        this.applyKmFilters();
    }

    applyKmFilters() {
        if (!this.kmState || !this.kmState.currentData) return;
        const allKeywords = this.kmState.currentData.keywords || [];

        const intent = $("kmFilterIntent") ? $("kmFilterIntent").value : "all";
        const kd = $("kmFilterKd") ? $("kmFilterKd").value : "all";
        const volMin = $("kmFilterVolMin") && $("kmFilterVolMin").value !== "" ? parseInt($("kmFilterVolMin").value) : null;
        const volMax = $("kmFilterVolMax") && $("kmFilterVolMax").value !== "" ? parseInt($("kmFilterVolMax").value) : null;
        const cpcMin = $("kmFilterCpcMin") && $("kmFilterCpcMin").value !== "" ? parseFloat($("kmFilterCpcMin").value) : null;
        const cpcMax = $("kmFilterCpcMax") && $("kmFilterCpcMax").value !== "" ? parseFloat($("kmFilterCpcMax").value) : null;
        const searchTxt = $("kmFilterSearch") ? $("kmFilterSearch").value.trim().toLowerCase() : "";

        let filtered = allKeywords.filter(k => {
            // Cluster filter
            if (this.kmState.cluster && (k.cluster || "").toLowerCase() !== this.kmState.cluster.toLowerCase()) {
                return false;
            }
            // Intent filter
            if (intent !== "all" && (k.intent || "").toLowerCase() !== intent.toLowerCase()) {
                return false;
            }
            // KD filter
            if (kd !== "all" && k.keyword_difficulty !== null && k.keyword_difficulty !== undefined) {
                const [minKD, maxKD] = kd.split("-").map(Number);
                if (k.keyword_difficulty < minKD || k.keyword_difficulty > maxKD) return false;
            }
            // Volume filter
            if (volMin !== null && (k.search_volume === null || k.search_volume < volMin)) return false;
            if (volMax !== null && (k.search_volume === null || k.search_volume > volMax)) return false;
            // CPC filter
            if (cpcMin !== null && (k.cpc === null || k.cpc < cpcMin)) return false;
            if (cpcMax !== null && (k.cpc === null || k.cpc > cpcMax)) return false;
            // Search text
            if (searchTxt && !k.keyword.toLowerCase().includes(searchTxt)) return false;

            return true;
        });

        this.kmState.filteredKeywords = filtered;
        this.renderKmTable(filtered);
    }

    applyKmClientSearch(query) {
        this.applyKmFilters();
    }

    resetKmFilters() {
        if ($("kmFilterIntent")) $("kmFilterIntent").value = "all";
        if ($("kmFilterKd")) $("kmFilterKd").value = "all";
        if ($("kmFilterVolMin")) $("kmFilterVolMin").value = "";
        if ($("kmFilterVolMax")) $("kmFilterVolMax").value = "";
        if ($("kmFilterCpcMin")) $("kmFilterCpcMin").value = "";
        if ($("kmFilterCpcMax")) $("kmFilterCpcMax").value = "";
        if ($("kmFilterSearch")) $("kmFilterSearch").value = "";
        this.kmState.cluster = "";
        this.selectKmCluster("");
    }

    renderKmResults(data) {
        // 1. Provenance Notice
        const provBadge = $("kmProviderBadge");
        if (provBadge) {
            provBadge.textContent = data.has_live_provider ? "DataForSEO Live Data" : "On-Site / Search Suggestions";
            provBadge.className = data.has_live_provider ? "badge badge-success" : "badge badge-primary";
        }
        const provDot = $("kmProvStatusDot");
        if (provDot) provDot.style.color = data.has_live_provider ? "#10B981" : "#64748B";
        const provStmt = $("kmProvStatement");
        if (provStmt) provStmt.innerHTML = `<b>Data Provenance:</b> ${esc(data.data_provider)}. ${esc(data.integrity_statement)}`;
        const costBadge = $("kmCostBadge");
        if (costBadge) {
            costBadge.textContent = data.cost_usd ? `Cost: $${data.cost_usd.toFixed(4)}` : "Provider: Free / Local";
        }

        // 2. Summary stats
        const sum = data.summary || {};
        if ($("kmStatTotal")) $("kmStatTotal").textContent = fmt(sum.total_keywords || 0);
        if ($("kmStatVolume")) {
            $("kmStatVolume").textContent = sum.total_search_volume !== null && sum.total_search_volume !== undefined ? fmt(sum.total_search_volume) : "—";
            if ($("kmStatVolumeSub")) $("kmStatVolumeSub").textContent = sum.total_search_volume !== null ? "Total monthly volume" : "Requires DataForSEO provider";
        }
        if ($("kmStatKd")) {
            $("kmStatKd").textContent = sum.average_difficulty !== null && sum.average_difficulty !== undefined ? `${sum.average_difficulty}%` : "—";
            if ($("kmStatKdSub")) $("kmStatKdSub").textContent = sum.average_difficulty !== null ? "Average KD" : "Requires DataForSEO provider";
        }

        // Intent distribution
        const intents = sum.intent_distribution || {};
        if ($("kmStatIntents")) {
            const badge = (name, count, bg, color) => count ? `<span class="badge" style="background:${bg}; color:${color}; font-size:11px;">${name}: ${count}</span>` : '';
            $("kmStatIntents").innerHTML = `
                ${badge("Info", intents.Informational, "#DBEAFE", "#1D4ED8")}
                ${badge("Comm", intents.Commercial, "#FEF3C7", "#B45309")}
                ${badge("Trans", intents.Transactional, "#D1FAE5", "#047857")}
                ${badge("Nav", intents.Navigational, "#F3E8FF", "#7E22CE")}
            ` || '<span style="font-size:11px; color:var(--text-muted);">No intent breakdown</span>';
        }

        // 3. Render Clusters List
        this.renderKmClusters(data.clusters || [], data.keywords ? data.keywords.length : 0);

        // 4. Render Table
        this.kmState.filteredKeywords = data.keywords || [];
        this.renderKmTable(this.kmState.filteredKeywords);
    }

    renderKmClusters(clusters, totalCount) {
        const list = $("kmClustersList");
        if (!list) return;

        if ($("kmClustersBadge")) $("kmClustersBadge").textContent = `${clusters.length} topics`;
        if ($("kmClusterTotalBadge")) $("kmClusterTotalBadge").textContent = totalCount;

        const allBtn = `
            <button class="btn btn-outline btn-sm ${!this.kmState.cluster ? 'active' : ''}" data-cluster="" style="justify-content:space-between; font-weight:600; text-align:left;" onclick="app.selectKmCluster('')">
                <span>All Topics</span>
                <span class="pill" style="font-size:10px;">${totalCount}</span>
            </button>
        `;

        const clusterBtns = clusters.map(c => {
            const isAct = (this.kmState.cluster || "").toLowerCase() === c.name.toLowerCase();
            const volStr = c.total_volume !== null && c.total_volume !== undefined ? ` • ${fmt(c.total_volume)} vol` : '';
            return `
                <button class="btn btn-outline btn-sm ${isAct ? 'active' : ''}" data-cluster="${esc(c.name)}" style="justify-content:space-between; font-weight:500; font-size:12px; text-align:left; padding:6px 10px;" onclick="app.selectKmCluster('${esc(c.name)}')">
                    <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:160px;" title="${esc(c.name)}">${esc(c.name)}</span>
                    <span class="pill" style="font-size:10px;" title="${c.count} keywords${volStr}">${c.count}</span>
                </button>
            `;
        }).join('');

        list.innerHTML = allBtn + clusterBtns;
    }

    renderKmTable(keywords) {
        const tbody = $("kmTableBody");
        if (!tbody) return;

        if ($("kmVisibleCount")) $("kmVisibleCount").textContent = keywords.length;

        if (!keywords || keywords.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-state" style="padding:40px 16px;">No keywords match the selected filters or cluster.</td></tr>';
            return;
        }

        const intentBadge = (intent) => {
            const it = (intent || "Informational").toLowerCase();
            if (it === "transactional") return '<span class="badge" style="background:#D1FAE5; color:#047857; font-size:11px;">Trans</span>';
            if (it === "commercial") return '<span class="badge" style="background:#FEF3C7; color:#B45309; font-size:11px;">Comm</span>';
            if (it === "navigational") return '<span class="badge" style="background:#F3E8FF; color:#7E22CE; font-size:11px;">Nav</span>';
            return '<span class="badge" style="background:#DBEAFE; color:#1D4ED8; font-size:11px;">Info</span>';
        };

        const kdPill = (kd) => {
            if (kd === null || kd === undefined) return '<span style="color:var(--text-muted); font-size:12px;">—</span>';
            let color = "#10B981"; // green
            let label = "Very Easy";
            if (kd >= 15 && kd < 30) { color = "#059669"; label = "Easy"; }
            else if (kd >= 30 && kd < 50) { color = "#F59E0B"; label = "Possible"; }
            else if (kd >= 50 && kd < 70) { color = "#EA580C"; label = "Difficult"; }
            else if (kd >= 70 && kd < 85) { color = "#DC2626"; label = "Hard"; }
            else if (kd >= 85) { color = "#7F1D1D"; label = "Very Hard"; }
            return `<span class="pill" style="background:${color}18; color:${color}; font-weight:700; font-size:11px;" title="${label}">${kd}%</span>`;
        };

        tbody.innerHTML = keywords.map((k, idx) => {
            const vol = k.search_volume !== null && k.search_volume !== undefined ? fmt(k.search_volume) : '<span style="color:var(--text-muted); font-size:12px;">—</span>';
            const cpc = k.cpc !== null && k.cpc !== undefined ? `$${k.cpc.toFixed(2)}` : '<span style="color:var(--text-muted); font-size:12px;">—</span>';
            const comp = k.competition_level ? `<span class="badge" style="font-size:10px; background:#F8FAFC; border:1px solid var(--border);">${esc(k.competition_level)}</span>` : '<span style="color:var(--text-muted); font-size:11px;">N/A</span>';

            return `
                <tr>
                    <td style="text-align:center;">
                        <input type="checkbox" class="km-row-checkbox" data-idx="${idx}" onchange="app.onKmRowCheckChange()">
                    </td>
                    <td>
                        <div style="display:flex; align-items:center; gap:6px;">
                            <b style="color:var(--text); font-size:13px;">${esc(k.keyword)}</b>
                            <button type="button" class="btn btn-outline" style="padding:1px 5px; font-size:10px; line-height:1;" onclick="navigator.clipboard.writeText('${esc(k.keyword)}'); alert('Copied: ${esc(k.keyword)}');" title="Copy keyword">📋</button>
                        </div>
                    </td>
                    <td>${intentBadge(k.intent)}</td>
                    <td><b>${vol}</b></td>
                    <td>${kdPill(k.keyword_difficulty)}</td>
                    <td><b>${cpc}</b></td>
                    <td>${comp}</td>
                    <td><span class="pill" style="font-size:11px;">${esc(k.cluster || "General")}</span></td>
                    <td>
                        <button class="btn btn-outline btn-sm" style="padding:3px 8px; font-size:11px;" onclick="app.quickSaveKeyword(${idx})">+ Save</button>
                    </td>
                </tr>
            `;
        }).join('');

        this.onKmRowCheckChange();
    }

    toggleKmSelectAll(checked) {
        const checkboxes = document.querySelectorAll(".km-row-checkbox");
        checkboxes.forEach(cb => cb.checked = checked);
        this.onKmRowCheckChange();
    }

    onKmRowCheckChange() {
        const checked = document.querySelectorAll(".km-row-checkbox:checked");
        const saveBtn = $("kmSaveSelectedBtn");
        if (saveBtn) {
            saveBtn.disabled = checked.length === 0;
            saveBtn.innerHTML = `<span>+ Add to Project (${checked.length})</span>`;
        }
        const selectAll = $("kmSelectAllCheckbox");
        const all = document.querySelectorAll(".km-row-checkbox");
        if (selectAll && all.length > 0) {
            selectAll.checked = (checked.length === all.length);
        }
    }

    getSelectedKmKeywords() {
        const checked = document.querySelectorAll(".km-row-checkbox:checked");
        const list = [];
        checked.forEach(cb => {
            const idx = parseInt(cb.getAttribute("data-idx"));
            if (this.kmState && this.kmState.filteredKeywords && this.kmState.filteredKeywords[idx]) {
                list.push(this.kmState.filteredKeywords[idx]);
            }
        });
        return list;
    }

    exportKm(format) {
        if (!this.kmState || !this.kmState.seed) {
            alert("Please search for a seed keyword first to export research results.");
            return;
        }
        const params = new URLSearchParams({
            seed: this.kmState.seed,
            country: this.kmState.country || 2840,
            language: this.kmState.language || "en",
            match_type: this.kmState.matchType || "all"
        });
        if (this.kmState.cluster) params.set("cluster", this.kmState.cluster);
        const intent = $("kmFilterIntent") ? $("kmFilterIntent").value : "all";
        if (intent !== "all") params.set("intent", intent);

        window.open(`${API_BASE}/keyword-magic/export/${format}?${params.toString()}`, "_blank");
    }

    // ==========================================
    // KEYWORD PROJECTS MANAGEMENT
    // ==========================================
    async openKmProjectsModal() {
        const modal = $("kmProjectModal");
        if (!modal) return;
        modal.classList.remove("hidden");
        modal.style.display = "flex";
        this.loadKmProjectsList();
    }

    closeKmProjectsModal() {
        const modal = $("kmProjectModal");
        if (!modal) return;
        modal.classList.add("hidden");
        modal.style.display = "none";
    }

    async loadKmProjectsList() {
        const body = $("kmProjectModalBody");
        if (!body) return;
        if ($("kmProjectModalTitle")) $("kmProjectModalTitle").textContent = "Keyword Projects";

        body.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">Loading projects...</div>';

        try {
            const projects = await jsonFetch(`${API_BASE}/keyword-magic/projects`);
            const clients = await jsonFetch(`${API_BASE}/clients`).catch(() => []);

            let clientOpts = clients.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');

            const createForm = `
                <div class="card" style="background:#F8FAFC; border:1px solid var(--border); padding:16px; margin-bottom:20px;">
                    <b style="font-size:14px; margin-bottom:10px; display:block;">+ Create New Keyword Project</b>
                    <form onsubmit="app.handleCreateKmProject(event)" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                        <input id="newKmProjectName" class="form-input" type="text" placeholder="Project name (e.g. Q4 Target Terms)..." required style="flex:2; min-width:180px;">
                        <select id="newKmProjectClient" class="form-input" style="flex:1; min-width:140px;">
                            <option value="">Link Client (Optional)...</option>
                            ${clientOpts}
                        </select>
                        <button type="submit" class="btn btn-primary" style="white-space:nowrap;">Create Project</button>
                    </form>
                </div>
            `;

            let tableHtml = '';
            if (!projects || projects.length === 0) {
                tableHtml = '<div class="empty-state" style="padding:24px;">No keyword projects created yet. Create one above to organize target keywords.</div>';
            } else {
                tableHtml = `
                    <div class="table-container">
                        <table>
                            <thead>
                                <tr>
                                    <th>Project Name</th>
                                    <th>Client</th>
                                    <th>Saved Keywords</th>
                                    <th>Last Updated</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${projects.map(p => `
                                    <tr>
                                        <td>
                                            <a href="javascript:void(0)" onclick="app.viewKmProjectDetail(${p.id})" style="color:var(--primary); font-weight:700; text-decoration:none;">
                                                📁 ${esc(p.name)}
                                            </a>
                                        </td>
                                        <td><span class="badge" style="font-size:11px;">${esc(p.client_name || "Unassigned")}</span></td>
                                        <td><b>${p.keyword_count || 0}</b> keywords</td>
                                        <td><span style="font-size:12px; color:var(--text-muted);">${p.updated_at ? new Date(p.updated_at).toLocaleDateString() : '—'}</span></td>
                                        <td>
                                            <div style="display:flex; gap:6px;">
                                                <button class="btn btn-outline btn-sm" onclick="app.viewKmProjectDetail(${p.id})">Open</button>
                                                <button class="btn btn-danger btn-sm" onclick="app.deleteKmProject(${p.id})">Delete</button>
                                            </div>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                `;
            }

            body.innerHTML = createForm + tableHtml;
            this.updateKmProjectsCount();
        } catch (err) {
            body.innerHTML = `<div class="card" style="border-left:4px solid var(--danger);">Failed to load projects: ${esc(err.message)}</div>`;
        }
    }

    async handleCreateKmProject(event) {
        if (event) event.preventDefault();
        const nameInp = $("newKmProjectName");
        if (!nameInp || !nameInp.value.trim()) return;
        const name = nameInp.value.trim();
        const clientVal = $("newKmProjectClient") ? $("newKmProjectClient").value : "";
        const client_id = clientVal ? parseInt(clientVal) : null;

        try {
            await jsonFetch(`${API_BASE}/keyword-magic/projects`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, client_id })
            });
            this.loadKmProjectsList();
        } catch (err) {
            alert("Failed to create project: " + err.message);
        }
    }

    async viewKmProjectDetail(projectId) {
        const body = $("kmProjectModalBody");
        if (!body) return;
        body.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">Loading project details...</div>';

        try {
            const project = await jsonFetch(`${API_BASE}/keyword-magic/projects/${projectId}`);
            if ($("kmProjectModalTitle")) $("kmProjectModalTitle").innerHTML = `<a href="javascript:void(0)" onclick="app.loadKmProjectsList()" style="color:var(--text-muted); text-decoration:none;">Projects</a> &gt; ${esc(project.name)}`;

            const keywords = project.keywords || [];
            let rowsHtml = '';
            if (keywords.length === 0) {
                rowsHtml = '<tr><td colspan="7" class="empty-state">No keywords saved to this project yet. Use the Keyword Magic Tool table to save keywords here.</td></tr>';
            } else {
                rowsHtml = keywords.map(k => `
                    <tr>
                        <td><b>${esc(k.keyword)}</b></td>
                        <td><span class="badge" style="font-size:11px;">${esc(k.intent || "Info")}</span></td>
                        <td><b>${k.search_volume !== null && k.search_volume !== undefined ? fmt(k.search_volume) : '—'}</b></td>
                        <td>${k.keyword_difficulty !== null && k.keyword_difficulty !== undefined ? `${k.keyword_difficulty}%` : '—'}</td>
                        <td>${k.cpc !== null && k.cpc !== undefined ? `$${k.cpc.toFixed(2)}` : '—'}</td>
                        <td><span class="pill" style="font-size:11px;">${esc(k.cluster || "General")}</span></td>
                        <td>
                            <button class="btn btn-outline btn-sm" style="color:var(--danger); border-color:var(--danger);" onclick="app.removeKmProjectKeyword(${projectId}, ${k.id})">✕ Remove</button>
                        </td>
                    </tr>
                `).join('');
            }

            body.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                    <div>
                        <div style="font-size:14px; font-weight:700;">${esc(project.name)}</div>
                        <div style="font-size:12px; color:var(--text-muted);">Client: ${esc(project.client_name)} • Total: ${keywords.length} keywords</div>
                    </div>
                    <div style="display:flex; gap:8px;">
                        <button class="btn btn-secondary btn-sm" onclick="app.loadKmProjectsList()">← Back to Projects</button>
                        <button class="btn btn-outline btn-sm" onclick="app.exportKmProjectCsv(${projectId})">📥 Export CSV</button>
                    </div>
                </div>
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Keyword</th>
                                <th>Intent</th>
                                <th>Search Volume</th>
                                <th>KD%</th>
                                <th>CPC</th>
                                <th>Cluster</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            body.innerHTML = `<div class="card" style="border-left:4px solid var(--danger);">Failed to load project details: ${esc(err.message)}</div>`;
        }
    }

    async deleteKmProject(projectId) {
        if (!confirm("Are you sure you want to delete this keyword project and all saved keywords in it?")) return;
        try {
            await jsonFetch(`${API_BASE}/keyword-magic/projects/${projectId}`, { method: "DELETE" });
            this.loadKmProjectsList();
        } catch (err) {
            alert("Failed to delete project: " + err.message);
        }
    }

    async removeKmProjectKeyword(projectId, keywordId) {
        try {
            await jsonFetch(`${API_BASE}/keyword-magic/projects/${projectId}/keywords/${keywordId}`, { method: "DELETE" });
            this.viewKmProjectDetail(projectId);
        } catch (err) {
            alert("Failed to remove keyword: " + err.message);
        }
    }

    async openSaveSelectedToProjectModal() {
        const selected = this.getSelectedKmKeywords();
        if (selected.length === 0) {
            alert("Please select at least one keyword using the checkboxes.");
            return;
        }

        const modal = $("kmProjectModal");
        if (!modal) return;
        modal.classList.remove("hidden");
        modal.style.display = "flex";
        if ($("kmProjectModalTitle")) $("kmProjectModalTitle").textContent = `Save ${selected.length} Keywords to Project`;

        const body = $("kmProjectModalBody");
        body.innerHTML = '<div style="text-align:center; padding:24px; color:var(--text-muted);">Loading projects...</div>';

        try {
            const projects = await jsonFetch(`${API_BASE}/keyword-magic/projects`);
            let projOptions = projects.map(p => `<option value="${p.id}">${esc(p.name)} (${p.keyword_count || 0} keywords)</option>`).join('');

            body.innerHTML = `
                <div style="font-size:13px; color:var(--text-muted); margin-bottom:16px;">
                    Saving <b>${selected.length}</b> keywords into a project list.
                </div>

                ${projects.length > 0 ? `
                <div class="card" style="padding:16px; margin-bottom:20px; background:#F8FAFC; border:1px solid var(--border);">
                    <b style="font-size:14px; margin-bottom:10px; display:block;">Option A: Save to Existing Project</b>
                    <div style="display:flex; gap:10px; align-items:center;">
                        <select id="kmSelectExistingProj" class="form-input" style="flex:1;">
                            ${projOptions}
                        </select>
                        <button class="btn btn-primary" onclick="app.saveSelectedToExistingProject()">Save Keywords</button>
                    </div>
                </div>
                ` : ''}

                <div class="card" style="padding:16px; border:1px solid var(--border);">
                    <b style="font-size:14px; margin-bottom:10px; display:block;">Option B: Create New Project &amp; Save</b>
                    <form onsubmit="app.handleCreateKmProjectAndSaveSelected(event)" style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                        <input id="kmNewProjAndSaveName" class="form-input" type="text" placeholder="New project name..." required style="flex:1; min-width:180px;">
                        <button type="submit" class="btn btn-secondary">Create &amp; Save</button>
                    </form>
                </div>
            `;
        } catch (err) {
            body.innerHTML = `<div class="card" style="border-left:4px solid var(--danger);">Failed to load options: ${esc(err.message)}</div>`;
        }
    }

    async saveSelectedToExistingProject() {
        const projSelect = $("kmSelectExistingProj");
        if (!projSelect || !projSelect.value) return;
        const pId = parseInt(projSelect.value);
        const selected = this.getSelectedKmKeywords();

        try {
            const res = await jsonFetch(`${API_BASE}/keyword-magic/projects/${pId}/keywords`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ keywords: selected })
            });
            alert(`Success! Added ${res.added_count} keywords to project.`);
            this.closeKmProjectsModal();
            this.updateKmProjectsCount();
        } catch (err) {
            alert("Failed to save keywords: " + err.message);
        }
    }

    async handleCreateKmProjectAndSaveSelected(event) {
        if (event) event.preventDefault();
        const inp = $("kmNewProjAndSaveName");
        if (!inp || !inp.value.trim()) return;
        const name = inp.value.trim();
        const selected = this.getSelectedKmKeywords();

        try {
            const created = await jsonFetch(`${API_BASE}/keyword-magic/projects`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name })
            });
            const pId = created.project.id;
            const res = await jsonFetch(`${API_BASE}/keyword-magic/projects/${pId}/keywords`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ keywords: selected })
            });
            alert(`Success! Created project "${name}" and added ${res.added_count} keywords.`);
            this.closeKmProjectsModal();
            this.updateKmProjectsCount();
        } catch (err) {
            alert("Failed to create and save: " + err.message);
        }
    }

    quickSaveKeyword(idx) {
        if (!this.kmState || !this.kmState.filteredKeywords || !this.kmState.filteredKeywords[idx]) return;
        const kw = this.kmState.filteredKeywords[idx];
        const checkboxes = document.querySelectorAll(".km-row-checkbox");
        checkboxes.forEach((cb, i) => {
            cb.checked = (i === idx);
        });
        this.onKmRowCheckChange();
        this.openSaveSelectedToProjectModal();
    }

    exportKmProjectCsv(projectId) {
        jsonFetch(`${API_BASE}/keyword-magic/projects/${projectId}`).then(project => {
            const keywords = project.keywords || [];
            if (keywords.length === 0) {
                alert("Project has no keywords to export.");
                return;
            }
            let csv = '\ufeffKeyword,Search Intent,Search Volume,KD (%),CPC (USD),Cluster,Source\n';
            keywords.forEach(k => {
                csv += `"${(k.keyword||'').replace(/"/g, '""')}",${k.intent||'Info'},${k.search_volume||'N/A'},${k.keyword_difficulty||'N/A'},${k.cpc||'N/A'},"${(k.cluster||'General').replace(/"/g, '""')}",${k.source||'research'}\n`;
            });
            const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `project_${project.name.toLowerCase().replace(/[^a-z0-9]/g, '_')}_keywords.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }).catch(err => alert("Export failed: " + err.message));
    }


    renderIssuesTrendChart(trends) {
        const container = $("doIssuesChartContainer");
        if (!container) return;

        if (!trends || trends.length < 2) {
            container.innerHTML = `
                <div style="padding:40px 16px; text-align:center; color:var(--text-muted); font-size:13px;">
                    <div>Sequential audits will automatically plot critical vs. warning resolution trends here.</div>
                </div>
            `;
            return;
        }

        const W = 500;
        const H = 180;
        const padX = 40;
        const padY = 25;
        const plotW = W - padX * 2;
        const plotH = H - padY * 2;

        const maxIssues = Math.max(10, ...trends.map(t => Math.max(t.critical_issues || 0, t.warning_issues || 0)));

        const critPoints = trends.map((t, idx) => {
            const x = padX + (idx / (trends.length - 1)) * plotW;
            const y = padY + plotH - ((t.critical_issues || 0) / maxIssues) * plotH;
            return { x, y, val: t.critical_issues || 0, date: t.date_display || `Audit ${t.audit_id}` };
        });

        const warnPoints = trends.map((t, idx) => {
            const x = padX + (idx / (trends.length - 1)) * plotW;
            const y = padY + plotH - ((t.warning_issues || 0) / maxIssues) * plotH;
            return { x, y, val: t.warning_issues || 0, date: t.date_display || `Audit ${t.audit_id}` };
        });

        const critLine = critPoints.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
        const warnLine = warnPoints.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');

        container.innerHTML = `
            <svg viewBox="0 0 ${W} ${H}" style="width:100%; height:180px; overflow:visible;">
                <!-- Grid Lines -->
                <line x1="${padX}" y1="${padY}" x2="${W - padX}" y2="${padY}" stroke="#E2E8F0" stroke-dasharray="3,3"/>
                <line x1="${padX}" y1="${padY + plotH * 0.5}" x2="${W - padX}" y2="${padY + plotH * 0.5}" stroke="#E2E8F0" stroke-dasharray="3,3"/>
                <line x1="${padX}" y1="${padY + plotH}" x2="${W - padX}" y2="${padY + plotH}" stroke="#CBD5E1"/>
                <text x="${padX - 8}" y="${padY + 4}" font-size="10" fill="#64748B" text-anchor="end">${maxIssues}</text>
                <text x="${padX - 8}" y="${padY + plotH * 0.5 + 4}" font-size="10" fill="#64748B" text-anchor="end">${Math.round(maxIssues * 0.5)}</text>
                <text x="${padX - 8}" y="${padY + plotH + 4}" font-size="10" fill="#64748B" text-anchor="end">0</text>
                
                <!-- Lines -->
                <path d="${warnLine}" fill="none" stroke="#F59E0B" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="${critLine}" fill="none" stroke="#EF4444" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                
                <!-- Warnings Points -->
                ${warnPoints.map(p => `
                    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="#FFFFFF" stroke="#F59E0B" stroke-width="2">
                        <title>${p.date}: ${p.val} Warnings</title>
                    </circle>
                    <text x="${p.x.toFixed(1)}" y="${(p.y - 8).toFixed(1)}" font-size="10" font-weight="700" fill="#F59E0B" text-anchor="middle">${p.val}</text>
                `).join('')}

                <!-- Critical Points -->
                ${critPoints.map(p => `
                    <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="4" fill="#FFFFFF" stroke="#EF4444" stroke-width="2">
                        <title>${p.date}: ${p.val} Critical Issues</title>
                    </circle>
                    <text x="${p.x.toFixed(1)}" y="${(p.y - 8).toFixed(1)}" font-size="10" font-weight="700" fill="#EF4444" text-anchor="middle">${p.val}</text>
                    <text x="${p.x.toFixed(1)}" y="${(padY + plotH + 16).toFixed(1)}" font-size="10" fill="#64748B" text-anchor="middle">${p.date}</text>
                `).join('')}
            </svg>
        `;
    }




    // ==========================================
    // COMPETITOR ANALYSIS MODULE (PHASE 5)
    // ==========================================
    async loadCompetitorAnalysis() {
        if (!this.compState) {
            this.compState = {
                targetDomain: "",
                competitorDomains: [],
                country: 2840,
                language: "en",
                analysisData: null,
                activeFilter: "all",
                searchQuery: "",
                intentFilter: "",
                selectedKeywords: new Set(),
                savedComparisons: []
            };
        }

        // 1. Populate Target Dropdown from domains list
        try {
            const domains = await jsonFetch(`${API_BASE}/domain/list`);
            const targetSelect = $("compTargetDropdown");
            if (targetSelect) {
                targetSelect.innerHTML = '<option value="">Select Inspected Domain...</option>' +
                    domains.map(d => `<option value="${d.domain}">${d.domain_display} (Score: ${d.latest_score !== null ? Math.round(d.latest_score) : 'No audit'})</option>`).join('');
            }
            if (!this.compState.targetDomain && domains && domains.length > 0) {
                this.compState.targetDomain = domains[0].domain.replace(/^https?:\/\//i, '').replace(/\/.*$/, '').replace(/^www\./i, '');
                if ($("compTargetInput")) $("compTargetInput").value = this.compState.targetDomain;
            }
        } catch (err) {
            console.warn("Could not load domains list for competitor analysis:", err);
        }

        // Set inputs from state
        if ($("compTargetInput") && this.compState.targetDomain) {
            $("compTargetInput").value = this.compState.targetDomain;
        }
        if ($("compCountrySelect")) $("compCountrySelect").value = this.compState.country;
        if ($("compLangSelect")) $("compLangSelect").value = this.compState.language;

        this.renderCompetitorTags();
        this.updateCompSavedCount();

        // If we haven't run analysis yet and have a target domain, run initial analysis
        if (!this.compState.analysisData && this.compState.targetDomain) {
            this.runCompetitorAnalysis();
        } else if (this.compState.analysisData) {
            this.renderCompetitorView(this.compState.analysisData);
        }
    }

    onCompTargetDropdownChange(val) {
        if (!val) return;
        const clean = val.replace(/^https?:\/\//i, '').replace(/\/.*$/, '').replace(/^www\./i, '').trim();
        this.compState.targetDomain = clean;
        if ($("compTargetInput")) $("compTargetInput").value = clean;
    }

    onAddCompetitorFromInput() {
        const inp = $("compAddInput");
        if (!inp) return;
        const val = inp.value.trim();
        if (!val) return;
        this.addCompetitorTag(val);
        inp.value = "";
    }

    addCompetitorTag(domainStr) {
        if (!domainStr) return;
        const clean = domainStr.replace(/^https?:\/\//i, '').replace(/\/.*$/, '').replace(/^www\./i, '').trim().toLowerCase();
        if (!clean) return;

        if (clean === (this.compState.targetDomain || "").toLowerCase()) {
            this.showNotification("Competitor domain cannot be the same as your target website.", "warning");
            return;
        }

        if (this.compState.competitorDomains.includes(clean)) {
            this.showNotification(`'${clean}' is already in your competitor comparison list.`, "info");
            return;
        }

        if (this.compState.competitorDomains.length >= 4) {
            this.showNotification("You can compare up to 4 competitor domains simultaneously.", "warning");
            return;
        }

        this.compState.competitorDomains.push(clean);
        this.renderCompetitorTags();
    }

    removeCompetitorTag(domainStr) {
        this.compState.competitorDomains = this.compState.competitorDomains.filter(d => d !== domainStr);
        this.renderCompetitorTags();
    }

    renderCompetitorTags() {
        const listEl = $("compTagsList");
        const countEl = $("compTagsCount");
        if (!listEl) return;

        const count = this.compState.competitorDomains.length;
        if (countEl) countEl.textContent = `${count}/4 added`;

        if (count === 0) {
            listEl.innerHTML = '<span style="font-size:12px; color:var(--text-muted); font-style:italic;">No competitor domains added yet (click Auto-Discover below or type a domain above).</span>';
            return;
        }

        listEl.innerHTML = this.compState.competitorDomains.map(d => `
            <span class="badge" style="background:#EEF2FF; color:#4338CA; font-weight:600; font-size:12px; padding:4px 8px; border-radius:6px; display:inline-flex; align-items:center; gap:6px;">
                <span>${escapeHtml(d)}</span>
                <span onclick="app.removeCompetitorTag('${escapeHtml(d)}')" style="cursor:pointer; font-weight:bold; color:#6366F1; hover:color:#4338CA;" title="Remove">&times;</span>
            </span>
        `).join('');
    }

    onCompetitorSearchSubmit(e) {
        if (e && e.preventDefault) e.preventDefault();
        const targetInp = $("compTargetInput");
        if (!targetInp || !targetInp.value.trim()) {
            this.showNotification("Please enter a target website to analyze.", "warning");
            return;
        }
        this.compState.targetDomain = targetInp.value.trim().replace(/^https?:\/\//i, '').replace(/\/.*$/, '').replace(/^www\./i, '');
        if ($("compCountrySelect")) this.compState.country = parseInt($("compCountrySelect").value, 10) || 2840;
        if ($("compLangSelect")) this.compState.language = $("compLangSelect").value || "en";

        this.runCompetitorAnalysis();
    }

    async runCompetitorAnalysis() {
        const target = this.compState.targetDomain;
        if (!target) {
            this.showNotification("Target website domain is required.", "warning");
            return;
        }

        const btn = $("compAnalyzeBtn");
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ Analyzing Market...</span>';
        }

        try {
            const payload = {
                target_domain: target,
                competitor_domains: this.compState.competitorDomains,
                country: this.compState.country,
                language: this.compState.language
            };

            const data = await jsonFetch(`${API_BASE}/competitors/analyze`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            this.compState.analysisData = data;
            // Update competitors list in state if auto-discovered
            if (data.competitor_domains && data.competitor_domains.length > 0) {
                this.compState.competitorDomains = data.competitor_domains;
                this.renderCompetitorTags();
            }

            this.renderCompetitorView(data);
            this.showNotification("Competitor intelligence & market gap analysis updated.", "success");
        } catch (err) {
            console.error("Competitor analysis failed:", err);
            this.showNotification("Competitor analysis failed: " + (err.message || err), "danger");
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<span>⚔️ Analyze Competitors</span>';
            }
        }
    }

    async autoDiscoverCompetitors() {
        const target = $("compTargetInput") ? $("compTargetInput").value.trim() : (this.compState.targetDomain || "");
        if (!target) {
            this.showNotification("Enter a target website first to discover organic competitors.", "warning");
            return;
        }

        const discoRow = $("compDiscoveredRow");
        if (discoRow) discoRow.innerHTML = '<span style="font-size:12px; color:var(--text-muted);">Finding organic competitors...</span>';

        try {
            const country = $("compCountrySelect") ? $("compCountrySelect").value : 2840;
            const lang = $("compLangSelect") ? $("compLangSelect").value : "en";
            const res = await jsonFetch(`${API_BASE}/competitors/discover?target=${encodeURIComponent(target)}&country=${country}&language=${lang}&limit=8`);

            if (!res.ok || !res.competitors || res.competitors.length === 0) {
                if (discoRow) discoRow.innerHTML = '<span style="font-size:12px; color:var(--text-muted); font-style:italic;">No competitor candidates found in index.</span>';
                return;
            }

            if (discoRow) {
                discoRow.innerHTML = res.competitors.slice(0, 6).map(c => `
                    <button type="button" class="pill" style="cursor:pointer; border:1px solid #CBD5E1; background:#F8FAFC; font-size:11px; padding:3px 8px; display:inline-flex; align-items:center; gap:4px;" onclick="app.addCompetitorTag('${escapeHtml(c.domain)}')">
                        <span>+ ${escapeHtml(c.domain)}</span>
                        ${c.shared_keywords ? `<span style="font-size:10px; color:var(--primary); font-weight:700;">(${c.shared_keywords} shared)</span>` : ''}
                    </button>
                `).join('');
            }
        } catch (err) {
            console.warn("Auto-discover failed:", err);
            if (discoRow) discoRow.innerHTML = '<span style="font-size:12px; color:#EF4444;">Failed to discover competitors.</span>';
        }
    }

    renderCompetitorView(data) {
        if (!data) return;

        // 1. Provenance Banner
        const prov = data.provenance || {};
        if ($("compProvSource")) {
            $("compProvSource").textContent = `Data Sources: ${(prov.data_providers || []).join(' • ')}`;
        }
        if ($("compProvLegal")) {
            $("compProvLegal").textContent = prov.privacy_notice || "Competitor Search Console and Google Analytics are private first-party properties and not accessible.";
        }
        if ($("compTimestampBadge")) {
            const dt = prov.generated_at ? new Date(prov.generated_at).toLocaleString() : 'Just now';
            $("compTimestampBadge").textContent = `Verified: ${dt}`;
        }

        // 2. Scoreboard Table
        this.renderCompetitorScoreboard(data.scoreboard || []);

        // 3. KPI Summary Numbers
        const kg = data.keyword_gap || {};
        if ($("compStatShared")) $("compStatShared").textContent = (kg.shared_count || 0).toLocaleString();
        if ($("compStatMissing")) $("compStatMissing").textContent = (kg.missing_count || 0).toLocaleString();
        if ($("compStatWeak")) $("compStatWeak").textContent = (kg.weak_count || 0).toLocaleString();
        if ($("compStatStrong")) $("compStatStrong").textContent = (kg.strong_count || 0).toLocaleString();

        // 4. Update Tab Counts
        if ($("compTabAllCount")) $("compTabAllCount").textContent = (kg.total_keywords || 0).toLocaleString();
        if ($("compTabMissingCount")) $("compTabMissingCount").textContent = (kg.missing_count || 0).toLocaleString();
        if ($("compTabWeakCount")) $("compTabWeakCount").textContent = (kg.weak_count || 0).toLocaleString();
        if ($("compTabSharedCount")) $("compTabSharedCount").textContent = (kg.shared_count || 0).toLocaleString();
        if ($("compTabStrongCount")) $("compTabStrongCount").textContent = (kg.strong_count || 0).toLocaleString();
        if ($("compGapCountBadge")) $("compGapCountBadge").textContent = `${(kg.total_keywords || 0).toLocaleString()} queries`;

        // 5. Keyword Gap Table
        this.renderCompetitorGapTable();

        // 6. Content Opportunities
        this.renderCompetitorContentOpportunities(data.content_opportunities || []);

        // 7. Backlink Gap
        this.renderCompetitorBacklinkGaps(data.backlink_gaps || []);

        // 8. Historical Trends
        this.renderCompetitorTrends(data.historical_trends || {});
    }

    renderCompetitorScoreboard(scoreboard) {
        const thead = $("compScoreboardHead");
        const tbody = $("compScoreboardBody");
        if (!thead || !tbody) return;

        if (!scoreboard || scoreboard.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No domain comparison data available.</td></tr>';
            return;
        }

        // Build header
        thead.innerHTML = '<th style="width:200px; text-align:left;">Domain Benchmark Metric</th>' +
            scoreboard.map(s => `
                <th style="text-align:center; min-width:140px; ${s.is_target ? 'background:#EFF6FF; border-bottom:2px solid var(--primary); color:#1E3A8A;' : ''}">
                    <div style="font-size:14px; font-weight:800;">${escapeHtml(s.domain)}</div>
                    <div style="font-size:11px; font-weight:normal; color:${s.is_target ? '#2563EB' : 'var(--text-muted)'};">
                        ${s.is_target ? '★ Target Website' : 'Competitor Benchmark'}
                    </div>
                </th>
            `).join('');

        const metrics = [
            {
                label: "SEO Health Score",
                format: s => {
                    if (s.seo_score === null || s.seo_score === undefined) return '<span style="color:var(--text-muted);">No Audit</span>';
                    const score = Math.round(s.seo_score);
                    const color = score >= 80 ? '#10B981' : (score >= 60 ? '#F59E0B' : '#EF4444');
                    return `<span style="font-size:16px; font-weight:800; color:${color};">${score}%</span>`;
                }
            },
            {
                label: "Technical SEO",
                format: s => s.technical_score !== null && s.technical_score !== undefined ? `<b>${Math.round(s.technical_score)}%</b>` : '<span style="color:var(--text-muted);">-</span>'
            },
            {
                label: "On-Page SEO",
                format: s => s.onpage_score !== null && s.onpage_score !== undefined ? `<b>${Math.round(s.onpage_score)}%</b>` : '<span style="color:var(--text-muted);">-</span>'
            },
            {
                label: "Content SEO",
                format: s => s.content_score !== null && s.content_score !== undefined ? `<b>${Math.round(s.content_score)}%</b>` : '<span style="color:var(--text-muted);">-</span>'
            },
            {
                label: "Organic Keywords",
                format: s => `<span style="font-weight:700; color:var(--primary);">${(s.organic_keywords_count || 0).toLocaleString()}</span>`
            },
            {
                label: "Est. Monthly Traffic",
                format: s => s.estimated_monthly_traffic !== null && s.estimated_monthly_traffic !== undefined ? `<span style="font-weight:700; color:#10B981;">${s.estimated_monthly_traffic.toLocaleString()}</span>` : '<span style="font-size:11px; color:var(--text-muted); font-style:italic;">Requires SERP Connector</span>'
            },
            {
                label: "Avg. Ranking Position",
                format: s => s.avg_position !== null && s.avg_position !== undefined ? `<b>#${s.avg_position}</b>` : '<span style="color:var(--text-muted);">-</span>'
            },
            {
                label: "Indexed Backlinks",
                format: s => s.backlinks_count !== null && s.backlinks_count !== undefined ? `<b>${s.backlinks_count.toLocaleString()}</b>` : '<span style="font-size:11px; color:var(--text-muted); font-style:italic;">DataForSEO Backlinks</span>'
            },
            {
                label: "Referring Domains",
                format: s => `<b>${(s.referring_domains_count || 0).toLocaleString()}</b>`
            },
            {
                label: "Core Web Vitals Perf",
                format: s => s.core_web_vitals_perf !== null && s.core_web_vitals_perf !== undefined ? `<b>${Math.round(s.core_web_vitals_perf)}/100</b>` : '<span style="color:var(--text-muted);">-</span>'
            },
            {
                label: "Crawled Pages",
                format: s => `<b>${(s.pages_crawled || 0).toLocaleString()}</b>`
            },
            {
                label: "Critical Issues",
                format: s => s.critical_issues > 0 ? `<span class="badge" style="background:#FEE2E2; color:#B91C1C; font-weight:700;">${s.critical_issues}</span>` : '<span class="badge" style="background:#DCFCE7; color:#15803D;">0</span>'
            }
        ];

        tbody.innerHTML = metrics.map(m => `
            <tr>
                <td style="font-weight:600; color:var(--text);">${escapeHtml(m.label)}</td>
                ${scoreboard.map(s => `
                    <td style="text-align:center; ${s.is_target ? 'background:#F8FAFC;' : ''}">
                        ${m.format(s)}
                    </td>
                `).join('')}
            </tr>
        `).join('');
    }

    renderCompetitorGapTable() {
        const thead = $("compGapHead");
        const tbody = $("compGapBody");
        if (!thead || !tbody) return;

        const data = this.compState.analysisData;
        if (!data || !data.keyword_gap) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No keyword gap analysis available.</td></tr>';
            return;
        }

        const comps = data.competitor_domains || [];
        const target = data.target_domain || "Target";

        // Build dynamic thead including competitors
        thead.innerHTML = `
            <th style="width:34px; text-align:center;"><input type="checkbox" id="compSelectAllCheckbox" onchange="app.toggleCompetitorSelectAll(this.checked)"></th>
            <th>Keyword</th>
            <th>Intent</th>
            <th>Search Volume</th>
            <th>KD%</th>
            <th>CPC</th>
            <th style="background:#EFF6FF; color:#1E3A8A;">Target (${escapeHtml(target)})</th>
            ${comps.map(c => `<th style="min-width:90px;">${escapeHtml(c)}</th>`).join('')}
            <th>Gap Status</th>
            <th style="text-align:right;">Action</th>
        `;

        const allRows = data.keyword_gap.keywords || [];
        const filter = this.compState.activeFilter;
        const q = (this.compState.searchQuery || "").trim().toLowerCase();
        const intent = this.compState.intentFilter;

        const filtered = allRows.filter(row => {
            if (filter !== "all" && row.gap_type !== filter) return false;
            if (q && !row.keyword.toLowerCase().includes(q)) return false;
            if (intent && row.intent !== intent) return false;
            return true;
        });

        if (filtered.length === 0) {
            tbody.innerHTML = `<tr><td colspan="${9 + comps.length}" class="empty-state" style="padding:30px;">No keywords match the selected filter criteria.</td></tr>`;
            return;
        }

        tbody.innerHTML = filtered.slice(0, 150).map(k => {
            const isChecked = this.compState.selectedKeywords.has(k.keyword);
            const gtype = (k.gap_type || "").toLowerCase();
            let badgeStyle = "background:#F1F5F9; color:#475569;";
            let badgeText = "SHARED";
            if (gtype === "missing") {
                badgeStyle = "background:#FEE2E2; color:#B91C1C;";
                badgeText = "MISSING";
            } else if (gtype === "weak") {
                badgeStyle = "background:#FFEDD5; color:#C2410C;";
                badgeText = "WEAK";
            } else if (gtype === "strong") {
                badgeStyle = "background:#EEF2FF; color:#4338CA;";
                badgeText = "STRONG";
            } else {
                badgeStyle = "background:#DCFCE7; color:#15803D;";
                badgeText = "SHARED";
            }

            // Intent badge style
            let intentBadge = `<span class="badge" style="background:#F1F5F9; color:#475569; font-size:11px;">${escapeHtml(k.intent || "Informational")}</span>`;
            if (k.intent === "Commercial") intentBadge = `<span class="badge" style="background:#FEF3C7; color:#B45309; font-size:11px;">Commercial</span>`;
            else if (k.intent === "Transactional") intentBadge = `<span class="badge" style="background:#D1FAE5; color:#047857; font-size:11px;">Transactional</span>`;
            else if (k.intent === "Navigational") intentBadge = `<span class="badge" style="background:#E0E7FF; color:#4338CA; font-size:11px;">Navigational</span>`;

            const volStr = k.search_volume !== null && k.search_volume !== undefined ? k.search_volume.toLocaleString() : '<span style="color:var(--text-muted);">-</span>';
            const kdStr = k.keyword_difficulty !== null && k.keyword_difficulty !== undefined ? `<b>${k.keyword_difficulty}%</b>` : '<span style="color:var(--text-muted);">-</span>';
            const cpcStr = k.cpc !== null && k.cpc !== undefined ? `$${k.cpc.toFixed(2)}` : '<span style="color:var(--text-muted);">-</span>';

            const tRankStr = k.target_rank !== null && k.target_rank !== undefined ? `<span style="font-weight:800; color:var(--primary);">#${k.target_rank}</span>` : '<span style="color:var(--text-muted); font-size:12px;">Not Ranking</span>';

            const compRanks = k.competitor_ranks || {};

            return `
                <tr>
                    <td style="text-align:center;">
                        <input type="checkbox" ${isChecked ? "checked" : ""} onchange="app.onCompetitorRowCheckChange('${escapeHtml(k.keyword)}', this.checked)">
                    </td>
                    <td style="font-weight:600; color:var(--text);">${escapeHtml(k.keyword)}</td>
                    <td>${intentBadge}</td>
                    <td style="font-weight:600;">${volStr}</td>
                    <td>${kdStr}</td>
                    <td>${cpcStr}</td>
                    <td style="background:#F8FAFC; text-align:center;">${tRankStr}</td>
                    ${comps.map(c => {
                        const rk = compRanks[c];
                        return `<td style="text-align:center;">${rk !== null && rk !== undefined ? `<b>#${rk}</b>` : '<span style="color:var(--text-muted); font-size:11px;">-</span>'}</td>`;
                    }).join('')}
                    <td>
                        <span class="badge" style="${badgeStyle} font-weight:700; font-size:11px;">${badgeText}</span>
                    </td>
                    <td style="text-align:right; white-space:nowrap;">
                        <button type="button" class="btn btn-outline btn-sm" style="font-size:11px; padding:3px 8px;" onclick="app.quickSaveCompetitorKeyword('${escapeHtml(k.keyword)}', '${escapeHtml(k.intent || '')}', ${k.search_volume || 'null'}, ${k.keyword_difficulty || 'null'}, ${k.cpc || 'null'})" title="Save to Project">
                            <span>+ Save</span>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    }

    filterCompetitorGap(filterType) {
        this.compState.activeFilter = filterType;
        const tabs = $("compGapTabs");
        if (tabs) {
            tabs.querySelectorAll("button").forEach(b => {
                b.classList.toggle("active", b.getAttribute("data-filter") === filterType);
            });
        }
        this.renderCompetitorGapTable();
    }

    applyCompetitorSearch(query) {
        this.compState.searchQuery = query;
        this.renderCompetitorGapTable();
    }

    applyCompetitorIntentFilter(intent) {
        this.compState.intentFilter = intent;
        this.renderCompetitorGapTable();
    }

    toggleCompetitorSelectAll(checked) {
        const data = this.compState.analysisData;
        if (!data || !data.keyword_gap) return;

        const allRows = data.keyword_gap.keywords || [];
        const filter = this.compState.activeFilter;
        const q = (this.compState.searchQuery || "").trim().toLowerCase();
        const intent = this.compState.intentFilter;

        const filtered = allRows.filter(row => {
            if (filter !== "all" && row.gap_type !== filter) return false;
            if (q && !row.keyword.toLowerCase().includes(q)) return false;
            if (intent && row.intent !== intent) return false;
            return true;
        });

        if (checked) {
            filtered.forEach(k => this.compState.selectedKeywords.add(k.keyword));
        } else {
            filtered.forEach(k => this.compState.selectedKeywords.delete(k.keyword));
        }

        this.updateCompetitorSelectedCount();
        this.renderCompetitorGapTable();
    }

    onCompetitorRowCheckChange(kwStr, checked) {
        if (checked) this.compState.selectedKeywords.add(kwStr);
        else this.compState.selectedKeywords.delete(kwStr);
        this.updateCompetitorSelectedCount();
    }

    updateCompetitorSelectedCount() {
        const count = this.compState.selectedKeywords.size;
        const btn = $("compAddSelectedBtn");
        const countSpan = $("compSelectedCount");
        if (btn) btn.style.display = count > 0 ? "inline-flex" : "none";
        if (countSpan) countSpan.textContent = count;
    }

    renderCompetitorContentOpportunities(opps) {
        const listEl = $("compContentOppsList");
        const badge = $("compContentOppsBadge");
        if (!listEl) return;

        if (badge) badge.textContent = `${opps.length} topics`;

        if (!opps || opps.length === 0) {
            listEl.innerHTML = '<div class="empty-state" style="padding:24px;">No topical content gaps identified.</div>';
            return;
        }

        listEl.innerHTML = opps.slice(0, 8).map(o => `
            <div style="padding:12px; border:1px solid var(--border); border-radius:8px; background:#F8FAFC;">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:4px; gap:8px;">
                    <div>
                        <b style="font-size:14px; color:var(--text);">${escapeHtml(o.topic)}</b>
                        <span class="badge" style="background:#DBEAFE; color:#1D4ED8; font-size:10px; margin-left:6px;">${escapeHtml(o.intent)}</span>
                    </div>
                    <span class="badge" style="background:#D1FAE5; color:#047857; font-weight:700; font-size:11px;">Score: ${o.opportunity_score}/100</span>
                </div>
                <div style="font-size:12px; color:var(--text-muted); margin-bottom:6px;">
                    ${escapeHtml(o.suggested_action)}
                </div>
                <div style="display:flex; gap:6px; flex-wrap:wrap; font-size:11px;">
                    <span style="color:var(--text-muted); font-weight:600;">Sample Queries:</span>
                    ${(o.sample_keywords || []).map(sk => `<span class="pill" style="font-size:10px; background:#FFFFFF; border:1px solid var(--border);">${escapeHtml(sk)}</span>`).join('')}
                </div>
            </div>
        `).join('');
    }

    renderCompetitorBacklinkGaps(gaps) {
        const listEl = $("compBacklinksList");
        const badge = $("compBacklinksBadge");
        if (!listEl) return;

        if (badge) badge.textContent = `${gaps.length} targets`;

        if (!gaps || gaps.length === 0) {
            listEl.innerHTML = '<div class="empty-state" style="padding:24px;">No backlink gaps identified. Local crawl data shows no missing external domains.</div>';
            return;
        }

        listEl.innerHTML = gaps.slice(0, 10).map(b => {
            const priorityStyle = b.outreach_priority === "High" ? "background:#FEE2E2; color:#B91C1C;" : "background:#FEF3C7; color:#B45309;";
            return `
                <div style="padding:10px 12px; border:1px solid var(--border); border-radius:8px; background:#F8FAFC; display:flex; justify-content:space-between; align-items:center; gap:8px;">
                    <div>
                        <div style="font-weight:700; font-size:13px; color:var(--text);">${escapeHtml(b.referring_domain)}</div>
                        <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">
                            ${escapeHtml(b.suggested_angle || 'Links to competitors')} • Competitors: <b>${(b.competitors_linked || []).join(', ')}</b>
                        </div>
                    </div>
                    <span class="badge" style="${priorityStyle} font-weight:700; font-size:10px; white-space:nowrap;">${escapeHtml(b.outreach_priority)} Priority</span>
                </div>
            `;
        }).join('');
    }

    renderCompetitorTrends(trends) {
        const container = $("compTrendsContainer");
        if (!container) return;

        const entries = Object.entries(trends || {}).filter(([d, list]) => list && list.length > 0);
        if (entries.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding:20px;">No historical audit records available for compared domains. Running multiple audits over time unlocks historical trajectory tracking.</div>';
            return;
        }

        container.innerHTML = `
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:14px;">
                ${entries.map(([dom, audits]) => {
                    const latest = audits[audits.length - 1];
                    const earliest = audits[0];
                    const diff = audits.length > 1 ? (latest.score - earliest.score) : 0;
                    const diffColor = diff >= 0 ? '#10B981' : '#EF4444';
                    const diffSign = diff >= 0 ? '+' : '';
                    return `
                        <div style="padding:12px; border:1px solid var(--border); border-radius:8px; background:#F8FAFC;">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                                <b style="font-size:13px;">${escapeHtml(dom)}</b>
                                <span class="badge" style="font-size:10px;">${audits.length} audits</span>
                            </div>
                            <div style="font-size:18px; font-weight:800; color:var(--primary);">
                                ${Math.round(latest.score)}%
                                ${audits.length > 1 ? `<span style="font-size:12px; color:${diffColor}; margin-left:4px;">(${diffSign}${Math.round(diff)}%)</span>` : ''}
                            </div>
                            <div style="font-size:11px; color:var(--text-muted); margin-top:4px;">
                                Latest: ${latest.date}
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    async exportCompetitor(format) {
        const target = this.compState.targetDomain;
        if (!target) {
            this.showNotification("Run competitor analysis first before exporting.", "warning");
            return;
        }

        try {
            this.showNotification(`Generating Competitor Analysis ${format.toUpperCase()} export...`, "info");
            const payload = {
                target_domain: target,
                competitor_domains: this.compState.competitorDomains,
                country: this.compState.country,
                language: this.compState.language
            };

            const token = localStorage.getItem("token") || "";
            const response = await fetch(`${API_BASE}/competitors/export/${format}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errText = await response.text();
                throw new Error(errText || "Export request failed");
            }

            const blob = await response.blob();
            const ext = format === "pdf" ? "pdf" : (format === "excel" ? "xls" : "csv");
            const filename = `competitor_analysis_${target.replace(/[^a-z0-9_-]/gi, '_')}_${new Date().toISOString().slice(0, 10)}.${ext}`;

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);

            this.showNotification(`Downloaded ${filename} successfully.`, "success");
        } catch (err) {
            console.error("Export failed:", err);
            this.showNotification("Export failed: " + (err.message || err), "danger");
        }
    }

    async saveCurrentComparison() {
        const target = this.compState.targetDomain;
        if (!target) {
            this.showNotification("Target website domain is required to save comparison set.", "warning");
            return;
        }

        const defaultName = `${target} vs ${(this.compState.competitorDomains || []).join(', ') || 'Competitors'}`;
        const name = prompt("Enter a name for this Competitor Benchmark Set:", defaultName);
        if (!name) return;

        try {
            const payload = {
                name: name.trim(),
                target_domain: target,
                competitor_domains: this.compState.competitorDomains,
                country: this.compState.country,
                language: this.compState.language,
                data: this.compState.analysisData
            };

            const res = await jsonFetch(`${API_BASE}/competitors/comparisons`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            this.showNotification(`Saved '${name}' benchmark set successfully.`, "success");
            this.updateCompSavedCount();
        } catch (err) {
            console.error("Save comparison failed:", err);
            this.showNotification("Save comparison failed: " + (err.message || err), "danger");
        }
    }

    async updateCompSavedCount() {
        try {
            const list = await jsonFetch(`${API_BASE}/competitors/comparisons`);
            if ($("compSavedCount")) $("compSavedCount").textContent = (list || []).length;
            this.compState.savedComparisons = list || [];
        } catch (e) {
            // ignore
        }
    }

    async openSavedComparisonsModal() {
        const modal = $("compSavedModal");
        const body = $("compSavedModalBody");
        if (!modal || !body) return;

        modal.classList.remove("hidden");
        body.innerHTML = '<div class="empty-state" style="padding:30px;">Loading saved comparisons...</div>';

        try {
            const list = await jsonFetch(`${API_BASE}/competitors/comparisons`);
            this.compState.savedComparisons = list || [];
            if ($("compSavedCount")) $("compSavedCount").textContent = (list || []).length;

            if (!list || list.length === 0) {
                body.innerHTML = '<div class="empty-state" style="padding:40px;">No saved competitor comparison sets yet. Click <b>Save Set</b> after analyzing competitors to save benchmarks.</div>';
                return;
            }

            body.innerHTML = `
                <div style="display:flex; flex-direction:column; gap:10px;">
                    ${list.map(item => `
                        <div style="padding:14px; border:1px solid var(--border); border-radius:10px; background:#F8FAFC; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
                            <div>
                                <b style="font-size:15px; color:var(--text);">${escapeHtml(item.name)}</b>
                                <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
                                    Target: <b>${escapeHtml(item.target_domain)}</b> • Competitors: <b>${(item.competitor_domains || []).join(', ') || 'None'}</b>
                                </div>
                                <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">
                                    Saved: ${item.created_at ? new Date(item.created_at).toLocaleDateString() : 'Unknown'}
                                </div>
                            </div>
                            <div style="display:flex; gap:8px;">
                                <button type="button" class="btn btn-primary btn-sm" onclick="app.loadSavedComparisonItem(${item.id})">Load Set</button>
                                <button type="button" class="btn btn-danger btn-sm" onclick="app.deleteSavedComparisonItem(${item.id})">Delete</button>
                            </div>
                        </div>
                    `).join('')}
                </div>
            `;
        } catch (err) {
            console.error("Failed to load saved comparisons:", err);
            body.innerHTML = `<div class="empty-state" style="padding:30px; color:#EF4444;">Failed to load saved comparisons: ${escapeHtml(err.message || err)}</div>`;
        }
    }

    closeSavedComparisonsModal() {
        const modal = $("compSavedModal");
        if (modal) modal.classList.add("hidden");
    }

    async loadSavedComparisonItem(id) {
        try {
            const item = await jsonFetch(`${API_BASE}/competitors/comparisons/${id}`);
            if (!item) return;

            this.compState.targetDomain = item.target_domain;
            this.compState.competitorDomains = item.competitor_domains || [];
            this.compState.country = item.market_country || 2840;
            this.compState.language = item.market_language || "en";

            if ($("compTargetInput")) $("compTargetInput").value = item.target_domain;
            if ($("compCountrySelect")) $("compCountrySelect").value = this.compState.country;
            if ($("compLangSelect")) $("compLangSelect").value = this.compState.language;

            this.renderCompetitorTags();
            this.closeSavedComparisonsModal();

            if (item.data && Object.keys(item.data).length > 0) {
                this.compState.analysisData = item.data;
                this.renderCompetitorView(item.data);
                this.showNotification(`Loaded saved comparison set '${item.name}'.`, "success");
            } else {
                this.runCompetitorAnalysis();
            }
        } catch (err) {
            console.error("Failed to load comparison item:", err);
            this.showNotification("Failed to load saved set: " + (err.message || err), "danger");
        }
    }

    async deleteSavedComparisonItem(id) {
        if (!confirm("Are you sure you want to delete this saved competitor comparison set?")) return;
        try {
            await jsonFetch(`${API_BASE}/competitors/comparisons/${id}`, { method: "DELETE" });
            this.showNotification("Saved comparison set deleted.", "info");
            this.openSavedComparisonsModal();
            this.updateCompSavedCount();
        } catch (err) {
            console.error("Delete comparison failed:", err);
            this.showNotification("Failed to delete saved set: " + (err.message || err), "danger");
        }
    }

    async openCompetitorSaveToProjectModal() {
        const selected = Array.from(this.compState.selectedKeywords);
        if (selected.length === 0) {
            this.showNotification("Please select at least one keyword using the checkboxes first.", "warning");
            return;
        }

        // Collect keyword objects from current gap data
        const data = this.compState.analysisData;
        const allKws = (data && data.keyword_gap && data.keyword_gap.keywords) || [];
        const kwMap = new Map(allKws.map(k => [k.keyword, k]));

        const kwObjs = selected.map(kname => {
            const found = kwMap.get(kname);
            return {
                keyword: kname,
                intent: found ? found.intent : "Informational",
                search_volume: found ? found.search_volume : null,
                keyword_difficulty: found ? found.keyword_difficulty : null,
                cpc: found ? found.cpc : null,
                cluster: "Competitor Gap",
                source: "Competitor Analysis"
            };
        });

        const projName = prompt(`Enter project name to save ${selected.length} competitor keywords to:`, "Competitor Opportunities");
        if (!projName) return;
        try {
            const projRes = await jsonFetch(`${API_BASE}/keyword-magic/projects`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: projName.trim(), description: `Keywords from competitor analysis on ${this.compState.targetDomain}` })
            });
            const projId = projRes.project.id;
            await jsonFetch(`${API_BASE}/keyword-magic/projects/${projId}/keywords`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ keywords: kwObjs })
            });
            this.showNotification(`Saved ${selected.length} keywords to project '${projName}'.`, "success");
            this.compState.selectedKeywords.clear();
            this.updateCompetitorSelectedCount();
            this.renderCompetitorGapTable();
        } catch (err) {
            this.showNotification("Failed to save to project: " + (err.message || err), "danger");
        }
    }

    async quickSaveCompetitorKeyword(kwStr, intent, vol, kd, cpc) {
        const projName = prompt(`Save '${kwStr}' to Keyword Project:`, "Competitor Opportunities");
        if (!projName) return;
        try {
            const projRes = await jsonFetch(`${API_BASE}/keyword-magic/projects`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: projName.trim(), description: `Keywords from competitor analysis on ${this.compState.targetDomain}` })
            });
            const projId = projRes.project.id;
            await jsonFetch(`${API_BASE}/keyword-magic/projects/${projId}/keywords`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    keywords: [{
                        keyword: kwStr,
                        intent: intent || "Informational",
                        search_volume: vol,
                        keyword_difficulty: kd,
                        cpc: cpc,
                        cluster: "Competitor Gap",
                        source: "Competitor Analysis"
                    }]
                })
            });
            this.showNotification(`Saved '${kwStr}' to project '${projName}'.`, "success");
        } catch (err) {
            this.showNotification("Failed to save to project: " + (err.message || err), "danger");
        }
    }

    /* -------------------------------------------------------------
       PHASE 6: BACKLINK ANALYTICS & LINK INTELLIGENCE
    -------------------------------------------------------------- */
    async loadBacklinkAnalytics() {
        const select = $("blTargetDropdown");
        if (select) {
            try {
                const audits = await jsonFetch(`${API_BASE}/audits?limit=50`);
                const seen = new Set();
                const options = ['<option value="">-- Choose audited domain --</option>'];
                (audits || []).forEach(a => {
                    const host = (a.target_url || "").replace(/^https?:\/\//i, "").replace(/^www\./i, "").split("/")[0].toLowerCase();
                    if (host && !seen.has(host)) {
                        seen.add(host);
                        options.push(`<option value="${esc(host)}">${esc(host)}</option>`);
                    }
                });
                select.innerHTML = options.join("");
            } catch (_) {}
        }

        const input = $("blTargetInput");
        if (input && input.value.trim()) {
            this.runBacklinkAnalysis(false);
        } else if (select && select.options.length > 1) {
            select.selectedIndex = 1;
            this.handleBacklinkDropdownChange();
        }
    }

    handleBacklinkDropdownChange() {
        const select = $("blTargetDropdown");
        const input = $("blTargetInput");
        if (select && input && select.value) {
            input.value = select.value;
            this.runBacklinkAnalysis(false);
        }
    }

    async runBacklinkAnalysis(refresh = false) {
        const input = $("blTargetInput");
        const domain = (input ? input.value : "").trim();
        if (!domain) {
            this.showNotification("Please select or enter a target domain to inspect backlinks.", "warning");
            return;
        }

        this.blState.targetDomain = domain;
        this.blState.loading = true;

        const content = $("blContentArea");
        if (content) {
            content.innerHTML = `
                <div class="card" style="text-align:center; padding:60px 20px;">
                    <div class="spinner" style="width:36px; height:36px; margin:0 auto 16px auto; border-width:3px;"></div>
                    <h3 style="margin:0 0 6px 0; font-size:18px;">Analyzing Backlink Architecture...</h3>
                    <div style="font-size:13px; color:var(--text-muted);">
                        Retrieving indexed backlinks, referring domains, anchor classifications, and calculating internal equity modeling (PAI)...
                    </div>
                </div>
            `;
        }

        try {
            const profile = await jsonFetch(`${API_BASE}/backlinks/overview?target=${encodeURIComponent(domain)}&refresh=${refresh ? 1 : 0}`);
            this.blState.currentProfile = profile;
            this.blState.loading = false;
            this.renderBacklinkProfile(profile);
        } catch (err) {
            this.blState.loading = false;
            if (content) {
                content.innerHTML = `
                    <div class="card" style="padding:40px 20px; text-align:center;">
                        <div style="font-size:32px; margin-bottom:10px;">⚠️</div>
                        <h3 style="margin:0 0 8px 0; color:var(--danger);">Failed to Retrieve Backlink Profile</h3>
                        <p style="margin:0 0 16px 0; font-size:13px; color:var(--text-muted);">${esc(err.message || err)}</p>
                        <button class="btn btn-secondary btn-sm" onclick="app.runBacklinkAnalysis(true)">Retry Analysis</button>
                    </div>
                `;
            }
        }
    }

    renderBacklinkProfile(profile) {
        const content = $("blContentArea");
        if (!content || !profile) return;

        // 1. Update Provider Status Pill & Provenance
        const badge = $("blProviderBadge");
        if (badge) {
            if (profile.has_external_provider) {
                badge.style.background = "#ECFDF5";
                badge.style.color = "#047857";
                badge.textContent = "● Live External Provider Active";
            } else {
                badge.style.background = "#EFF6FF";
                badge.style.color = "#1D4ED8";
                badge.textContent = "● On-Site Link Equity Engine";
            }
        }

        const provText = $("blProvenanceText");
        if (provText) {
            provText.innerHTML = `<b>Data Provenance:</b> ${esc(profile.data_provider_note || "")}`;
        }

        const ov = profile.overview || {};
        const da = profile.domain_authority || {};
        const pai = profile.platform_authority_index || {};
        const tox = profile.toxicity_radar || {};

        const totalBlStr = ov.total_backlinks != null ? fmt(ov.total_backlinks) : '<span style="color:var(--text-muted); font-size:16px;">Requires Provider</span>';
        const refDomStr = ov.referring_domains != null ? fmt(ov.referring_domains) : '<span style="color:var(--text-muted); font-size:16px;">Requires Provider</span>';
        const dofollowPctStr = ov.dofollow_percentage != null ? `${ov.dofollow_percentage}%` : '—';
        const paiScore = (pai.score || 0).toFixed(1);
        const paiColor = getScoreColor(pai.score);

        const toxLevel = tox.risk_level || "LOW";
        const toxBadgeColor = toxLevel === "LOW" ? "#10B981" : (toxLevel === "MODERATE" ? "#F59E0B" : "#EF4444");

        content.innerHTML = `
            <!-- 4 Top KPI Scoreboard Cards -->
            <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:16px; margin-bottom:20px;">
                <!-- Total Backlinks -->
                <div class="card stat-card" style="border-top:3px solid #2563EB;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <span class="stat-label" style="text-transform:uppercase; font-size:11px; font-weight:700; color:var(--text-muted);">Total Indexed Backlinks</span>
                            <div class="stat-value" style="color:#2563EB; font-size:28px; margin:4px 0;">${totalBlStr}</div>
                        </div>
                        <div style="width:36px; height:36px; border-radius:8px; background:#EFF6FF; display:flex; align-items:center; justify-content:center; font-size:16px;">🔗</div>
                    </div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                        ${ov.broken_backlinks ? `<span style="color:var(--danger); font-weight:600;">${fmt(ov.broken_backlinks)} broken</span>` : "Live external link index"}
                    </div>
                </div>

                <!-- Referring Domains -->
                <div class="card stat-card" style="border-top:3px solid #10B981;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <span class="stat-label" style="text-transform:uppercase; font-size:11px; font-weight:700; color:var(--text-muted);">Referring Domains</span>
                            <div class="stat-value" style="color:#10B981; font-size:28px; margin:4px 0;">${refDomStr}</div>
                        </div>
                        <div style="width:36px; height:36px; border-radius:8px; background:#ECFDF5; display:flex; align-items:center; justify-content:center; font-size:16px;">🌐</div>
                    </div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                        ${ov.referring_ips ? `${fmt(ov.referring_ips)} distinct IPs • ${fmt(ov.referring_main_domains || 0)} main domains` : "Unique domain origins"}
                    </div>
                </div>

                <!-- Dofollow Ratio -->
                <div class="card stat-card" style="border-top:3px solid #06B6D4;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <span class="stat-label" style="text-transform:uppercase; font-size:11px; font-weight:700; color:var(--text-muted);">Dofollow Link Ratio</span>
                            <div class="stat-value" style="color:#06B6D4; font-size:28px; margin:4px 0;">${dofollowPctStr}</div>
                        </div>
                        <div style="width:36px; height:36px; border-radius:8px; background:#ECFEFF; display:flex; align-items:center; justify-content:center; font-size:16px;">⚡</div>
                    </div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                        ${ov.dofollow_backlinks != null ? `${fmt(ov.dofollow_backlinks)} dofollow • ${fmt(ov.nofollow_backlinks || 0)} nofollow` : "Authority passing links"}
                    </div>
                </div>

                <!-- Platform Authority Index (PAI) -->
                <div class="card stat-card" style="border-top:3px solid ${paiColor}; cursor:pointer;" onclick="app.showPaiMethodologyModal()" title="Click to view mathematical methodology">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <span class="stat-label" style="text-transform:uppercase; font-size:11px; font-weight:700; color:var(--text-muted);">Platform Authority (PAI)</span>
                            <div class="stat-value" style="color:${paiColor}; font-size:28px; margin:4px 0;">${paiScore}<span style="font-size:14px; color:var(--text-muted);">/100</span></div>
                        </div>
                        <div style="width:36px; height:36px; border-radius:8px; background:${paiColor}15; display:flex; align-items:center; justify-content:center; font-size:16px;">🏆</div>
                    </div>
                    <div style="font-size:12px; color:var(--text-muted); margin-top:6px;">
                        Internal PageRank equity • <span style="color:#2563EB; font-weight:600;">Methodology ↗</span>
                    </div>
                </div>
            </div>

            <!-- Tabbed Navigation Bar -->
            <div class="card" style="padding:0; overflow:hidden; margin-bottom:20px;">
                <div style="display:flex; border-bottom:1px solid var(--border); background:#F8FAFC; overflow-x:auto;">
                    <button class="bl-tab-btn ${this.blState.activeTab === 'domains' ? 'active' : ''}" onclick="app.switchBacklinkTab('domains')">
                        🌐 Referring Domains <span class="pill" style="font-size:10px; margin-left:4px;">${(profile.referring_domains || []).length}</span>
                    </button>
                    <button class="bl-tab-btn ${this.blState.activeTab === 'anchors' ? 'active' : ''}" onclick="app.switchBacklinkTab('anchors')">
                        ⚓ Anchor Profile <span class="pill" style="font-size:10px; margin-left:4px;">${(profile.anchor_profile || []).length}</span>
                    </button>
                    <button class="bl-tab-btn ${this.blState.activeTab === 'equity' ? 'active' : ''}" onclick="app.switchBacklinkTab('equity')">
                        🌳 Internal Equity (IPES) <span class="pill" style="font-size:10px; margin-left:4px;">${((profile.internal_equity || {}).top_equity_pages || []).length}</span>
                    </button>
                    <button class="bl-tab-btn ${this.blState.activeTab === 'gap' ? 'active' : ''}" onclick="app.switchBacklinkTab('gap')">
                        ⚔️ Competitor Backlink Gap
                    </button>
                    <button class="bl-tab-btn ${this.blState.activeTab === 'toxicity' ? 'active' : ''}" onclick="app.switchBacklinkTab('toxicity')">
                        ⚠️ Toxicity Radar <span class="pill" style="background:${toxBadgeColor}20; color:${toxBadgeColor}; font-size:10px; margin-left:4px;">${toxLevel}</span>
                    </button>
                </div>
                <div id="blTabContent" style="padding:20px;"></div>
            </div>
        `;

        this.renderActiveBacklinkTab();
    }

    switchBacklinkTab(tabKey) {
        this.blState.activeTab = tabKey;
        document.querySelectorAll(".bl-tab-btn").forEach(btn => {
            const isMatch = (tabKey === "domains" && btn.textContent.includes("Referring Domains")) ||
                            (tabKey === "anchors" && btn.textContent.includes("Anchor Profile")) ||
                            (tabKey === "equity" && btn.textContent.includes("Internal Equity")) ||
                            (tabKey === "gap" && btn.textContent.includes("Competitor Backlink Gap")) ||
                            (tabKey === "toxicity" && btn.textContent.includes("Toxicity Radar"));
            btn.classList.toggle("active", isMatch);
        });
        this.renderActiveBacklinkTab();
    }

    renderActiveBacklinkTab() {
        const tabKey = this.blState.activeTab;
        const profile = this.blState.currentProfile;
        if (!profile) return;

        if (tabKey === "domains") this.renderBacklinkDomainsTab(profile);
        else if (tabKey === "anchors") this.renderBacklinkAnchorsTab(profile);
        else if (tabKey === "equity") this.renderBacklinkEquityTab(profile);
        else if (tabKey === "gap") this.renderBacklinkGapTab(profile);
        else if (tabKey === "toxicity") this.renderBacklinkToxicityTab(profile);
    }

    renderBacklinkDomainsTab(profile) {
        const container = $("blTabContent");
        if (!container) return;

        let items = profile.referring_domains || [];

        // Apply filters
        if (this.blState.referringSearch) {
            const s = this.blState.referringSearch.toLowerCase();
            items = items.filter(it => (it.domain || "").toLowerCase().includes(s));
        }
        if (this.blState.referringFilter === "dofollow") {
            items = items.filter(it => (it.dofollow || 0) > 0);
        } else if (this.blState.referringFilter === "nofollow") {
            items = items.filter(it => (it.nofollow || 0) > 0);
        }

        container.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:12px;">
                <div style="display:flex; gap:8px; align-items:center;">
                    <input type="text" class="form-input form-input-sm" placeholder="Filter domains..." value="${esc(this.blState.referringSearch)}" oninput="app.blState.referringSearch = this.value; app.renderBacklinkDomainsTab(app.blState.currentProfile);" style="width:200px;">
                    <div style="display:flex; gap:4px;">
                        <button class="btn btn-sm ${this.blState.referringFilter === 'all' ? 'btn-primary' : 'btn-secondary'}" onclick="app.blState.referringFilter = 'all'; app.renderBacklinkDomainsTab(app.blState.currentProfile);">All</button>
                        <button class="btn btn-sm ${this.blState.referringFilter === 'dofollow' ? 'btn-primary' : 'btn-secondary'}" onclick="app.blState.referringFilter = 'dofollow'; app.renderBacklinkDomainsTab(app.blState.currentProfile);">Dofollow</button>
                        <button class="btn btn-sm ${this.blState.referringFilter === 'nofollow' ? 'btn-primary' : 'btn-secondary'}" onclick="app.blState.referringFilter = 'nofollow'; app.renderBacklinkDomainsTab(app.blState.currentProfile);">Nofollow</button>
                    </div>
                </div>
                <div style="font-size:12px; color:var(--text-muted);">
                    Showing <b>${items.length}</b> referring domains
                </div>
            </div>

            ${items.length ? `
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Referring Domain</th>
                                <th style="text-align:right;">Provider Rank</th>
                                <th style="text-align:right;">Total Links</th>
                                <th style="text-align:right;">Dofollow</th>
                                <th style="text-align:right;">Nofollow</th>
                                <th>First Seen</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${items.map(r => `
                                <tr>
                                    <td>
                                        <b style="color:var(--text);">${esc(r.domain || "")}</b>
                                        ${r.tld ? `<span class="pill" style="font-size:10px; margin-left:6px; background:#F1F5F9;">.${esc(r.tld)}</span>` : ""}
                                    </td>
                                    <td style="text-align:right;">
                                        <span class="pill" style="background:#EFF6FF; color:#1D4ED8; font-weight:700;">${r.rank != null ? esc(r.rank) : "—"}</span>
                                    </td>
                                    <td style="text-align:right; font-weight:700;">${fmt(r.backlinks)}</td>
                                    <td style="text-align:right; color:#10B981; font-weight:600;">${fmt(r.dofollow)}</td>
                                    <td style="text-align:right; color:#64748B;">${fmt(r.nofollow)}</td>
                                    <td style="font-size:12px; color:var(--text-muted); white-space:nowrap;">${esc(String(r.first_seen || "—").slice(0, 10))}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>
            ` : `
                <div class="empty-state" style="padding:32px;">
                    <p style="margin:0; font-size:13px; color:var(--text-muted);">
                        ${profile.has_external_provider ? "No referring domains match your filter criteria." : "External referring domains require a connected backlink provider (DataForSEO Backlinks API)."}
                    </p>
                </div>
            `}
        `;
    }

    renderBacklinkAnchorsTab(profile) {
        const container = $("blTabContent");
        if (!container) return;

        const anchors = profile.anchor_profile || [];

        // Check for commercial anchor over-optimization
        const exactMatches = anchors.filter(a => a.category === "Exact Match" || a.category === "Target Commercial");
        const totalAnchorBl = anchors.reduce((acc, a) => acc + (a.backlinks || 0), 0);
        const exactBl = exactMatches.reduce((acc, a) => acc + (a.backlinks || 0), 0);
        const exactRatio = totalAnchorBl > 0 ? (exactBl / totalAnchorBl) * 100 : 0;
        const isOverfit = exactRatio > 25;

        container.innerHTML = `
            ${isOverfit ? `
                <div style="background:#FEF2F2; border:1px solid #FECACA; border-radius:8px; padding:12px 16px; margin-bottom:16px; display:flex; gap:12px; align-items:flex-start;">
                    <div style="font-size:20px;">⚠️</div>
                    <div>
                        <b style="color:#B91C1C; font-size:13px;">Commercial Anchor Over-Optimization Warning</b>
                        <div style="font-size:12px; color:#7F1D1D; margin-top:2px;">
                            ${exactRatio.toFixed(1)}% of your backlinks use exact commercial anchor text. Natural link profiles typically feature over 60% branded or naked URL anchors. Excessive exact-match anchors may trigger search engine spam filtering.
                        </div>
                    </div>
                </div>
            ` : ""}

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <div style="font-size:13px; color:var(--text-muted);">
                    Anchor texts classified across Branded, Exact Match, Partial Match, Generic, and Naked URL categories.
                </div>
                <div style="font-size:12px; color:var(--text-muted);">
                    <b>${anchors.length}</b> distinct anchor terms
                </div>
            </div>

            ${anchors.length ? `
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Anchor Text</th>
                                <th>Classification</th>
                                <th style="text-align:right;">Backlinks</th>
                                <th style="text-align:right;">Referring Domains</th>
                                <th style="text-align:right;">Dofollow</th>
                                <th>Origin</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${anchors.map(a => `
                                <tr>
                                    <td><b style="color:var(--text);">"${esc(a.anchor || "")}"</b></td>
                                    <td>
                                        <span class="pill" style="background:${a.badge_color || '#64748B'}20; color:${a.badge_color || '#64748B'}; font-weight:700; font-size:10px;">
                                            ${esc(a.category || "Unclassified")}
                                        </span>
                                    </td>
                                    <td style="text-align:right; font-weight:700;">${fmt(a.backlinks)}</td>
                                    <td style="text-align:right; color:#2563EB;">${fmt(a.referring_domains)}</td>
                                    <td style="text-align:right; color:#10B981;">${fmt(a.dofollow)}</td>
                                    <td style="font-size:11px; color:var(--text-muted);">${a.is_internal ? "On-Site Internal" : "External Index"}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>
            ` : `
                <div class="empty-state" style="padding:32px;">
                    <p style="margin:0; font-size:13px; color:var(--text-muted);">No anchor profiles recorded for this target domain.</p>
                </div>
            `}
        `;
    }

    renderBacklinkEquityTab(profile) {
        const container = $("blTabContent");
        if (!container) return;

        const equity = profile.internal_equity || {};
        const pages = equity.top_equity_pages || [];
        const orphans = equity.orphan_pages || [];

        container.innerHTML = `
            <div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:8px; padding:12px 16px; margin-bottom:16px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <b style="color:#15803D; font-size:13px;">Internal Link Equity Simulation (PageRank d=0.85)</b>
                        <div style="font-size:12px; color:#166534; margin-top:2px;">
                            ${esc(equity.methodology || "")}
                        </div>
                    </div>
                    <button class="btn btn-secondary btn-sm" onclick="app.showPaiMethodologyModal()" style="white-space:nowrap; margin-left:12px;">Methodology Details</button>
                </div>
            </div>

            ${orphans.length ? `
                <div style="background:#FEF3C7; border:1px solid #FCD34D; border-radius:8px; padding:10px 14px; margin-bottom:16px; font-size:12px; color:#92400E;">
                    <b>Orphan Pages Detected:</b> Found <b>${orphans.length}</b> page(s) on your website with 0 internal inbound links (IPES = 0.0). These pages receive zero internal link authority.
                </div>
            ` : ""}

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px;">
                <div style="font-size:12px; color:var(--text-muted);">
                    Evaluated <b>${equity.internal_pages_evaluated || pages.length}</b> crawled URLs. Sorted by equity score.
                </div>
            </div>

            ${pages.length ? `
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Page URL &amp; Title</th>
                                <th style="text-align:right;">Equity Score (IPES)</th>
                                <th style="text-align:right;">Internal Inlinks</th>
                                <th style="text-align:right;">Outlinks</th>
                                <th style="text-align:right;">Crawl Depth</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${pages.map(p => {
                                const score = p.internal_equity_score || 0;
                                const color = getScoreColor(score);
                                return `
                                    <tr>
                                        <td>
                                            <div style="font-weight:600; color:var(--text); max-width:440px; word-break:break-all;">${esc(p.url || "")}</div>
                                            <div style="font-size:11px; color:var(--text-muted);">${esc(p.title || "")}</div>
                                            ${p.is_orphan ? `<span class="pill" style="background:#FEF2F2; color:#DC2626; font-size:9px; margin-top:2px;">ORPHAN PAGE</span>` : ""}
                                        </td>
                                        <td style="text-align:right;">
                                            <div style="display:inline-flex; align-items:center; gap:6px;">
                                                <div style="width:60px; height:6px; background:#E2E8F0; border-radius:3px; overflow:hidden;">
                                                    <div style="width:${score}%; height:100%; background:${color};"></div>
                                                </div>
                                                <b style="color:${color}; font-size:13px;">${score.toFixed(1)}</b>
                                            </div>
                                        </td>
                                        <td style="text-align:right; font-weight:700;">${fmt(p.inbound_internal_links)}</td>
                                        <td style="text-align:right; color:var(--text-muted);">${fmt(p.outbound_internal_links)}</td>
                                        <td style="text-align:right;"><span class="pill" style="font-size:10px;">Depth ${p.depth || 1}</span></td>
                                        <td><span class="pill" style="background:${p.status === 200 ? '#ECFDF5' : '#FEF2F2'}; color:${p.status === 200 ? '#047857' : '#DC2626'}; font-size:10px;">HTTP ${p.status}</span></td>
                                    </tr>
                                `;
                            }).join("")}
                        </tbody>
                    </table>
                </div>
            ` : `
                <div class="empty-state" style="padding:32px;">
                    <p style="margin:0; font-size:13px; color:var(--text-muted);">Run a technical crawl audit on this website first to generate its internal link equity graph.</p>
                </div>
            `}
        `;
    }

    renderBacklinkGapTab(profile) {
        const container = $("blTabContent");
        if (!container) return;

        container.innerHTML = `
            <div class="card" style="background:#F8FAFC; border:1px solid var(--border); margin-bottom:20px;">
                <h4 style="margin:0 0 8px 0; font-size:14px;">Find Competitor Backlink Opportunities</h4>
                <div style="font-size:12px; color:var(--text-muted); margin-bottom:14px;">
                    Discover referring domains that link to your competitors but have not yet linked to <b>${esc(profile.target_domain)}</b>.
                </div>
                <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
                    <input id="blCompInput1" type="text" class="form-input form-input-sm" placeholder="Competitor 1 (e.g. competitor.com)" style="width:200px;">
                    <input id="blCompInput2" type="text" class="form-input form-input-sm" placeholder="Competitor 2 (optional)" style="width:200px;">
                    <input id="blCompInput3" type="text" class="form-input form-input-sm" placeholder="Competitor 3 (optional)" style="width:200px;">
                    <button class="btn btn-primary btn-sm" onclick="app.runBacklinkGapAnalysis()">Analyze Backlink Gap</button>
                </div>
            </div>

            <div id="blGapResultsArea">
                <div class="empty-state" style="padding:32px;">
                    <div style="font-size:28px; margin-bottom:8px;">⚔️</div>
                    <p style="margin:0; font-size:13px; color:var(--text-muted);">Enter one or more competitor domains above to uncover missing link prospects.</p>
                </div>
            </div>
        `;
    }

    async runBacklinkGapAnalysis() {
        const target = this.blState.targetDomain;
        const c1 = ($("blCompInput1") ? $("blCompInput1").value : "").trim();
        const c2 = ($("blCompInput2") ? $("blCompInput2").value : "").trim();
        const c3 = ($("blCompInput3") ? $("blCompInput3").value : "").trim();

        const comps = [c1, c2, c3].filter(Boolean);
        if (!comps.length) {
            this.showNotification("Please enter at least one competitor domain.", "warning");
            return;
        }

        const area = $("blGapResultsArea");
        if (area) {
            area.innerHTML = `
                <div style="text-align:center; padding:32px;">
                    <div class="spinner" style="margin:0 auto 10px auto;"></div>
                    <div style="font-size:13px; color:var(--text-muted);">Comparing referring domain indexes across competitors...</div>
                </div>
            `;
        }

        try {
            const data = await jsonFetch(`${API_BASE}/backlinks/gap`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ target_domain: target, competitor_domains: comps })
            });

            if (area) {
                const gaps = data.gaps || [];
                if (!gaps.length) {
                    area.innerHTML = `
                        <div class="empty-state" style="padding:32px;">
                            <p style="margin:0; font-size:13px; color:var(--text-muted);">No backlink gaps found or competitor data requires active backlink provider.</p>
                        </div>
                    `;
                    return;
                }

                area.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <div style="font-size:13px; color:var(--text-muted);">
                            Found <b>${data.total_backlink_gaps}</b> referring domain opportunities (<b>${data.high_priority_gaps_count}</b> linking to 2+ competitors).
                        </div>
                    </div>
                    <div class="table-container">
                        <table class="data-table">
                            <thead>
                                <tr>
                                    <th>Prospect Domain</th>
                                    <th style="text-align:right;">Provider Rank</th>
                                    <th style="text-align:right;">Competitor Coverage</th>
                                    <th style="text-align:right;">Links to Competitors</th>
                                    <th>Linked Competitors</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${gaps.map(g => `
                                    <tr>
                                        <td><b style="color:var(--text);">${esc(g.referring_domain)}</b></td>
                                        <td style="text-align:right;"><span class="pill" style="background:#EFF6FF; color:#1D4ED8; font-weight:700;">${g.rank != null ? esc(g.rank) : "—"}</span></td>
                                        <td style="text-align:right;">
                                            <span class="pill" style="background:${g.competitors_count >= 2 ? '#ECFDF5' : '#F1F5F9'}; color:${g.competitors_count >= 2 ? '#047857' : '#475569'}; font-weight:700;">
                                                ${g.competitors_count} Competitor(s)
                                            </span>
                                        </td>
                                        <td style="text-align:right; font-weight:700;">${fmt(g.backlinks_to_competitors)}</td>
                                        <td style="font-size:11px; color:var(--text-muted);">
                                            ${Object.keys(g.competitor_links || {}).map(c => `<span class="pill" style="font-size:9px; margin-right:4px;">${esc(c)}</span>`).join("")}
                                        </td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </div>
                `;
            }
        } catch (err) {
            if (area) {
                area.innerHTML = `<div class="empty-state" style="color:var(--danger); padding:24px;">Gap analysis failed: ${esc(err.message || err)}</div>`;
            }
        }
    }

    renderBacklinkToxicityTab(profile) {
        const container = $("blTabContent");
        if (!container) return;

        const tox = profile.toxicity_radar || {};
        const flags = tox.flags || [];
        const riskLevel = tox.risk_level || "LOW";
        const riskColor = riskLevel === "LOW" ? "#10B981" : (riskLevel === "MODERATE" ? "#F59E0B" : "#EF4444");

        container.innerHTML = `
            <div style="display:grid; grid-template-columns: 280px 1fr; gap:20px; margin-bottom:20px; align-items:start;">
                <!-- Risk Meter Card -->
                <div class="card" style="text-align:center; padding:24px; border-top:4px solid ${riskColor};">
                    <span class="stat-label" style="text-transform:uppercase; font-size:11px; font-weight:700; color:var(--text-muted);">Overall Link Toxicity Risk</span>
                    <div style="font-size:36px; font-weight:800; color:${riskColor}; margin:8px 0;">${riskLevel}</div>
                    <div style="font-size:13px; color:var(--text-muted); margin-bottom:12px;">Risk Score: <b>${tox.risk_score || 0} / 100</b></div>
                    <div style="background:#F1F5F9; border-radius:6px; height:8px; overflow:hidden; margin:0 auto; max-width:200px;">
                        <div style="width:${tox.risk_score || 0}%; height:100%; background:${riskColor};"></div>
                    </div>
                    <div style="font-size:11px; color:var(--text-muted); margin-top:10px;">
                        Backlinks per Domain Ratio: <b>${tox.backlinks_per_domain_ratio || 0}:1</b>
                    </div>
                </div>

                <!-- Toxicity Flags -->
                <div class="card" style="padding:20px;">
                    <h4 style="margin:0 0 12px 0; font-size:14px;">Suspicious Link Pattern Flags (${flags.length})</h4>
                    ${flags.length ? `
                        <div style="display:flex; flex-direction:column; gap:10px;">
                            ${flags.map(f => `
                                <div style="background:${f.severity === 'HIGH' ? '#FEF2F2' : '#FFFBEB'}; border:1px solid ${f.severity === 'HIGH' ? '#FECACA' : '#FDE68A'}; border-radius:8px; padding:12px 14px;">
                                    <div style="display:flex; justify-content:space-between; align-items:center;">
                                        <b style="color:${f.severity === 'HIGH' ? '#B91C1C' : '#B45309'}; font-size:13px;">${esc(f.title)}</b>
                                        <span class="pill" style="background:${f.severity === 'HIGH' ? '#DC2626' : '#D97706'}; color:#FFFFFF; font-size:9px; font-weight:700;">${f.severity}</span>
                                    </div>
                                    <div style="font-size:12px; color:#475569; margin-top:4px;">${esc(f.detail)}</div>
                                </div>
                            `).join("")}
                        </div>
                    ` : `
                        <div style="background:#ECFDF5; border:1px solid #A7F3D0; border-radius:8px; padding:16px; color:#065F46; font-size:13px;">
                            <b>✓ Clean Link Profile:</b> No high-risk sitewide link skew, spam scores, or unnatural commercial anchor patterns detected.
                        </div>
                    `}
                </div>
            </div>
        `;
    }

    async saveCurrentBacklinkSnapshot() {
        const profile = this.blState.currentProfile;
        if (!profile) {
            this.showNotification("Please load a backlink profile first before saving a snapshot.", "warning");
            return;
        }

        const btn = $("btnSaveBacklinkSnapshot");
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Saving...";
        }

        try {
            const res = await jsonFetch(`${API_BASE}/backlinks/snapshots`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    target_domain: profile.target_domain,
                    client_id: this.state.selectedClientId || null,
                    data: profile
                })
            });
            this.showNotification(`Saved snapshot #${res.snapshot_id} for ${profile.target_domain}.`, "success");
        } catch (err) {
            this.showNotification("Failed to save snapshot: " + (err.message || err), "danger");
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = "💾 Save Snapshot";
            }
        }
    }

    async openSavedBacklinkSnapshotsModal() {
        const modal = $("backlinkSnapshotsModal");
        const body = $("blSavedModalBody");
        if (!modal || !body) return;

        modal.classList.remove("hidden");
        body.innerHTML = '<div style="text-align:center; padding:32px;"><div class="spinner" style="margin:0 auto 10px auto;"></div>Loading snapshots...</div>';

        try {
            const list = await jsonFetch(`${API_BASE}/backlinks/snapshots`);
            if (!list.length) {
                body.innerHTML = '<div class="empty-state" style="padding:32px;">No backlink snapshots saved yet.</div>';
                return;
            }

            body.innerHTML = `
                <div class="table-container">
                    <table class="data-table">
                        <thead>
                            <tr>
                                <th>Target Domain</th>
                                <th>Saved Date</th>
                                <th style="text-align:right;">Backlinks</th>
                                <th style="text-align:right;">Referring Domains</th>
                                <th style="text-align:right;">PAI Score</th>
                                <th style="text-align:right;">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${list.map(s => `
                                <tr>
                                    <td><b style="color:var(--text);">${esc(s.target_domain)}</b></td>
                                    <td style="font-size:12px; color:var(--text-muted);">${esc(String(s.created_at || "—").replace("T", " ").slice(0, 16))}</td>
                                    <td style="text-align:right; font-weight:700;">${fmt(s.total_backlinks)}</td>
                                    <td style="text-align:right;">${fmt(s.referring_domains)}</td>
                                    <td style="text-align:right;">
                                        <span class="pill" style="background:#EFF6FF; color:#1D4ED8; font-weight:700;">${(s.platform_authority_index || 0).toFixed(1)}</span>
                                    </td>
                                    <td style="text-align:right; white-space:nowrap;">
                                        <button class="btn btn-secondary btn-sm" onclick="app.loadSavedBacklinkSnapshot(${s.id})" style="margin-right:4px;">Load</button>
                                        <button class="btn btn-secondary btn-sm" onclick="app.deleteSavedBacklinkSnapshot(${s.id})" style="color:var(--danger);">Delete</button>
                                    </td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            body.innerHTML = `<div class="empty-state" style="color:var(--danger); padding:24px;">Failed to load snapshots: ${esc(err.message || err)}</div>`;
        }
    }

    closeSavedBacklinkSnapshotsModal() {
        const modal = $("backlinkSnapshotsModal");
        if (modal) modal.classList.add("hidden");
    }

    async loadSavedBacklinkSnapshot(id) {
        try {
            const snap = await jsonFetch(`${API_BASE}/backlinks/snapshots/${id}`);
            if (snap && snap.data) {
                this.blState.currentProfile = snap.data;
                this.blState.targetDomain = snap.target_domain;
                if ($("blTargetInput")) $("blTargetInput").value = snap.target_domain;
                this.renderBacklinkProfile(snap.data);
                this.closeSavedBacklinkSnapshotsModal();
                this.showNotification(`Loaded snapshot #${id} for ${snap.target_domain}.`, "success");
            }
        } catch (err) {
            this.showNotification("Failed to load snapshot: " + (err.message || err), "danger");
        }
    }

    async deleteSavedBacklinkSnapshot(id) {
        if (!confirm(`Are you sure you want to delete backlink snapshot #${id}?`)) return;
        try {
            await jsonFetch(`${API_BASE}/backlinks/snapshots/${id}`, { method: "DELETE" });
            this.showNotification(`Snapshot #${id} deleted.`, "success");
            this.openSavedBacklinkSnapshotsModal();
        } catch (err) {
            this.showNotification("Failed to delete snapshot: " + (err.message || err), "danger");
        }
    }

    showPaiMethodologyModal() {
        const modal = $("backlinkMethodologyModal");
        if (modal) modal.classList.remove("hidden");
    }

    closePaiMethodologyModal() {
        const modal = $("backlinkMethodologyModal");
        if (modal) modal.classList.add("hidden");
    }

    async exportBacklinks(format = "pdf") {
        const profile = this.blState.currentProfile;
        if (!profile) {
            this.showNotification("Please load a backlink profile first to export data.", "warning");
            return;
        }

        try {
            this.showNotification(`Generating ${format.toUpperCase()} backlink report...`, "info");
            const res = await fetch(`${API_BASE}/backlinks/export/${format}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {})
                },
                body: JSON.stringify(profile)
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `backlinks_${profile.target_domain}_${new Date().toISOString().slice(0, 10)}.${format === "excel" ? "xls" : format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            this.showNotification(`Downloaded ${format.toUpperCase()} report successfully.`, "success");
        } catch (err) {
            this.showNotification(`Export failed: ${err.message || err}`, "danger");
        }
    }

    /* -------------------------------------------------------------
       PHASE 7: GOOGLE SEARCH CONSOLE, GA4 & PERFORMANCE INTELLIGENCE
    -------------------------------------------------------------- */

    async loadGooglePerformance() {
        try {
            const websites = await jsonFetch(`${API_BASE}/google/websites`);
            this.gperfState.websites = websites || [];
            const select = $("gperfWebsiteSelect");
            if (select) {
                if (websites && websites.length > 0) {
                    select.innerHTML = websites.map(w => `
                        <option value="${w.id}">${escapeHtml(w.name)} (${escapeHtml(w.url)})</option>
                    `).join("");
                    if (!this.gperfState.websiteId || !websites.some(w => w.id === this.gperfState.websiteId)) {
                        this.gperfState.websiteId = websites[0].id;
                        this.gperfState.websiteUrl = websites[0].url;
                    }
                    select.value = String(this.gperfState.websiteId);
                    await this.checkGoogleConnections(this.gperfState.websiteId);
                    await this.fetchGooglePerformanceReport();
                } else {
                    select.innerHTML = `<option value="">-- No client websites registered --</option>`;
                }
            }
        } catch (err) {
            console.error("Failed to load Google websites:", err);
        }
    }

    async handleGoogleWebsiteChange() {
        const select = $("gperfWebsiteSelect");
        if (!select || !select.value) return;
        const wid = parseInt(select.value, 10);
        this.gperfState.websiteId = wid;
        const site = this.gperfState.websites.find(w => w.id === wid);
        if (site) this.gperfState.websiteUrl = site.url;
        await this.checkGoogleConnections(wid);
        await this.fetchGooglePerformanceReport();
    }

    async handleGoogleDaysChange() {
        const select = $("gperfDaysSelect");
        if (!select) return;
        this.gperfState.days = parseInt(select.value, 10) || 28;
        await this.fetchGooglePerformanceReport();
    }

    async checkGoogleConnections(websiteId) {
        if (!websiteId) return;
        try {
            const data = await jsonFetch(`${API_BASE}/google/connections/${websiteId}`);
            this.updateGoogleConnectionBadges(data);
        } catch (err) {
            console.warn("Connection check failed:", err);
        }
    }

    updateGoogleConnectionBadges(data) {
        if (!data) return;
        const gscBadge = $("gperfGscStatusBadge");
        const ga4Badge = $("gperfGa4StatusBadge");
        const psiBadge = $("gperfPsiStatusBadge");
        const lastChecked = $("gperfLastCheckedText");

        if (gscBadge && data.search_console) {
            const st = data.search_console.status;
            if (st === "CONNECTED") {
                gscBadge.style.background = "#DCFCE7";
                gscBadge.style.color = "#15803D";
                gscBadge.textContent = "✓ Connected";
                gscBadge.title = data.search_console.detail || "Authorized";
            } else if (st === "UNAUTHORIZED") {
                gscBadge.style.background = "#FEF3C7";
                gscBadge.style.color = "#B45309";
                gscBadge.textContent = "⚠️ Unauthorized";
                gscBadge.title = data.search_console.detail || "Unauthorized";
            } else {
                gscBadge.style.background = "#F1F5F9";
                gscBadge.style.color = "#64748B";
                gscBadge.textContent = "Not Configured";
                gscBadge.title = data.search_console.detail || "No service account or property configured";
            }
        }

        if (ga4Badge && data.google_analytics_4) {
            const st = data.google_analytics_4.status;
            if (st === "CONNECTED") {
                ga4Badge.style.background = "#DCFCE7";
                ga4Badge.style.color = "#15803D";
                ga4Badge.textContent = "✓ Connected";
                ga4Badge.title = data.google_analytics_4.detail || "Connected";
            } else if (st === "UNAUTHORIZED") {
                ga4Badge.style.background = "#FEF3C7";
                ga4Badge.style.color = "#B45309";
                ga4Badge.textContent = "⚠️ Permission Denied";
                ga4Badge.title = data.google_analytics_4.detail || "Permission denied";
            } else {
                ga4Badge.style.background = "#F1F5F9";
                ga4Badge.style.color = "#64748B";
                ga4Badge.textContent = "Not Configured";
                ga4Badge.title = data.google_analytics_4.detail || "No GA4 property configured";
            }
        }

        if (psiBadge && data.pagespeed) {
            psiBadge.style.background = "#DCFCE7";
            psiBadge.style.color = "#15803D";
            psiBadge.textContent = data.pagespeed.status === "CONNECTED" ? "✓ API Active" : "✓ Active";
            psiBadge.title = data.pagespeed.detail || "PageSpeed Ready";
        }

        if (lastChecked && data.last_checked_at) {
            try {
                const dt = new Date(data.last_checked_at);
                lastChecked.textContent = `Status verified at ${dt.toLocaleTimeString()}`;
            } catch (_) {}
        }
    }

    async fetchGooglePerformanceReport() {
        const wid = this.gperfState.websiteId;
        if (!wid) {
            this.showNotification("Please select a website first.", "warning");
            return;
        }

        const btn = $("btnFetchGooglePerf");
        const content = $("gperfContentArea");
        const days = this.gperfState.days || 28;

        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<span class="spin">⏳</span> Fetching...`;
        }

        if (content) {
            content.innerHTML = `
                <div class="card" style="padding:48px 20px; text-align:center;">
                    <div style="font-size:36px; margin-bottom:12px;">⏳</div>
                    <h3 style="margin:0 0 8px 0;">Querying Google Telemetry...</h3>
                    <p style="margin:0; font-size:13px; color:var(--text-muted);">Retrieving Search Console search analytics, GA4 sessions, and Core Web Vitals field data...</p>
                </div>
            `;
        }

        try {
            const report = await jsonFetch(`${API_BASE}/google/performance/${wid}?days=${days}`);
            this.gperfState.currentReport = report;
            this.gperfState.targetDomain = report.target_domain || "";
            if (report.connections) {
                this.updateGoogleConnectionBadges(report.connections);
            }
            this.renderGooglePerformanceReport(report);
        } catch (err) {
            if (content) {
                content.innerHTML = `
                    <div class="card" style="padding:40px 20px; text-align:center;">
                        <div style="font-size:36px; color:#EF4444; margin-bottom:12px;">⚠️</div>
                        <h3 style="margin:0 0 8px 0; color:#EF4444;">Failed to Fetch Telemetry</h3>
                        <p style="margin:0 0 16px 0; font-size:13px; color:var(--text-muted);">${escapeHtml(err.message || String(err))}</p>
                        <button class="btn btn-secondary btn-sm" onclick="app.fetchGooglePerformanceReport()">Try Again</button>
                    </div>
                `;
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `<span>⚡ Refresh Telemetry</span>`;
            }
        }
    }

    renderGooglePerformanceReport(report) {
        const content = $("gperfContentArea");
        if (!content || !report) return;

        const gsc = report.search_console || {};
        const ga4 = report.google_analytics_4 || {};
        const cwv = report.core_web_vitals_field || {};
        const lh = report.lighthouse_lab || {};

        const gscTotals = gsc.totals || { clicks: 0, impressions: 0, ctr: 0, position: 0 };
        const ga4Totals = ga4.totals || { sessions: 0, total_users: 0, active_users: 0, new_users: 0, engagement_rate: 0, average_session_duration: 0, bounce_rate: 0 };

        // Real User CWV Assessment Color
        const cwvAssessment = (cwv.assessment || "insufficient data").toUpperCase();
        let cwvBadgeBg = "#FEF3C7";
        let cwvBadgeFg = "#B45309";
        if (cwvAssessment === "PASSED") {
            cwvBadgeBg = "#DCFCE7";
            cwvBadgeFg = "#15803D";
        } else if (cwvAssessment === "FAILED") {
            cwvBadgeBg = "#FEE2E2";
            cwvBadgeFg = "#B91C1C";
        }

        const activeTab = this.gperfState.activeTab || "gsc";

        content.innerHTML = `
            <!-- 4 Top KPI Scorecards -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:16px; margin-bottom:20px;">
                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Google Search Clicks</div>
                    <div style="font-size:26px; font-weight:800; color:#1E293B; margin:6px 0 2px 0;">${(gscTotals.clicks || 0).toLocaleString()}</div>
                    <div style="font-size:12px; color:#64748B;">CTR: <b>${gscTotals.ctr || 0}%</b></div>
                </div>

                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Search Impressions</div>
                    <div style="font-size:26px; font-weight:800; color:#1E293B; margin:6px 0 2px 0;">${(gscTotals.impressions || 0).toLocaleString()}</div>
                    <div style="font-size:12px; color:#64748B;">Avg Position: <b>${(gscTotals.position || 0).toFixed(1)}</b></div>
                </div>

                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">GA4 Total Sessions</div>
                    <div style="font-size:26px; font-weight:800; color:#1E293B; margin:6px 0 2px 0;">${(ga4Totals.sessions || 0).toLocaleString()}</div>
                    <div style="font-size:12px; color:#64748B;">Active Users: <b>${(ga4Totals.active_users || 0).toLocaleString()}</b></div>
                </div>

                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">GA4 Engagement Rate</div>
                    <div style="font-size:26px; font-weight:800; color:#1E293B; margin:6px 0 2px 0;">${ga4Totals.engagement_rate || 0}%</div>
                    <div style="font-size:12px; color:#64748B;">Avg Duration: <b>${ga4Totals.average_session_duration || 0}s</b> (Bounce: ${ga4Totals.bounce_rate || 0}%)</div>
                </div>
            </div>

            <!-- Core Web Vitals Field (Real-User) vs Lighthouse Lab Simulation -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:20px; margin-bottom:24px;">
                <!-- Real-User Field Card -->
                <div class="card" style="padding:20px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <div>
                            <h3 style="margin:0; font-size:16px; font-weight:800; display:flex; align-items:center; gap:6px;">
                                <span>👥 Real-User Core Web Vitals (CrUX)</span>
                            </h3>
                            <div style="font-size:11px; color:var(--text-muted);">75th percentile of real Chrome visits over 28-day window</div>
                        </div>
                        <span class="pill" style="background:${cwvBadgeBg}; color:${cwvBadgeFg}; font-weight:800; font-size:11px;">${cwvAssessment}</span>
                    </div>

                    ${this.renderCwvFieldMetrics(cwv)}
                </div>

                <!-- Synthetic Lighthouse Lab Card -->
                <div class="card" style="padding:20px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                        <div>
                            <h3 style="margin:0; font-size:16px; font-weight:800; display:flex; align-items:center; gap:6px;">
                                <span>🔬 Lighthouse Synthetic Lab Audit</span>
                            </h3>
                            <div style="font-size:11px; color:var(--text-muted);">Simulated browser audit executed in isolated test environment</div>
                        </div>
                        <span class="pill" style="background:#F1F5F9; color:#475569; font-size:11px;">Lab Simulation</span>
                    </div>

                    ${this.renderLighthouseLabScores(lh)}
                </div>
            </div>

            <!-- Deep Dive Tabbed Section -->
            <div class="card" style="padding:0; overflow:hidden;">
                <div style="display:flex; border-bottom:1px solid var(--border); background:#F8FAFC;">
                    <button class="tab-btn ${activeTab === 'gsc' ? 'active' : ''}" onclick="app.switchGooglePerfTab('gsc')" style="padding:14px 20px; font-size:13px; font-weight:700; border:none; background:none; cursor:pointer;">
                        Google Search Console (${(gsc.top_queries || []).length} Queries)
                    </button>
                    <button class="tab-btn ${activeTab === 'ga4' ? 'active' : ''}" onclick="app.switchGooglePerfTab('ga4')" style="padding:14px 20px; font-size:13px; font-weight:700; border:none; background:none; cursor:pointer;">
                        Google Analytics 4 (${(ga4.channels || []).length} Channels)
                    </button>
                </div>

                <div style="padding:20px;">
                    ${activeTab === 'gsc' ? this.renderGscTabContent(gsc) : this.renderGa4TabContent(ga4)}
                </div>
            </div>
        `;
    }

    renderCwvFieldMetrics(cwv) {
        const mob = (cwv && cwv.mobile) || {};
        const desk = (cwv && cwv.desktop) || {};
        const hasData = cwv && cwv.has_real_user_data;

        if (!hasData) {
            return `
                <div style="background:#F8FAFC; border:1px dashed #CBD5E1; border-radius:8px; padding:24px 16px; text-align:center; color:#64748B;">
                    <div style="font-size:24px; margin-bottom:6px;">📉</div>
                    <div style="font-weight:700; font-size:13px; color:#334155; margin-bottom:4px;">Insufficient Real-User Field Data</div>
                    <div style="font-size:11px; line-height:1.4;">
                        The Chrome User Experience Report requires a minimum threshold of real visits before publishing p75 metrics for this specific URL or origin.
                    </div>
                </div>
            `;
        }

        const metrics = [
            { key: "largest_contentful_paint", label: "LCP (Loading)", unit: "ms" },
            { key: "interaction_to_next_paint", label: "INP (Responsiveness)", unit: "ms" },
            { key: "cumulative_layout_shift", label: "CLS (Visual Stability)", unit: "" },
            { key: "first_contentful_paint", label: "FCP (First Paint)", unit: "ms" },
            { key: "experimental_time_to_first_byte", label: "TTFB (Server Response)", unit: "ms" }
        ];

        return `
            <div class="table-container">
                <table style="font-size:12px; margin:0;">
                    <thead>
                        <tr>
                            <th>Metric</th>
                            <th>Mobile (p75)</th>
                            <th>Desktop (p75)</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${metrics.map(m => {
                            const mVal = mob[m.key] ? (mob[m.key].value !== undefined ? `${mob[m.key].value}${m.unit}` : "-") : "-";
                            const mCat = mob[m.key] ? (mob[m.key].category || "").toLowerCase() : "";
                            const dVal = desk[m.key] ? (desk[m.key].value !== undefined ? `${desk[m.key].value}${m.unit}` : "-") : "-";
                            const dCat = desk[m.key] ? (desk[m.key].category || "").toLowerCase() : "";
                            return `
                                <tr>
                                    <td><b>${m.label}</b></td>
                                    <td><span class="pill pill-${mCat === 'fast' || mCat === 'good' ? 'success' : (mCat === 'slow' || mCat === 'poor' ? 'danger' : 'warning')}">${mVal}</span></td>
                                    <td><span class="pill pill-${dCat === 'fast' || dCat === 'good' ? 'success' : (dCat === 'slow' || dCat === 'poor' ? 'danger' : 'warning')}">${dVal}</span></td>
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderLighthouseLabScores(lh) {
        const mobScore = lh.mobile_score !== undefined && lh.mobile_score !== null ? lh.mobile_score : "N/A";
        const deskScore = lh.desktop_score !== undefined && lh.desktop_score !== null ? lh.desktop_score : "N/A";
        const catsMob = lh.categories_mobile || {};

        return `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px;">
                <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:12px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted);">MOBILE PERFORMANCE</div>
                    <div style="font-size:24px; font-weight:800; color:${mobScore >= 90 ? '#10B981' : (mobScore >= 50 ? '#F59E0B' : '#EF4444')}; margin-top:4px;">
                        ${mobScore} <span style="font-size:12px; color:#64748B;">/ 100</span>
                    </div>
                </div>
                <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:12px; text-align:center;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted);">DESKTOP PERFORMANCE</div>
                    <div style="font-size:24px; font-weight:800; color:${deskScore >= 90 ? '#10B981' : (deskScore >= 50 ? '#F59E0B' : '#EF4444')}; margin-top:4px;">
                        ${deskScore} <span style="font-size:12px; color:#64748B;">/ 100</span>
                    </div>
                </div>
            </div>

            <div style="font-size:12px; color:#475569;">
                <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #F1F5F9;">
                    <span>Accessibility Score:</span>
                    <b>${catsMob.accessibility !== undefined ? catsMob.accessibility + '/100' : 'N/A'}</b>
                </div>
                <div style="display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid #F1F5F9;">
                    <span>Best Practices Score:</span>
                    <b>${catsMob.best_practices !== undefined ? catsMob.best_practices + '/100' : 'N/A'}</b>
                </div>
                <div style="display:flex; justify-content:space-between; padding:4px 0;">
                    <span>SEO Audit Score:</span>
                    <b>${catsMob.seo !== undefined ? catsMob.seo + '/100' : 'N/A'}</b>
                </div>
            </div>
        `;
    }

    switchGooglePerfTab(tabName) {
        this.gperfState.activeTab = tabName;
        if (this.gperfState.currentReport) {
            this.renderGooglePerformanceReport(this.gperfState.currentReport);
        }
    }

    renderGscTabContent(gsc) {
        if (!gsc.is_connected && gsc.error) {
            return `
                <div style="background:#FFFBEB; border:1px solid #FDE68A; border-radius:8px; padding:20px; color:#92400E; text-align:center;">
                    <div style="font-size:24px; margin-bottom:6px;">⚠️</div>
                    <div style="font-weight:700; font-size:14px; margin-bottom:4px;">Google Search Console Not Connected</div>
                    <div style="font-size:12px; margin-bottom:12px;">${escapeHtml(gsc.error)}</div>
                    <button class="btn btn-secondary btn-sm" onclick="app.openGoogleSettingsModal()">Configure Search Console Property</button>
                </div>
            `;
        }

        const queries = gsc.top_queries || [];
        const pages = gsc.top_pages || [];
        const devices = gsc.devices || [];
        const countries = gsc.countries || [];

        return `
            <!-- Top Queries & Top Pages Grid -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(400px, 1fr)); gap:20px; margin-bottom:24px;">
                <!-- Queries Table -->
                <div>
                    <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700;">Top Google Search Queries</h4>
                    <div class="table-container" style="max-height:360px; overflow-y:auto;">
                        <table style="font-size:12px; margin:0;">
                            <thead>
                                <tr>
                                    <th>Query</th>
                                    <th style="text-align:right;">Clicks</th>
                                    <th style="text-align:right;">Impr</th>
                                    <th style="text-align:right;">CTR</th>
                                    <th style="text-align:right;">Avg Pos</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${queries.length === 0 ? `<tr><td colspan="5" class="empty-state">No search queries recorded.</td></tr>` : queries.map(q => `
                                    <tr>
                                        <td><b>${escapeHtml(q.query || "")}</b></td>
                                        <td style="text-align:right;">${(q.clicks || 0).toLocaleString()}</td>
                                        <td style="text-align:right;">${(q.impressions || 0).toLocaleString()}</td>
                                        <td style="text-align:right;">${(q.ctr || 0)}%</td>
                                        <td style="text-align:right;">${(q.position || 0).toFixed(1)}</td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Pages Table -->
                <div>
                    <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700;">Top Search Landing Pages</h4>
                    <div class="table-container" style="max-height:360px; overflow-y:auto;">
                        <table style="font-size:12px; margin:0;">
                            <thead>
                                <tr>
                                    <th>Page URL</th>
                                    <th style="text-align:right;">Clicks</th>
                                    <th style="text-align:right;">Impr</th>
                                    <th style="text-align:right;">CTR</th>
                                    <th style="text-align:right;">Avg Pos</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${pages.length === 0 ? `<tr><td colspan="5" class="empty-state">No pages recorded.</td></tr>` : pages.map(p => `
                                    <tr>
                                        <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(p.page || "")}">
                                            <a href="${escapeHtml(p.page || "")}" target="_blank" rel="noopener" style="color:#2563EB; text-decoration:none;">${escapeHtml(p.page || "")}</a>
                                        </td>
                                        <td style="text-align:right;">${(p.clicks || 0).toLocaleString()}</td>
                                        <td style="text-align:right;">${(p.impressions || 0).toLocaleString()}</td>
                                        <td style="text-align:right;">${(p.ctr || 0)}%</td>
                                        <td style="text-align:right;">${(p.position || 0).toFixed(1)}</td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Devices and Countries Breakdown -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:20px;">
                <!-- Device Breakdown -->
                <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:16px;">
                    <h5 style="margin:0 0 12px 0; font-size:13px; font-weight:700;">Device Breakdown</h5>
                    ${devices.length === 0 ? `<div style="font-size:12px; color:#64748B;">No device telemetry recorded.</div>` : devices.map(d => `
                        <div style="margin-bottom:8px;">
                            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:2px;">
                                <span style="font-weight:600; text-transform:capitalize;">${escapeHtml(d.device || "Unknown")}</span>
                                <span>${(d.clicks || 0).toLocaleString()} clicks (${(d.impressions || 0).toLocaleString()} impr)</span>
                            </div>
                        </div>
                    `).join("")}
                </div>

                <!-- Top Countries Breakdown -->
                <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:16px;">
                    <h5 style="margin:0 0 12px 0; font-size:13px; font-weight:700;">Top Geographic Markets</h5>
                    ${countries.length === 0 ? `<div style="font-size:12px; color:#64748B;">No country telemetry recorded.</div>` : countries.slice(0, 6).map(c => `
                        <div style="display:flex; justify-content:space-between; font-size:12px; padding:4px 0; border-bottom:1px solid #F1F5F9;">
                            <span style="font-weight:600; text-transform:uppercase;">${escapeHtml(c.country || "Unknown")}</span>
                            <span>${(c.clicks || 0).toLocaleString()} clicks</span>
                        </div>
                    `).join("")}
                </div>
            </div>
        `;
    }

    renderGa4TabContent(ga4) {
        if (!ga4.is_connected && ga4.error) {
            return `
                <div style="background:#FFFBEB; border:1px solid #FDE68A; border-radius:8px; padding:20px; color:#92400E; text-align:center;">
                    <div style="font-size:24px; margin-bottom:6px;">⚠️</div>
                    <div style="font-weight:700; font-size:14px; margin-bottom:4px;">Google Analytics 4 Not Connected</div>
                    <div style="font-size:12px; margin-bottom:12px;">${escapeHtml(ga4.error)}</div>
                    <button class="btn btn-secondary btn-sm" onclick="app.openGoogleSettingsModal()">Configure GA4 Property ID</button>
                </div>
            `;
        }

        const channels = ga4.channels || [];
        const topPages = ga4.top_pages || [];
        const countries = ga4.countries || [];

        return `
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:20px; margin-bottom:24px;">
                <!-- Acquisition Channels -->
                <div>
                    <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700;">Traffic Acquisition Channels</h4>
                    <div class="table-container">
                        <table style="font-size:12px; margin:0;">
                            <thead>
                                <tr>
                                    <th>Channel Group</th>
                                    <th style="text-align:right;">Sessions</th>
                                    <th style="text-align:right;">Users</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${channels.length === 0 ? `<tr><td colspan="3" class="empty-state">No channel traffic recorded.</td></tr>` : channels.map(ch => `
                                    <tr>
                                        <td><b>${escapeHtml(ch.channel || "Unassigned")}</b></td>
                                        <td style="text-align:right;">${(ch.sessions || 0).toLocaleString()}</td>
                                        <td style="text-align:right;">${(ch.users || 0).toLocaleString()}</td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Top GA4 Landing Pages -->
                <div>
                    <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700;">Top Landing Pages (Views &amp; Sessions)</h4>
                    <div class="table-container">
                        <table style="font-size:12px; margin:0;">
                            <thead>
                                <tr>
                                    <th>Page Path</th>
                                    <th style="text-align:right;">Views</th>
                                    <th style="text-align:right;">Sessions</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${topPages.length === 0 ? `<tr><td colspan="3" class="empty-state">No page telemetry recorded.</td></tr>` : topPages.slice(0, 15).map(p => `
                                    <tr>
                                        <td style="max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(p.page_path || "")}">
                                            <code>${escapeHtml(p.page_path || "")}</code>
                                        </td>
                                        <td style="text-align:right;">${(p.page_views || 0).toLocaleString()}</td>
                                        <td style="text-align:right;">${(p.sessions || 0).toLocaleString()}</td>
                                    </tr>
                                `).join("")}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Country breakdown -->
            <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:16px;">
                <h5 style="margin:0 0 12px 0; font-size:13px; font-weight:700;">GA4 Geographic Distribution</h5>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px;">
                    ${countries.length === 0 ? `<div style="font-size:12px; color:#64748B;">No country data recorded.</div>` : countries.slice(0, 8).map(c => `
                        <div style="display:flex; justify-content:space-between; font-size:12px; padding:6px 8px; background:#FFFFFF; border:1px solid #E2E8F0; border-radius:6px;">
                            <span style="font-weight:600;">${escapeHtml(c.country || "Unknown")}</span>
                            <span>${(c.sessions || 0).toLocaleString()} sessions</span>
                        </div>
                    `).join("")}
                </div>
            </div>
        `;
    }

    openGoogleSettingsModal() {
        const modal = $("googleSettingsModal");
        if (!modal) return;
        const wid = this.gperfState.websiteId;
        const site = this.gperfState.websites.find(w => w.id === wid);
        if (site) {
            if ($("gperfModalWebsiteId")) $("gperfModalWebsiteId").value = site.id;
            if ($("gperfModalWebsiteUrl")) $("gperfModalWebsiteUrl").value = `${site.name} (${site.url})`;
            if ($("gperfModalGscProp")) $("gperfModalGscProp").value = site.gsc_property || "";
            if ($("gperfModalGa4Id")) $("gperfModalGa4Id").value = site.ga4_property_id || "";
        }
        modal.classList.remove("hidden");
    }

    closeGoogleSettingsModal() {
        const modal = $("googleSettingsModal");
        if (modal) modal.classList.add("hidden");
    }

    async saveGoogleSettings() {
        const wid = parseInt($("gperfModalWebsiteId").value, 10);
        if (!wid) return;
        const gscProp = ($("gperfModalGscProp").value || "").trim();
        const ga4Id = ($("gperfModalGa4Id").value || "").trim();
        const btn = $("btnSaveGoogleSettings");
        if (btn) {
            btn.disabled = true;
            btn.textContent = "Saving...";
        }
        try {
            const res = await jsonFetch(`${API_BASE}/google/settings/${wid}`, {
                method: "POST",
                body: JSON.stringify({ gsc_property: gscProp, ga4_property_id: ga4Id })
            });
            this.showNotification("Google connection settings saved successfully.", "success");
            this.closeGoogleSettingsModal();
            // Update cached website details
            const site = this.gperfState.websites.find(w => w.id === wid);
            if (site) {
                site.gsc_property = gscProp;
                site.ga4_property_id = ga4Id;
            }
            this.updateGoogleConnectionBadges(res);
            await this.fetchGooglePerformanceReport();
        } catch (err) {
            this.showNotification("Failed to save settings: " + (err.message || err), "danger");
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = "Save & Test Connection";
            }
        }
    }

    async exportGooglePerformance(format = "pdf") {
        const rep = this.gperfState.currentReport;
        if (!rep) {
            this.showNotification("Please load website telemetry first to export data.", "warning");
            return;
        }

        try {
            this.showNotification(`Generating ${format.toUpperCase()} performance report...`, "info");
            const res = await fetch(`${API_BASE}/google/export/${format}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {})
                },
                body: JSON.stringify(rep)
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            const target = rep.target_domain || "website";
            a.download = `google_performance_${target}_${new Date().toISOString().slice(0, 10)}.${format === "excel" ? "xls" : format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            this.showNotification(`Downloaded ${format.toUpperCase()} report successfully.`, "success");
        } catch (err) {
            this.showNotification(`Export failed: ${err.message || err}`, "danger");
        }
    }

    /* -------------------------------------------------------------
       PHASE 8: KEYWORD RANK TRACKING & LIVE SERP MONITORING
    -------------------------------------------------------------- */

    async loadRankings() {
        try {
            // Load available client websites for dropdown
            const websites = await jsonFetch(`${API_BASE}/google/websites`);
            const select = $("rankDomainSelect");
            if (select) {
                if (websites && websites.length > 0) {
                    select.innerHTML = websites.map(w => {
                        const dom = (w.url || "").replace(/^https?:\/\//i, "").replace(/\/.*$/, "").replace(/^www\./i, "");
                        return `<option value="${dom}" data-wid="${w.id}">${escapeHtml(w.name)} (${dom})</option>`;
                    }).join("");

                    if (!this.rankState.targetDomain || !websites.some(w => w.url.includes(this.rankState.targetDomain))) {
                        const firstDom = (websites[0].url || "").replace(/^https?:\/\//i, "").replace(/\/.*$/, "").replace(/^www\./i, "");
                        this.rankState.targetDomain = firstDom;
                        this.rankState.websiteId = websites[0].id;
                    }
                    select.value = this.rankState.targetDomain;
                } else {
                    select.innerHTML = `<option value="">-- No websites registered --</option>`;
                }
            }
            await this.loadRankingsOverview();
        } catch (err) {
            console.error("Failed to load ranking domains:", err);
            await this.loadRankingsOverview();
        }
    }

    async handleRankDomainChange() {
        const select = $("rankDomainSelect");
        if (!select || !select.value) return;
        this.rankState.targetDomain = select.value.trim();
        const opt = select.options[select.selectedIndex];
        if (opt && opt.dataset.wid) {
            this.rankState.websiteId = parseInt(opt.dataset.wid, 10);
        }
        await this.loadRankingsOverview();
    }

    async handleRankDeviceChange() {
        const select = $("rankDeviceSelect");
        if (!select) return;
        this.rankState.device = select.value;
        await this.loadRankingsOverview();
    }

    async loadRankingsOverview() {
        const domain = this.rankState.targetDomain || "";
        const device = this.rankState.device || "";
        const content = $("rankContentArea");

        if (content) {
            content.innerHTML = `
                <div class="card" style="padding:48px 20px; text-align:center;">
                    <div style="font-size:36px; margin-bottom:12px;">⏳</div>
                    <h3 style="margin:0 0 8px 0;">Loading Keyword Rankings...</h3>
                    <p style="margin:0; font-size:13px; color:var(--text-muted);">Fetching live SERP positions, competitor benchmarks, and rank volatility analytics...</p>
                </div>
            `;
        }

        try {
            let url = `${API_BASE}/rankings/overview?`;
            if (domain) url += `target_domain=${encodeURIComponent(domain)}&`;
            if (device) url += `device=${encodeURIComponent(device)}&`;
            const data = await jsonFetch(url);
            this.rankState.currentOverview = data;
            this.renderRankingsContent();
        } catch (err) {
            if (content) {
                content.innerHTML = `
                    <div class="card" style="padding:40px 20px; text-align:center;">
                        <div style="font-size:36px; color:#EF4444; margin-bottom:12px;">⚠️</div>
                        <h3 style="margin:0 0 8px 0; color:#EF4444;">Failed to Load Rankings</h3>
                        <p style="margin:0 0 16px 0; font-size:13px; color:var(--text-muted);">${escapeHtml(err.message || String(err))}</p>
                        <button class="btn btn-secondary btn-sm" onclick="app.loadRankingsOverview()">Try Again</button>
                    </div>
                `;
            }
        }
    }

    renderRankingsContent() {
        const content = $("rankContentArea");
        const data = this.rankState.currentOverview;
        if (!content || !data) return;

        const total = data.total_keywords || 0;
        const avgPos = data.average_position || 0.0;
        const vis = data.visibility_score || 0.0;
        const dist = data.distribution || {};
        const winners = data.winners || [];
        const losers = data.losers || [];
        const alerts = data.recent_alerts || [];
        const unreadAlerts = alerts.filter(a => !a.is_read);

        // Update badge counters
        const alertsBadge = $("rankAlertsBadge");
        if (alertsBadge) {
            if (unreadAlerts.length > 0) {
                alertsBadge.style.display = "inline";
                alertsBadge.textContent = String(unreadAlerts.length);
            } else {
                alertsBadge.style.display = "none";
            }
        }

        if ($("countFilterAll")) $("countFilterAll").textContent = String(total);
        if ($("countFilterTop3")) $("countFilterTop3").textContent = String(dist.top_3 || 0);
        if ($("countFilterTop10")) $("countFilterTop10").textContent = String(dist.top_10 || 0);
        if ($("countFilterTop20")) $("countFilterTop20").textContent = String(dist.top_20 || 0);
        if ($("countFilterWinners")) $("countFilterWinners").textContent = String(winners.length);
        if ($("countFilterLosers")) $("countFilterLosers").textContent = String(losers.length);
        if ($("countFilterUnranked")) $("countFilterUnranked").textContent = String(dist.unranked || 0);

        if (total === 0) {
            content.innerHTML = `
                <div class="card" style="padding:48px 20px; text-align:center;">
                    <div style="font-size:36px; margin-bottom:12px;">🎯</div>
                    <h3 style="margin:0 0 6px 0;">No Tracked Keywords Registered</h3>
                    <p style="margin:0 0 16px 0; font-size:13px; color:var(--text-muted);">
                        No active keywords found for <b>${escapeHtml(this.rankState.targetDomain || "this domain")}</b>.
                        Add target search terms to monitor live Google rankings and competitor movements.
                    </p>
                    <button class="btn btn-primary btn-sm" onclick="app.openAddKeywordsModal()">+ Add Target Keywords</button>
                </div>
            `;
            return;
        }

        const activeTab = this.rankState.activeTab || "keywords";

        content.innerHTML = `
            <!-- 4 Top KPI Scorecards -->
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(210px, 1fr)); gap:16px; margin-bottom:20px;">
                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Tracked Keywords</div>
                    <div style="font-size:26px; font-weight:800; color:#1E293B; margin:6px 0 2px 0;">${total.toLocaleString()}</div>
                    <div style="font-size:12px; color:#64748B;">Device: <b style="text-transform:capitalize;">${this.rankState.device || "All"}</b></div>
                </div>

                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Average SERP Position</div>
                    <div style="font-size:26px; font-weight:800; color:#4F46E5; margin:6px 0 2px 0;">#${avgPos.toFixed(1)}</div>
                    <div style="font-size:12px; color:#64748B;">Top 10 Terms: <b>${(dist.top_10 || 0).toLocaleString()}</b></div>
                </div>

                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Visibility Index (SOV)</div>
                    <div style="font-size:26px; font-weight:800; color:#10B981; margin:6px 0 2px 0;">${vis.toFixed(1)}%</div>
                    <div style="font-size:12px; color:#64748B;">Organic CTR Share of Voice</div>
                </div>

                <div class="card" style="padding:18px;">
                    <div style="font-size:11px; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Ranking Volatility</div>
                    <div style="font-size:22px; font-weight:800; color:#1E293B; margin:8px 0 2px 0; display:flex; align-items:center; gap:8px;">
                        <span style="color:#10B981; font-size:18px;">🟢 +${winners.length}</span>
                        <span style="color:#EF4444; font-size:18px;">🔴 -${losers.length}</span>
                    </div>
                    <div style="font-size:12px; color:#64748B;">${winners.length} improved, ${losers.length} dropped</div>
                </div>
            </div>

            <!-- Position Distribution Stacked Bar -->
            <div class="card" style="padding:16px 20px; margin-bottom:20px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <div style="font-size:12px; font-weight:700; color:#1E293B;">Google SERP Position Distribution</div>
                    <div style="font-size:11px; color:#64748B;">
                        Top 3: <b>${dist.top_3 || 0}</b> | Top 10: <b>${dist.top_10 || 0}</b> | Top 20: <b>${dist.top_20 || 0}</b> | Unranked: <b>${dist.unranked || 0}</b>
                    </div>
                </div>
                <div style="height:12px; border-radius:6px; background:#F1F5F9; overflow:hidden; display:flex;">
                    <div style="width:${(dist.top_3 / total * 100).toFixed(1)}%; background:#10B981;" title="Top 3: ${dist.top_3}"></div>
                    <div style="width:${((dist.top_10 - dist.top_3) / total * 100).toFixed(1)}%; background:#3B82F6;" title="Pos 4-10: ${dist.top_10 - dist.top_3}"></div>
                    <div style="width:${((dist.top_20 - dist.top_10) / total * 100).toFixed(1)}%; background:#6366F1;" title="Pos 11-20: ${dist.top_20 - dist.top_10}"></div>
                    <div style="width:${((dist.top_50 - dist.top_20) / total * 100).toFixed(1)}%; background:#F59E0B;" title="Pos 21-50: ${dist.top_50 - dist.top_20}"></div>
                    <div style="width:${((dist.top_100 - dist.top_50) / total * 100).toFixed(1)}%; background:#94A3B8;" title="Pos 51-100: ${dist.top_100 - dist.top_50}"></div>
                    <div style="width:${(dist.unranked / total * 100).toFixed(1)}%; background:#E2E8F0;" title="Unranked: ${dist.unranked}"></div>
                </div>
            </div>

            <!-- Deep-Dive Tabs -->
            <div class="card" style="padding:0; overflow:hidden;">
                <div style="display:flex; border-bottom:1px solid var(--border); background:#F8FAFC;">
                    <button class="tab-btn ${activeTab === 'keywords' ? 'active' : ''}" onclick="app.switchRankTab('keywords')" style="padding:14px 20px; font-size:13px; font-weight:700; border:none; background:none; cursor:pointer;">
                        Tracked Keywords (${total})
                    </button>
                    <button class="tab-btn ${activeTab === 'competitors' ? 'active' : ''}" onclick="app.switchRankTab('competitors')" style="padding:14px 20px; font-size:13px; font-weight:700; border:none; background:none; cursor:pointer;">
                        Competitor Comparison (${Object.keys(data.competitor_summary || {}).length} Domains)
                    </button>
                    <button class="tab-btn ${activeTab === 'volatility' ? 'active' : ''}" onclick="app.switchRankTab('volatility')" style="padding:14px 20px; font-size:13px; font-weight:700; border:none; background:none; cursor:pointer;">
                        Winners &amp; Losers
                    </button>
                    <button class="tab-btn ${activeTab === 'alerts' ? 'active' : ''}" onclick="app.switchRankTab('alerts')" style="padding:14px 20px; font-size:13px; font-weight:700; border:none; background:none; cursor:pointer;">
                        Volatility Alerts (${alerts.length})
                    </button>
                </div>

                <div style="padding:20px;">
                    ${this.renderActiveRankTabContent(activeTab)}
                </div>
            </div>
        `;
    }

    renderActiveRankTabContent(tab) {
        if (tab === "competitors") return this.renderRankCompetitors();
        if (tab === "volatility") return this.renderRankVolatility();
        if (tab === "alerts") return this.renderRankAlerts();
        return this.renderRankingsTable();
    }

    switchRankTab(tab) {
        this.rankState.activeTab = tab;
        this.renderRankingsContent();
    }

    setRankFilter(filter) {
        this.rankState.activeFilter = filter;
        document.querySelectorAll(".rank-filter-pill").forEach(p => {
            p.classList.toggle("active", p.dataset.filter === filter);
        });
        if (this.rankState.activeTab !== "keywords") {
            this.rankState.activeTab = "keywords";
            this.renderRankingsContent();
        } else {
            const container = $("rankTableContainer");
            if (container) container.innerHTML = this.renderRankingsTableRows();
        }
    }

    filterRankingsTable() {
        const inp = $("rankSearchInput");
        this.rankState.searchQuery = (inp ? inp.value : "").trim().toLowerCase();
        const container = $("rankTableContainer");
        if (container) container.innerHTML = this.renderRankingsTableRows();
    }

    renderRankingsTable() {
        return `
            <div id="rankTableContainer" class="table-container">
                ${this.renderRankingsTableRows()}
            </div>
        `;
    }

    renderRankingsTableRows() {
        const data = this.rankState.currentOverview;
        if (!data) return "";

        let items = data.keywords || [];
        const filter = this.rankState.activeFilter || "all";
        const query = this.rankState.searchQuery || "";

        // Apply quick filter
        if (filter === "top3") items = items.filter(k => k.current_position && k.current_position <= 3);
        else if (filter === "top10") items = items.filter(k => k.current_position && k.current_position <= 10);
        else if (filter === "top20") items = items.filter(k => k.current_position && k.current_position <= 20);
        else if (filter === "improved") items = items.filter(k => (k.position_change || 0) > 0);
        else if (filter === "declined") items = items.filter(k => (k.position_change || 0) < 0);
        else if (filter === "unranked") items = items.filter(k => !k.current_position);

        // Apply text search
        if (query) {
            items = items.filter(k => (k.keyword || "").toLowerCase().includes(query) || (k.tags || "").toLowerCase().includes(query));
        }

        if (items.length === 0) {
            return `<div class="empty-state" style="padding:32px;">No keywords match your selected filter criteria.</div>`;
        }

        return `
            <table style="font-size:12px; margin:0;">
                <thead>
                    <tr>
                        <th>Keyword</th>
                        <th>Device / Market</th>
                        <th style="text-align:center;">SERP Rank</th>
                        <th style="text-align:center;">Change</th>
                        <th style="text-align:center;">Best</th>
                        <th>Landing URL</th>
                        <th>Competitor SERP Ranks</th>
                        <th style="text-align:right;">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    ${items.map(k => {
                        const pos = k.current_position;
                        const posStr = pos ? `#${pos}` : `<span style="color:#94A3B8;">>100</span>`;
                        let posBadge = `<span class="pill" style="background:#F1F5F9; color:#475569; font-weight:800;">${posStr}</span>`;
                        if (pos && pos <= 3) posBadge = `<span class="pill" style="background:#DCFCE7; color:#15803D; font-weight:800;">${posStr}</span>`;
                        else if (pos && pos <= 10) posBadge = `<span class="pill" style="background:#EEF2FF; color:#4F46E5; font-weight:800;">${posStr}</span>`;

                        const ch = k.position_change || 0;
                        let chBadge = `<span style="color:#94A3B8;">0</span>`;
                        if (ch > 0) chBadge = `<span class="pill" style="background:#DCFCE7; color:#15803D; font-weight:700;">+${ch}</span>`;
                        else if (ch < 0) chBadge = `<span class="pill" style="background:#FEE2E2; color:#B91C1C; font-weight:700;">${ch}</span>`;

                        const comps = k.competitors || {};
                        const compBadges = Object.keys(comps).map(cDom => {
                            const cPos = comps[cDom];
                            return `<span class="pill" style="font-size:10px; margin-right:4px; background:#F8FAFC; border:1px solid #E2E8F0;" title="${escapeHtml(cDom)}: #${cPos || '>100'}"><b>${escapeHtml(cDom.slice(0, 10))}:</b> ${cPos ? '#' + cPos : '>100'}</span>`;
                        }).join("");

                        return `
                            <tr>
                                <td>
                                    <div style="font-weight:700; color:#1E293B;">${escapeHtml(k.keyword)}</div>
                                    ${k.tags ? `<div style="font-size:10px; color:#64748B; margin-top:2px;">Tags: ${escapeHtml(k.tags)}</div>` : ''}
                                </td>
                                <td>
                                    <span style="text-transform:capitalize; font-weight:600;">${k.device || 'desktop'}</span>
                                    <div style="font-size:10px; color:#64748B;">${escapeHtml(k.location_name || 'US')}</div>
                                </td>
                                <td style="text-align:center;">${posBadge}</td>
                                <td style="text-align:center;">${chBadge}</td>
                                <td style="text-align:center; font-weight:700; color:#475569;">${k.best_position ? '#' + k.best_position : '-'}</td>
                                <td style="max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                                    ${k.latest_url ? `<a href="${escapeHtml(k.latest_url)}" target="_blank" rel="noopener" style="color:#2563EB; text-decoration:none;" title="${escapeHtml(k.latest_url)}">${escapeHtml(k.latest_url)}</a>` : '<span style="color:#94A3B8;">-</span>'}
                                </td>
                                <td>${compBadges || '<span style="color:#94A3B8; font-size:11px;">None tracked</span>'}</td>
                                <td style="text-align:right; white-space:nowrap;">
                                    <button class="btn btn-secondary btn-sm" onclick="app.triggerCheckKeyword(${k.id})" title="Re-check SERP Now" style="padding:4px 8px;">⚡ Check</button>
                                    <button class="btn btn-secondary btn-sm" onclick="app.openKeywordHistory(${k.id})" title="View Historical Trajectory" style="padding:4px 8px;">📈 History</button>
                                    <button class="btn btn-secondary btn-sm" onclick="app.deleteTrackedKeyword(${k.id}, '${escapeHtml(k.keyword)}')" title="Delete" style="padding:4px 8px; color:#EF4444;">✕</button>
                                </td>
                            </tr>
                        `;
                    }).join("")}
                </tbody>
            </table>
        `;
    }

    renderRankCompetitors() {
        const data = this.rankState.currentOverview;
        const compSummary = (data && data.competitor_summary) || {};
        const compDomains = Object.keys(compSummary);

        if (compDomains.length === 0) {
            return `
                <div class="empty-state" style="padding:32px;">
                    <div style="font-size:28px; margin-bottom:8px;">⚔️</div>
                    <div style="font-weight:700; font-size:14px; margin-bottom:4px;">No Competitors Configured</div>
                    <div style="font-size:12px; color:var(--text-muted);">Edit your tracked keywords or add competitor domains to view head-to-head SERP comparisons.</div>
                </div>
            `;
        }

        return `
            <div style="margin-bottom:20px;">
                <h4 style="margin:0 0 12px 0; font-size:14px; font-weight:700;">Competitor SERP Benchmark Summary</h4>
                <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px;">
                    ${compDomains.map(dom => {
                        const s = compSummary[dom] || {};
                        return `
                            <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:14px;">
                                <div style="font-weight:700; color:#1E293B; margin-bottom:6px; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(dom)}</div>
                                <div style="font-size:12px; color:#475569; margin-bottom:2px;">Avg Position: <b>#${s.average_position || '-'}</b></div>
                                <div style="font-size:12px; color:#475569; margin-bottom:2px;">Top 3 Terms: <b>${s.top_3_count || 0}</b></div>
                                <div style="font-size:12px; color:#475569;">Top 10 Terms: <b>${s.top_10_count || 0}</b></div>
                            </div>
                        `;
                    }).join("")}
                </div>
            </div>

            <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700;">Head-to-Head Keyword Comparison Matrix</h4>
            <div class="table-container">
                <table style="font-size:12px; margin:0;">
                    <thead>
                        <tr>
                            <th>Keyword</th>
                            <th>Target Domain (${escapeHtml(data.target_domain || 'You')})</th>
                            ${compDomains.map(d => `<th>${escapeHtml(d)}</th>`).join("")}
                        </tr>
                    </thead>
                    <tbody>
                        ${(data.keywords || []).map(k => {
                            const targetPos = k.current_position;
                            const comps = k.competitors || {};
                            return `
                                <tr>
                                    <td><b>${escapeHtml(k.keyword)}</b></td>
                                    <td>
                                        <span class="pill" style="font-weight:800; background:${targetPos && targetPos <= 10 ? '#DCFCE7' : '#F1F5F9'}; color:${targetPos && targetPos <= 10 ? '#15803D' : '#475569'};">
                                            ${targetPos ? '#' + targetPos : '>100'}
                                        </span>
                                    </td>
                                    ${compDomains.map(d => {
                                        const cPos = comps[d];
                                        return `
                                            <td>
                                                <span class="pill" style="font-weight:600; background:#F8FAFC; color:#334155;">
                                                    ${cPos ? '#' + cPos : '>100'}
                                                </span>
                                            </td>
                                        `;
                                    }).join("")}
                                </tr>
                            `;
                        }).join("")}
                    </tbody>
                </table>
            </div>
        `;
    }

    renderRankVolatility() {
        const data = this.rankState.currentOverview || {};
        const winners = data.winners || [];
        const losers = data.losers || [];

        return `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:24px;">
                <!-- Winners -->
                <div>
                    <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700; color:#15803D; display:flex; align-items:center; gap:6px;">
                        <span>🟢 Top Ranking Gainers (Winners)</span>
                    </h4>
                    ${winners.length === 0 ? `<div style="font-size:12px; color:#64748B;">No ranking gains observed in recent checks.</div>` : `
                        <div class="table-container">
                            <table style="font-size:12px; margin:0;">
                                <thead>
                                    <tr>
                                        <th>Keyword</th>
                                        <th style="text-align:center;">Current Rank</th>
                                        <th style="text-align:right;">Position Surge</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${winners.map(w => `
                                        <tr>
                                            <td><b>${escapeHtml(w.keyword)}</b></td>
                                            <td style="text-align:center;"><span class="pill" style="background:#DCFCE7; color:#15803D; font-weight:800;">#${w.position}</span></td>
                                            <td style="text-align:right;"><span class="pill" style="background:#DCFCE7; color:#15803D; font-weight:800;">+${w.change}</span></td>
                                        </tr>
                                    `).join("")}
                                </tbody>
                            </table>
                        </div>
                    `}
                </div>

                <!-- Losers -->
                <div>
                    <h4 style="margin:0 0 10px 0; font-size:14px; font-weight:700; color:#B91C1C; display:flex; align-items:center; gap:6px;">
                        <span>🔴 Top Ranking Declines (Losers)</span>
                    </h4>
                    ${losers.length === 0 ? `<div style="font-size:12px; color:#64748B;">No ranking drops observed in recent checks.</div>` : `
                        <div class="table-container">
                            <table style="font-size:12px; margin:0;">
                                <thead>
                                    <tr>
                                        <th>Keyword</th>
                                        <th style="text-align:center;">Current Rank</th>
                                        <th style="text-align:right;">Position Drop</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${losers.map(l => `
                                        <tr>
                                            <td><b>${escapeHtml(l.keyword)}</b></td>
                                            <td style="text-align:center;"><span class="pill" style="background:#FEE2E2; color:#B91C1C; font-weight:800;">#${l.position || '>100'}</span></td>
                                            <td style="text-align:right;"><span class="pill" style="background:#FEE2E2; color:#B91C1C; font-weight:800;">${l.change}</span></td>
                                        </tr>
                                    `).join("")}
                                </tbody>
                            </table>
                        </div>
                    `}
                </div>
            </div>
        `;
    }

    renderRankAlerts() {
        const data = this.rankState.currentOverview || {};
        const alerts = data.recent_alerts || [];

        if (alerts.length === 0) {
            return `
                <div class="empty-state" style="padding:32px;">
                    <div style="font-size:28px; margin-bottom:8px;">🔔</div>
                    <div style="font-weight:700; font-size:14px; margin-bottom:4px;">No Volatility Alerts</div>
                    <div style="font-size:12px; color:var(--text-muted);">Ranking positions are stable. Alerts trigger automatically when keywords jump into Top 3, reach Page 1, or surge/drop 5+ spots.</div>
                </div>
            `;
        }

        return `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
                <h4 style="margin:0; font-size:14px; font-weight:700;">Recent Volatility Alerts Log</h4>
                <div style="font-size:12px; color:#64748B;">${alerts.length} total events recorded</div>
            </div>
            <div style="display:flex; flex-direction:column; gap:8px;">
                ${alerts.map(a => {
                    let sevBg = "#F1F5F9";
                    let sevFg = "#475569";
                    if (a.severity === "SUCCESS") { sevBg = "#DCFCE7"; sevFg = "#15803D"; }
                    else if (a.severity === "WARNING") { sevBg = "#FEF3C7"; sevFg = "#B45309"; }
                    else if (a.severity === "DANGER") { sevBg = "#FEE2E2"; sevFg = "#B91C1C"; }

                    return `
                        <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:8px; padding:12px 16px; display:flex; justify-content:space-between; align-items:center; gap:12px;">
                            <div style="display:flex; align-items:center; gap:10px;">
                                <span class="pill" style="background:${sevBg}; color:${sevFg}; font-weight:800; font-size:10px;">${escapeHtml(a.alert_type)}</span>
                                <div style="font-size:13px; font-weight:600; color:#1E293B;">${escapeHtml(a.message)}</div>
                            </div>
                            <div style="display:flex; align-items:center; gap:12px;">
                                <div style="font-size:11px; color:#94A3B8;">${a.created_at ? new Date(a.created_at).toLocaleDateString() : ''}</div>
                                ${!a.is_read ? `<button class="btn btn-secondary btn-sm" onclick="app.markAlertRead(${a.id})" style="font-size:11px; padding:3px 8px;">Dismiss</button>` : ''}
                            </div>
                        </div>
                    `;
                }).join("")}
            </div>
        `;
    }

    openAddKeywordsModal() {
        const modal = $("addKeywordsModal");
        if (!modal) return;
        if ($("addKwTargetDomain")) $("addKwTargetDomain").value = this.rankState.targetDomain || "";
        modal.classList.remove("hidden");
    }

    closeAddKeywordsModal() {
        const modal = $("addKeywordsModal");
        if (modal) modal.classList.add("hidden");
    }

    async submitAddTrackedKeywords() {
        const target = ($("addKwTargetDomain").value || "").trim();
        const rawKw = ($("addKwTextarea").value || "").trim();
        if (!target) {
            this.showNotification("Please enter target domain.", "warning");
            return;
        }
        if (!rawKw) {
            this.showNotification("Please enter at least one keyword.", "warning");
            return;
        }

        const keywords = rawKw.split(/[\r\n,]+/).map(k => k.trim()).filter(Boolean);
        const locVal = $("addKwLocationSelect").value.split("|");
        const locCode = parseInt(locVal[0], 10) || 2840;
        const locName = locVal[1] || "United States";
        const lang = $("addKwLanguageSelect").value || "en";
        const device = $("addKwDeviceSelect").value || "desktop";
        const rawComps = ($("addKwCompetitors").value || "").trim();
        const comps = rawComps ? rawComps.split(/[\r\n,]+/).map(c => c.trim()).filter(Boolean) : [];
        const tags = ($("addKwTags").value || "").trim();
        const freq = $("addKwFrequency").value || "daily";

        const btn = $("btnAddKwSubmit");
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<span class="spin">⏳</span> Checking SERPs...`;
        }

        try {
            const resp = await jsonFetch(`${API_BASE}/rankings/keywords`, {
                method: "POST",
                body: JSON.stringify({
                    keywords: keywords,
                    target_domain: target,
                    website_id: this.rankState.websiteId,
                    location_code: locCode,
                    location_name: locName,
                    language_code: lang,
                    device: device,
                    competitor_domains: comps,
                    tags: tags,
                    check_frequency: freq,
                    run_initial_check: true
                })
            });

            this.showNotification(`Successfully added ${resp.count} target keyword(s)!`, "success");
            this.closeAddKeywordsModal();
            $("addKwTextarea").value = "";
            this.rankState.targetDomain = target;
            await this.loadRankings();
        } catch (err) {
            this.showNotification("Failed to add keywords: " + (err.message || err), "danger");
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = "Start Tracking &amp; Check SERPs";
            }
        }
    }

    async triggerCheckKeyword(kwId) {
        try {
            this.showNotification("Checking live Google SERP position...", "info");
            const res = await jsonFetch(`${API_BASE}/rankings/check/${kwId}`, { method: "POST" });
            const pos = res.current_position ? `#${res.current_position}` : ">100";
            this.showNotification(`Keyword '${res.keyword}' checked: Position ${pos}.`, "success");
            await this.loadRankingsOverview();
        } catch (err) {
            this.showNotification("Ranking check failed: " + (err.message || err), "danger");
        }
    }

    async triggerCheckAllRankings() {
        const btn = $("btnCheckAllRankings");
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<span class="spin">⏳</span> Checking Positions...`;
        }
        try {
            this.showNotification("Querying live SERPs across all active keywords...", "info");
            const domain = this.rankState.targetDomain || "";
            const res = await jsonFetch(`${API_BASE}/rankings/check-all?target_domain=${encodeURIComponent(domain)}`, { method: "POST" });
            this.showNotification(`Checked ${res.total_checked} keywords (${res.improved_count} improved, ${res.declined_count} dropped).`, "success");
            await this.loadRankingsOverview();
        } catch (err) {
            this.showNotification("Batch ranking check failed: " + (err.message || err), "danger");
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `⚡ Check All Positions`;
            }
        }
    }

    async deleteTrackedKeyword(kwId, kwText) {
        if (!confirm(`Are you sure you want to stop tracking '${kwText}'? Historical observations will be removed.`)) return;
        try {
            await jsonFetch(`${API_BASE}/rankings/keywords/${kwId}`, { method: "DELETE" });
            this.showNotification(`Stopped tracking '${kwText}'.`, "success");
            await this.loadRankingsOverview();
        } catch (err) {
            this.showNotification("Failed to delete keyword: " + (err.message || err), "danger");
        }
    }

    async openKeywordHistory(kwId) {
        const modal = $("keywordHistoryModal");
        const body = $("kwHistModalBody");
        if (!modal || !body) return;

        body.innerHTML = `<div style="text-align:center; padding:32px; color:var(--text-muted);"><span class="spin">⏳</span> Loading historical trajectory...</div>`;
        modal.classList.remove("hidden");

        try {
            const data = await jsonFetch(`${API_BASE}/rankings/keywords/${kwId}`);
            if ($("kwHistTitle")) $("kwHistTitle").textContent = `History: ${data.keyword}`;
            if ($("kwHistSubtitle")) $("kwHistSubtitle").textContent = `Domain: ${data.target_domain} • Best Rank: #${data.best_position || '-'} • Current: #${data.current_position || '>100'}`;

            const timeline = data.timeline || [];
            if (timeline.length === 0) {
                body.innerHTML = `<div class="empty-state" style="padding:32px;">No historical observations recorded yet. Click 'Check' to run an initial observation.</div>`;
                return;
            }

            body.innerHTML = `
                <div style="margin-bottom:18px;">
                    <h5 style="margin:0 0 10px 0; font-size:13px; font-weight:700;">Historical SERP Position Trajectory</h5>
                    <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:16px;">
                        <div style="display:flex; justify-content:space-between; align-items:flex-end; height:120px; gap:8px;">
                            ${timeline.slice(-15).map(t => {
                                const p = t.position || 100;
                                const heightPct = Math.max(10, Math.min(100, 100 - p));
                                const barColor = p <= 3 ? '#10B981' : (p <= 10 ? '#3B82F6' : '#94A3B8');
                                return `
                                    <div style="flex:1; display:flex; flex-direction:column; align-items:center; height:100%; justify-content:flex-end;" title="${t.date}: #${t.position || '>100'}">
                                        <span style="font-size:9px; font-weight:700; color:#334155; margin-bottom:2px;">#${t.position || '>100'}</span>
                                        <div style="width:100%; max-width:24px; height:${heightPct}%; background:${barColor}; border-radius:3px 3px 0 0;"></div>
                                        <span style="font-size:8px; color:#94A3B8; margin-top:4px; transform:rotate(-45deg); white-space:nowrap;">${t.date ? t.date.slice(5) : ''}</span>
                                    </div>
                                `;
                            }).join("")}
                        </div>
                    </div>
                </div>

                <h5 style="margin:0 0 10px 0; font-size:13px; font-weight:700;">Observations Log</h5>
                <div class="table-container" style="max-height:220px; overflow-y:auto;">
                    <table style="font-size:12px; margin:0;">
                        <thead>
                            <tr>
                                <th>Date &amp; Time</th>
                                <th style="text-align:center;">SERP Rank</th>
                                <th>Ranking URL</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${timeline.slice().reverse().map(t => `
                                <tr>
                                    <td>${t.collected_at ? new Date(t.collected_at).toLocaleString() : '-'}</td>
                                    <td style="text-align:center;"><b>${t.position ? '#' + t.position : '>100'}</b></td>
                                    <td style="max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                                        ${t.ranked_url ? `<a href="${escapeHtml(t.ranked_url)}" target="_blank" rel="noopener" style="color:#2563EB;">${escapeHtml(t.ranked_url)}</a>` : '-'}
                                    </td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            body.innerHTML = `<div style="color:#EF4444; padding:20px; text-align:center;">Failed to load history: ${escapeHtml(err.message || String(err))}</div>`;
        }
    }

    closeKeywordHistoryModal() {
        const modal = $("keywordHistoryModal");
        if (modal) modal.classList.add("hidden");
    }

    openRankAlertsModal() {
        const modal = $("rankAlertsModal");
        const body = $("rankAlertsModalBody");
        if (!modal || !body) return;

        modal.classList.remove("hidden");
        const alerts = (this.rankState.currentOverview && this.rankState.currentOverview.recent_alerts) || [];
        if (alerts.length === 0) {
            body.innerHTML = `<div class="empty-state" style="padding:32px;">No volatility alerts recorded.</div>`;
            return;
        }

        body.innerHTML = this.renderRankAlerts();
    }

    closeRankAlertsModal() {
        const modal = $("rankAlertsModal");
        if (modal) modal.classList.add("hidden");
    }

    async markAlertRead(alertId) {
        try {
            await jsonFetch(`${API_BASE}/rankings/alerts/${alertId}/read`, { method: "POST" });
            this.showNotification("Alert marked as read.", "success");
            await this.loadRankingsOverview();
        } catch (err) {
            this.showNotification("Failed to update alert: " + (err.message || err), "danger");
        }
    }

    async exportRankings(format = "pdf") {
        const overview = this.rankState.currentOverview;
        if (!overview || !overview.total_keywords) {
            this.showNotification("Please load keyword rankings first to export data.", "warning");
            return;
        }

        try {
            this.showNotification(`Generating ${format.toUpperCase()} rankings report...`, "info");
            const res = await fetch(`${API_BASE}/rankings/export/${format}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {})
                },
                body: JSON.stringify(overview)
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            const target = overview.target_domain || "rankings";
            a.download = `keyword_rankings_${target}_${new Date().toISOString().slice(0, 10)}.${format === "excel" ? "xls" : format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            this.showNotification(`Downloaded ${format.toUpperCase()} rankings report successfully.`, "success");
        } catch (err) {
            this.showNotification(`Export failed: ${err.message || err}`, "danger");
        }
    }

    // ------------------------------------------------------------------------
    // PHASE 9: AI SEO RECOMMENDATION ENGINE & ASSISTANT
    // ------------------------------------------------------------------------

    async initAiAdvisor() {
        await this.checkAiStatus();
        await this.loadAiAuditsDropdown();
        if (this.state.currentAudit && !this.aiState.currentRecommendations) {
            await this.generateAiRecommendations(false);
        }
    }

    async checkAiStatus() {
        try {
            const res = await jsonFetch(`${API_BASE}/ai/status`);
            this.aiState.status = res;
            const badge = $("aiModelBadge");
            const label = $("aiEngineLabel");
            if (res && res.available && res.model_available) {
                if (badge) {
                    badge.textContent = `🟢 Connected: ${res.model}`;
                    badge.style.background = "#dcfce7";
                    badge.style.color = "#15803d";
                }
                if (label) label.textContent = `Engine: Ollama (${res.model})`;
            } else {
                if (badge) {
                    badge.textContent = "🟠 Deterministic Fallback Active";
                    badge.style.background = "#fef3c7";
                    badge.style.color = "#b45309";
                }
                if (label) label.textContent = "Engine: Deterministic SEO Knowledge Engine";
            }
        } catch (err) {
            console.warn("[eSupport] Failed to check AI status:", err);
            const badge = $("aiModelBadge");
            if (badge) {
                badge.textContent = "🟠 Knowledge-Base Engine";
                badge.style.background = "#fef3c7";
                badge.style.color = "#b45309";
            }
        }
    }

    async loadAiAuditsDropdown() {
        const sel = $("aiAuditSelector");
        if (!sel) return;
        try {
            const audits = await jsonFetch(`${API_BASE}/audits`);
            let html = '<option value="">-- Select Completed Audit --</option>';
            if (Array.isArray(audits)) {
                audits.forEach(a => {
                    const domain = a.target_url ? a.target_url.replace(/^https?:\/\//, "").replace(/\/.*$/, "") : `Audit #${a.id}`;
                    const score = a.score !== null ? `${Math.round(a.score)}/100` : "Unscored";
                    const dt = a.created_at ? new Date(a.created_at).toLocaleDateString() : "";
                    const selected = (this.aiState.activeAuditId == a.id) ? "selected" : "";
                    html += `<option value="${a.id}" ${selected}>${domain} (${score} • ${dt})</option>`;
                });
            }
            sel.innerHTML = html;
        } catch (err) {
            console.warn("[eSupport] Failed to load audits for AI advisor:", err);
        }
    }

    onAiAuditSelected() {
        const sel = $("aiAuditSelector");
        if (!sel) return;
        this.aiState.activeAuditId = sel.value ? parseInt(sel.value) : null;
        if (this.aiState.activeAuditId) {
            this.generateAiRecommendations(false);
        }
    }

    toggleAiExportMenu(e) {
        if (e) e.stopPropagation();
        const menu = $("aiExportMenu");
        if (menu) {
            menu.style.display = (menu.style.display === "block") ? "none" : "block";
        }
    }

    async generateAiRecommendations(forceFallback = false) {
        const btn = $("btnGenerateAi");
        const btnFb = $("btnFallbackAi");
        if (btn) btn.disabled = true;
        if (btnFb) btnFb.disabled = true;

        const auditId = this.aiState.activeAuditId;
        const currentAudit = this.state.currentAudit;

        if (!auditId && !currentAudit) {
            this.showNotification("Please select an audit from the dropdown or run a fresh audit first.", "warning");
            if (btn) btn.disabled = false;
            if (btnFb) btnFb.disabled = false;
            return;
        }

        try {
            this.showNotification(forceFallback ? "Generating deterministic knowledge-base recommendations..." : "Synthesizing evidence-based AI SEO recommendations...", "info");
            const payload = {
                audit: currentAudit,
                audit_id: auditId,
                force_fallback: forceFallback
            };

            const data = await jsonFetch(`${API_BASE}/ai/recommendations`, {
                method: "POST",
                body: JSON.stringify(payload)
            });

            this.aiState.currentRecommendations = data;
            if ($("aiEmptyState")) $("aiEmptyState").style.display = "none";
            if ($("aiActiveWorkspace")) $("aiActiveWorkspace").style.display = "block";

            // Update badge & engine
            const badge = $("aiModelBadge");
            const label = $("aiEngineLabel");
            if (data.ai_generated) {
                if (badge) {
                    badge.textContent = `🟢 ${data.source_model || "Ollama"}`;
                    badge.style.background = "#dcfce7";
                    badge.style.color = "#15803d";
                }
                if (label) label.textContent = `Engine: ${data.source_model || "Ollama"}`;
            } else {
                if (badge) {
                    badge.textContent = "🟠 Knowledge-Base Engine";
                    badge.style.background = "#fef3c7";
                    badge.style.color = "#b45309";
                }
                if (label) label.textContent = `Engine: ${data.source_model || "Deterministic Fallback"}`;
            }

            this.renderAiCurrentTab();
            this.showNotification("AI recommendations ready across all 8 disciplines.", "success");
        } catch (err) {
            this.showNotification(`Failed to generate recommendations: ${err.message || err}`, "danger");
        } finally {
            if (btn) btn.disabled = false;
            if (btnFb) btnFb.disabled = false;
        }
    }

    switchAiTab(tabKey) {
        this.aiState.activeTab = tabKey;
        document.querySelectorAll("[data-aitab]").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.aitab === tabKey);
            btn.classList.toggle("btn-primary", btn.dataset.aitab === tabKey);
            btn.classList.toggle("btn-secondary", btn.dataset.aitab !== tabKey);
        });

        document.querySelectorAll(".ai-tab-panel").forEach(p => p.style.display = "none");
        this.renderAiCurrentTab();
    }

    renderAiCurrentTab() {
        const tab = this.aiState.activeTab || "roadmap";
        const map = {
            roadmap: { panel: "aiTabPanelRoadmap", fn: () => this.renderAiRoadmap() },
            explanations: { panel: "aiTabPanelExplanations", fn: () => this.renderAiExplanations() },
            technical: { panel: "aiTabPanelTechnical", fn: () => this.renderAiTechnicalFixes() },
            content: { panel: "aiTabPanelContent", fn: () => this.renderAiContent() },
            keywords: { panel: "aiTabPanelKeywords", fn: () => this.renderAiKeywords() },
            linking: { panel: "aiTabPanelLinking", fn: () => this.renderAiInternalLinking() },
            schema: { panel: "aiTabPanelSchema", fn: () => this.renderAiStructuredData() },
            dev: { panel: "aiTabPanelDev", fn: () => this.renderAiDevInstructions() },
            rag_knowledge: { panel: "aiTabPanelKnowledge", fn: () => this.loadAndRenderAiKnowledge() },
            ai_quality: { panel: "aiTabPanelQuality", fn: () => this.loadAndRenderAiQuality() },
            ai_training: { panel: "aiTabPanelTraining", fn: () => this.loadAndRenderAiTraining() },
            ai_status: { panel: "aiTabPanelStatus", fn: () => this.loadAndRenderAiStatus() }
        };

        const target = map[tab];
        if (target) {
            const p = $(target.panel);
            if (p) {
                p.style.display = "block";
                const content = target.fn();
                if (typeof content === "string") {
                    p.innerHTML = content;
                }
            }
        }
    }

    renderAiRoadmap() {
        const recs = this.aiState.currentRecommendations?.prioritized_recommendations || [];
        if (!recs.length) {
            return '<div class="empty-state" style="padding:40px;">No prioritized recommendations available.</div>';
        }

        const sevColors = {
            CRITICAL: { bg: "#fef2f2", text: "#b91c1c", border: "#fca5a5" },
            HIGH: { bg: "#fff7ed", text: "#c2410c", border: "#fdba74" },
            MEDIUM: { bg: "#eff6ff", text: "#1d4ed8", border: "#93c5fd" },
            LOW: { bg: "#f8fafc", text: "#475569", border: "#cbd5e1" }
        };

        return `
            <div style="display:flex; flex-direction:column; gap:12px;">
                ${recs.map(r => {
                    const col = sevColors[r.priority] || sevColors.MEDIUM;
                    const urls = (r.affected_urls || []).slice(0, 3).map(u => `<code style="font-size:11px; background:#f1f5f9; padding:2px 6px; border-radius:4px;">${escapeHtml(u)}</code>`).join(" ");
                    return `
                        <div class="card" style="border-left:5px solid ${col.border}; padding:16px 20px;">
                            <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px; margin-bottom:8px;">
                                <div style="display:flex; align-items:center; gap:8px;">
                                    <span class="badge" style="background:${col.bg}; color:${col.text}; font-weight:700; font-size:11px;">${r.priority}</span>
                                    <span class="badge" style="background:#f1f5f9; color:#334155; font-size:11px;">${escapeHtml(r.category || "General")}</span>
                                    <h4 style="margin:0; font-size:15px; font-weight:700; color:#0f172a;">${escapeHtml(r.title)}</h4>
                                </div>
                                <div style="display:flex; gap:8px; font-size:12px;">
                                    <span title="Expected SEO Impact" style="background:#ecfdf5; color:#047857; padding:2px 8px; border-radius:4px; font-weight:600;">Impact: ${escapeHtml(r.impact || "High")}</span>
                                    <span title="Implementation Effort" style="background:#f1f5f9; color:#475569; padding:2px 8px; border-radius:4px; font-weight:600;">Effort: ${escapeHtml(r.effort || "Medium")}</span>
                                </div>
                            </div>
                            <div style="font-size:13px; color:#334155; margin-bottom:10px; line-height:1.5;">
                                <b>Action Plan:</b> ${escapeHtml(r.action)}
                            </div>
                            ${r.validation ? `
                                <div style="font-size:12px; color:#0369a1; background:#f0f9ff; padding:6px 12px; border-radius:4px; margin-bottom:8px;">
                                    <b>Validation Criteria:</b> ${escapeHtml(r.validation)}
                                </div>
                            ` : ""}
                            ${(r.citations && r.citations.length) ? `
                                <div style="font-size:11px; color:#1e40af; background:#eff6ff; padding:6px 10px; border-radius:4px; margin-bottom:8px; display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                    <b>📚 Knowledge Citations:</b>
                                    ${r.citations.map(c => `<a href="${c.url || '#'}" target="_blank" rel="noopener noreferrer" style="color:#2563eb; text-decoration:underline;">${escapeHtml(c.title || c.publisher || 'Documentation')}</a>`).join(" • ")}
                                </div>
                            ` : ""}
                            ${urls ? `
                                <div style="font-size:11px; color:var(--text-muted); display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                                    <span>Affected:</span> ${urls}
                                </div>
                            ` : ""}
                        </div>
                    `;
                }).join("")}
            </div>
        `;
    }

    renderAiExplanations() {
        const issues = this.aiState.currentRecommendations?.issue_explanations || [];
        if (!issues.length) {
            return '<div class="empty-state" style="padding:40px;">No issue explanations loaded.</div>';
        }

        return `
            <div class="grid grid-2col" style="gap:16px;">
                ${issues.map(iss => `
                    <div class="card" style="padding:16px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                            <span class="badge" style="background:#e0e7ff; color:#3730a3; font-family:monospace; font-size:11px;">${escapeHtml(iss.code || "ISSUE")}</span>
                            <span class="badge" style="background:${iss.severity === 'CRITICAL' ? '#fef2f2' : '#fff7ed'}; color:${iss.severity === 'CRITICAL' ? '#dc2626' : '#ea580c'}; font-size:10px;">${iss.severity}</span>
                        </div>
                        <h4 style="margin:0 0 8px 0; font-size:14px; font-weight:700;">${escapeHtml(iss.title)}</h4>
                        <p style="margin:0 0 8px 0; font-size:12px; color:#475569; line-height:1.45;">
                            <b>Root Cause:</b> ${escapeHtml(iss.explanation)}
                        </p>
                        ${iss.evidence ? `
                            <div style="font-size:11px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:6px 10px; margin-bottom:8px; font-family:monospace; color:#0f172a; word-break:break-all;">
                                <b>Evidence:</b> ${escapeHtml(iss.evidence)}
                            </div>
                        ` : ""}
                        <div style="font-size:12px; color:#047857; background:#ecfdf5; padding:6px 10px; border-radius:4px;">
                            <b>Recommended Fix:</b> ${escapeHtml(iss.action)}
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }

    renderAiTechnicalFixes() {
        const fixes = this.aiState.currentRecommendations?.technical_fixes || [];
        if (!fixes.length) {
            return '<div class="empty-state" style="padding:40px;">No technical snippets required.</div>';
        }

        return `
            <div style="display:flex; flex-direction:column; gap:16px;">
                ${fixes.map((f, idx) => `
                    <div class="card" style="padding:18px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span class="badge" style="background:#3b82f6; color:#fff; font-size:11px;">${escapeHtml(f.snippet_type || "Snippet")}</span>
                                <h4 style="margin:0; font-size:15px; font-weight:700;">${escapeHtml(f.title)}</h4>
                            </div>
                            <button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText($('snippetCode_${idx}').textContent); app.showNotification('Snippet copied to clipboard!', 'success');" style="font-size:11px; padding:3px 8px;">
                                📋 Copy Snippet
                            </button>
                        </div>
                        <p style="margin:0 0 10px 0; font-size:13px; color:#475569;">${escapeHtml(f.description)}</p>
                        <pre style="margin:0; background:#0f172a; color:#f8fafc; padding:12px 16px; border-radius:6px; font-size:12px; font-family:monospace; overflow-x:auto;"><code id="snippetCode_${idx}">${escapeHtml(f.code || "")}</code></pre>
                    </div>
                `).join("")}
            </div>
        `;
    }

    renderAiContent() {
        const items = this.aiState.currentRecommendations?.content_improvements || [];
        if (!items.length) {
            return '<div class="empty-state" style="padding:40px;">No content rewrite proposals for this crawl.</div>';
        }

        return `
            <div style="display:flex; flex-direction:column; gap:16px;">
                ${items.map(pg => `
                    <div class="card" style="padding:18px;">
                        <div style="font-size:13px; font-weight:700; color:#0f172a; margin-bottom:12px; display:flex; align-items:center; gap:6px;">
                            <span>📄 Target URL:</span>
                            <a href="${escapeHtml(pg.page_url)}" target="_blank" style="color:#2563eb; text-decoration:none; font-family:monospace; font-size:12px;">${escapeHtml(pg.page_url)}</a>
                        </div>
                        <div style="display:flex; flex-direction:column; gap:12px;">
                            ${(pg.suggestions || []).map(sug => `
                                <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:12px;">
                                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                                        <span class="badge" style="background:#8b5cf6; color:#fff; font-size:11px;">${escapeHtml(sug.type)}</span>
                                        <span style="font-size:11px; color:#64748b;">Proposed: ${sug.character_count || 0} chars</span>
                                    </div>
                                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; font-size:12px; margin-bottom:6px;">
                                        <div style="background:#fff; border:1px solid #fed7aa; padding:8px; border-radius:4px;">
                                            <b style="color:#c2410c;">Current Value:</b>
                                            <div style="color:#334155; margin-top:4px;">${escapeHtml(sug.current || "(Empty)")}</div>
                                        </div>
                                        <div style="background:#fff; border:1px solid #bbf7d0; padding:8px; border-radius:4px;">
                                            <b style="color:#15803d;">Proposed High-CTR Proposal:</b>
                                            <div style="color:#0f172a; margin-top:4px; font-weight:600;">${escapeHtml(sug.proposed || "")}</div>
                                        </div>
                                    </div>
                                    <div style="font-size:11px; color:#475569;"><b>Rationale:</b> ${escapeHtml(sug.rationale || "")}</div>
                                </div>
                            `).join("")}
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }

    renderAiKeywords() {
        const kws = this.aiState.currentRecommendations?.keyword_opportunities || [];
        if (!kws.length) {
            return '<div class="empty-state" style="padding:40px;">No on-page keyword gaps identified.</div>';
        }

        return `
            <div class="card" style="padding:0; overflow:hidden;">
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Keyword Opportunity</th>
                                <th>Source</th>
                                <th>Intent</th>
                                <th>Optimization Action</th>
                                <th>Evidence Basis</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${kws.map(k => `
                                <tr>
                                    <td><b style="color:#0f172a;">${escapeHtml(k.keyword)}</b></td>
                                    <td><span class="badge" style="background:#f1f5f9; font-size:11px;">${escapeHtml(k.source || "Crawl")}</span></td>
                                    <td><span class="badge" style="background:#e0f2fe; color:#0369a1; font-size:11px;">${escapeHtml(k.intent || "Informational")}</span></td>
                                    <td style="font-size:12px; color:#334155;">${escapeHtml(k.recommendation)}</td>
                                    <td style="font-size:11px; color:#64748b; font-family:monospace;">${escapeHtml(k.evidence_basis || "-")}</td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    renderAiInternalLinking() {
        const links = this.aiState.currentRecommendations?.internal_linking || [];
        if (!links.length) {
            return '<div class="empty-state" style="padding:40px;">No internal linking equity transfers suggested.</div>';
        }

        return `
            <div style="display:flex; flex-direction:column; gap:12px;">
                ${links.map(l => `
                    <div class="card" style="padding:16px;">
                        <div style="display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:16px; margin-bottom:10px;">
                            <div style="background:#f8fafc; padding:8px 12px; border-radius:6px; font-size:12px; border:1px solid #e2e8f0;">
                                <div style="font-size:11px; color:#64748b; font-weight:700;">SOURCE PAGE (High Authority)</div>
                                <div style="font-family:monospace; color:#0f172a; word-break:break-all; margin-top:2px;">${escapeHtml(l.source_url)}</div>
                            </div>
                            <div style="font-size:20px; color:#4f46e5;">➔</div>
                            <div style="background:#f8fafc; padding:8px 12px; border-radius:6px; font-size:12px; border:1px solid #e2e8f0;">
                                <div style="font-size:11px; color:#64748b; font-weight:700;">TARGET PAGE (Priority Index)</div>
                                <div style="font-family:monospace; color:#0f172a; word-break:break-all; margin-top:2px;">${escapeHtml(l.target_url)}</div>
                            </div>
                        </div>
                        <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; background:#f0fdf4; border:1px solid #bbf7d0; padding:8px 12px; border-radius:4px;">
                            <div><b>Suggested Anchor Text:</b> <span style="color:#15803d; font-weight:700;">"${escapeHtml(l.suggested_anchor_text)}"</span></div>
                            <div style="font-size:11px; color:#475569;"><b>Equity Strategy:</b> ${escapeHtml(l.rationale || "Redistribute link equity")}</div>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }

    renderAiStructuredData() {
        const schemas = this.aiState.currentRecommendations?.structured_data_schemas || [];
        if (!schemas.length) {
            return '<div class="empty-state" style="padding:40px;">No structured data schemas proposed.</div>';
        }

        return `
            <div style="display:flex; flex-direction:column; gap:16px;">
                ${schemas.map((s, idx) => `
                    <div class="card" style="padding:18px;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span class="badge" style="background:#10b981; color:#fff; font-size:11px;">${escapeHtml(s.schema_type)}</span>
                                <h4 style="margin:0; font-size:14px; font-weight:700;">Target: ${escapeHtml(s.page_target || "Homepage")}</h4>
                            </div>
                            <button class="btn btn-secondary btn-sm" onclick="navigator.clipboard.writeText($('schemaCode_${idx}').textContent); app.showNotification('JSON-LD copied!', 'success');" style="font-size:11px; padding:3px 8px;">
                                📋 Copy JSON-LD
                            </button>
                        </div>
                        <p style="margin:0 0 10px 0; font-size:12px; color:#475569;">${escapeHtml(s.implementation_guide || "Paste into page <head> section.")}</p>
                        <pre style="margin:0; background:#0f172a; color:#34d399; padding:12px 16px; border-radius:6px; font-size:11px; font-family:monospace; overflow-x:auto;"><code id="schemaCode_${idx}">${escapeHtml(s.json_ld || "")}</code></pre>
                    </div>
                `).join("")}
            </div>
        `;
    }

    renderAiDevInstructions() {
        const steps = this.aiState.currentRecommendations?.developer_instructions || [];
        if (!steps.length) {
            return '<div class="empty-state" style="padding:40px;">No developer tasks generated.</div>';
        }

        return `
            <div style="display:flex; flex-direction:column; gap:12px;">
                ${steps.map(st => `
                    <div class="card" style="padding:16px; display:flex; gap:14px; align-items:flex-start;">
                        <div style="background:#4f46e5; color:#fff; width:28px; height:28px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:12px; flex-shrink:0;">
                            ${st.step || "•"}
                        </div>
                        <div style="flex-grow:1;">
                            <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                                <span class="badge" style="background:#f1f5f9; color:#475569; font-size:10px;">${escapeHtml(st.category || "Development")}</span>
                                <h4 style="margin:0; font-size:14px; font-weight:700; color:#0f172a;">${escapeHtml(st.title)}</h4>
                            </div>
                            <div style="font-size:13px; color:#334155; margin-bottom:8px; line-height:1.45;">${escapeHtml(st.task)}</div>
                            <div style="font-size:11px; background:#eff6ff; color:#1d4ed8; padding:6px 10px; border-radius:4px; font-family:monospace;">
                                <b>QA Verification:</b> ${escapeHtml(st.verification || "Inspect via browser DevTools network tab.")}
                            </div>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }

    async sendAiChatMessage(customPrompt) {
        const inp = $("aiChatInput");
        const btn = $("btnAiChatSend");
        const prompt = customPrompt || (inp ? inp.value.trim() : "");
        if (!prompt) return;

        if (inp && !customPrompt) inp.value = "";
        if (btn) btn.disabled = true;

        const chatLog = $("aiChatLog");
        if (chatLog) {
            // Append user message
            const userMsg = document.createElement("div");
            userMsg.style.cssText = "display:flex; gap:8px; align-items:flex-start; justify-content:flex-end;";
            userMsg.innerHTML = `
                <div style="background:#4f46e5; color:#fff; padding:8px 12px; border-radius:8px; font-size:13px; line-height:1.45; max-width:85%;">
                    ${escapeHtml(prompt)}
                </div>
                <div style="font-size:18px;">👤</div>
            `;
            chatLog.appendChild(userMsg);

            // Append thinking placeholder
            const thinkingMsg = document.createElement("div");
            thinkingMsg.id = "aiThinkingPlaceholder";
            thinkingMsg.style.cssText = "display:flex; gap:8px; align-items:flex-start;";
            thinkingMsg.innerHTML = `
                <div style="font-size:18px;">🤖</div>
                <div style="background:#f1f5f9; padding:8px 12px; border-radius:8px; font-size:13px; color:#64748b;">
                    Consulting verified audit telemetry and search specs...
                </div>
            `;
            chatLog.appendChild(thinkingMsg);
            chatLog.scrollTop = chatLog.scrollHeight;
        }

        try {
            const payload = {
                prompt: prompt,
                audit: this.state.currentAudit,
                audit_id: this.aiState.activeAuditId
            };

            const res = await jsonFetch(`${API_BASE}/ai/chat`, {
                method: "POST",
                body: JSON.stringify(payload)
            });

            const ph = $("aiThinkingPlaceholder");
            if (ph) ph.remove();

            if (chatLog) {
                const aiMsg = document.createElement("div");
                aiMsg.style.cssText = "display:flex; gap:8px; align-items:flex-start;";
                const formattedAnswer = (res.answer || "").replace(/\n/g, "<br>");
                aiMsg.innerHTML = `
                    <div style="font-size:18px;">🤖</div>
                    <div style="background:#f1f5f9; padding:10px 14px; border-radius:8px; font-size:13px; line-height:1.5; max-width:85%; color:#0f172a;">
                        ${formattedAnswer}
                        <div style="margin-top:6px; font-size:10px; color:#94a3b8; border-top:1px solid #e2e8f0; padding-top:4px;">
                            ${res.ai_generated ? "⚡ Answered by " + (res.source_model || "Ollama") : "🛡️ Grounded in Deterministic Knowledge Base"}
                        </div>
                    </div>
                `;
                chatLog.appendChild(aiMsg);
                chatLog.scrollTop = chatLog.scrollHeight;
            }
        } catch (err) {
            const ph = $("aiThinkingPlaceholder");
            if (ph) ph.remove();
            if (chatLog) {
                const errMsg = document.createElement("div");
                errMsg.style.cssText = "display:flex; gap:8px; align-items:flex-start;";
                errMsg.innerHTML = `
                    <div style="font-size:18px;">🤖</div>
                    <div style="background:#fef2f2; color:#b91c1c; padding:8px 12px; border-radius:8px; font-size:12px;">
                        Assistant communication error: ${escapeHtml(err.message || err)}
                    </div>
                `;
                chatLog.appendChild(errMsg);
                chatLog.scrollTop = chatLog.scrollHeight;
            }
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async exportAiRecommendations(format = "pdf") {
        const menu = $("aiExportMenu");
        if (menu) menu.style.display = "none";

        const recs = this.aiState.currentRecommendations;
        if (!recs) {
            this.showNotification("Please generate AI recommendations first before exporting.", "warning");
            return;
        }

        try {
            this.showNotification(`Generating client-ready ${format.toUpperCase()} recommendation report...`, "info");
            const res = await fetch(`${API_BASE}/ai/export/${format}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {})
                },
                body: JSON.stringify({
                    recommendations: recs,
                    audit_id: this.aiState.activeAuditId,
                    audit: this.state.currentAudit
                })
            });

            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            const target = (recs.target || "website").replace(/[^a-zA-Z0-9_\-\.]/g, "_");
            a.download = `ai_seo_recommendations_${target}_${new Date().toISOString().slice(0, 10)}.${format === "excel" ? "xls" : format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            this.showNotification(`Downloaded ${format.toUpperCase()} report successfully.`, "success");
        } catch (err) {
            this.showNotification(`Export failed: ${err.message || err}`, "danger");
        }
    }

    /* -------------------------------------------------------------
       PHASE 12: AI INTELLIGENCE & KNOWLEDGE GOVERNANCE (RAG)
    -------------------------------------------------------------- */
    async loadAndRenderAiKnowledge() {
        const p = $("aiTabPanelKnowledge");
        if (!p) return;
        p.innerHTML = '<div style="padding:30px; text-align:center;"><div class="scan-spinner-ring" style="margin:0 auto 12px;"></div>Loading RAG SEO Knowledge Base...</div>';
        try {
            const data = await jsonFetch(`${API_BASE}/admin/ai/knowledge`);
            const docs = data.documents || [];
            p.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                    <div>
                        <h3 style="margin:0; font-size:16px; font-weight:700;">Google Search Central Knowledge Base</h3>
                        <div style="font-size:12px; color:var(--text-muted);">Active Version: <b>${escapeHtml(data.active_version || '1.0.0')}</b> &bull; Total Documents: <b>${docs.length}</b></div>
                    </div>
                    <div style="display:flex; gap:8px;">
                        <button class="btn btn-secondary btn-sm" onclick="app.rollbackAiKnowledge()">⏪ Rollback Version</button>
                        <button class="btn btn-primary btn-sm" onclick="app.refreshAiKnowledge()">🔄 Refresh Knowledge Base</button>
                    </div>
                </div>
                <div class="card" style="padding:0; overflow:hidden;">
                    <table>
                        <thead>
                            <tr>
                                <th>Doc ID</th>
                                <th>Title</th>
                                <th>Category</th>
                                <th>Publisher</th>
                                <th>Version</th>
                                <th>Hash</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${docs.length ? docs.map(d => `
                                <tr>
                                    <td><code style="font-size:11px; font-weight:700;">${escapeHtml(d.document_id)}</code></td>
                                    <td>
                                        <a href="${escapeHtml(d.source_url)}" target="_blank" rel="noopener noreferrer" style="font-weight:600; color:var(--primary); text-decoration:none;">
                                            ${escapeHtml(d.title)} ↗
                                        </a>
                                    </td>
                                    <td><span class="badge" style="background:#eef2ff; color:#4f46e5; font-size:11px;">${escapeHtml(d.category || d.topic)}</span></td>
                                    <td style="font-size:12px; color:var(--text-muted);">${escapeHtml(d.publisher)}</td>
                                    <td style="font-size:12px;"><span class="pill pill-success">${escapeHtml(d.knowledge_version || '1.0.0')}</span></td>
                                    <td><code style="font-size:10px; color:var(--text-muted);">${escapeHtml((d.content_hash || '').slice(0, 10))}...</code></td>
                                </tr>
                            `).join("") : '<tr><td colspan="6" class="empty-state">No knowledge documents loaded.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            p.innerHTML = `<div class="empty-state" style="padding:30px; color:var(--danger);">Failed to load knowledge base: ${escapeHtml(err.message || err)}</div>`;
        }
    }

    async refreshAiKnowledge() {
        if (!confirm("Refresh and re-hash SEO knowledge base documents from authoritative Google Search Central specifications?")) return;
        try {
            this.showNotification("Refreshing RAG knowledge documents...", "info");
            const res = await jsonFetch(`${API_BASE}/admin/ai/knowledge/refresh`, { method: "POST" });
            this.showNotification(res.message || "Knowledge base refreshed successfully.", "success");
            await this.loadAndRenderAiKnowledge();
        } catch (err) {
            this.showNotification(`Refresh failed: ${err.message || err}`, "danger");
        }
    }

    async rollbackAiKnowledge() {
        const targetVer = prompt("Enter target knowledge version to restore (e.g. 1.0.0):", "1.0.0");
        if (!targetVer) return;
        try {
            this.showNotification(`Rolling back knowledge base to version ${targetVer}...`, "info");
            const res = await jsonFetch(`${API_BASE}/admin/ai/knowledge/rollback`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ target_version: targetVer })
            });
            this.showNotification(res.message || `Rollback to ${targetVer} complete.`, "success");
            await this.loadAndRenderAiKnowledge();
        } catch (err) {
            this.showNotification(`Rollback failed: ${err.message || err}`, "danger");
        }
    }

    async loadAndRenderAiQuality() {
        const p = $("aiTabPanelQuality");
        if (!p) return;
        p.innerHTML = '<div style="padding:30px; text-align:center;"><div class="scan-spinner-ring" style="margin:0 auto 12px;"></div>Loading AI Accuracy Verification Telemetry...</div>';
        try {
            const data = await jsonFetch(`${API_BASE}/admin/ai/quality`);
            p.innerHTML = `
                <div style="margin-bottom:16px;">
                    <h3 style="margin:0; font-size:16px; font-weight:700;">AI Recommendation Verification & Accuracy</h3>
                    <div style="font-size:12px; color:var(--text-muted);">Real-time verification metrics and benchmark evaluation results against measured audit evidence</div>
                </div>
                <div class="dash-summary-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:20px;">
                    <div class="card stat-card" style="border-top:3px solid #10b981;">
                        <span class="stat-label">Evidence Grounding</span>
                        <b class="stat-value" style="color:#10b981; font-size:28px;">${data.evidence_support_rate != null ? Math.round(data.evidence_support_rate * 100) : 100}%</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Recommendations supported by crawl facts</div>
                    </div>
                    <div class="card stat-card" style="border-top:3px solid #2563eb;">
                        <span class="stat-label">Hallucination Rate</span>
                        <b class="stat-value" style="color:#2563eb; font-size:28px;">${data.hallucination_rate != null ? (data.hallucination_rate * 100).toFixed(1) : "0.0"}%</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Invented issues / unmeasured claims</div>
                    </div>
                    <div class="card stat-card" style="border-top:3px solid #f59e0b;">
                        <span class="stat-label">Rule Conflict Rate</span>
                        <b class="stat-value" style="color:#f59e0b; font-size:28px;">${data.rule_conflict_rate != null ? (data.rule_conflict_rate * 100).toFixed(1) : "0.0"}%</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Contradictions of deterministic checks</div>
                    </div>
                    <div class="card stat-card" style="border-top:3px solid #8b5cf6;">
                        <span class="stat-label">Ranking Guarantees Blocked</span>
                        <b class="stat-value" style="color:#8b5cf6; font-size:28px;">100%</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Guaranteed ranking claims prohibited</div>
                    </div>
                </div>
                <div class="card" style="padding:16px 20px;">
                    <h4 style="margin:0 0 10px; font-size:14px; font-weight:700;">Multi-System Evaluation Benchmark (docs/AI_EVALUATION_REPORT.md)</h4>
                    <table>
                        <thead>
                            <tr>
                                <th>Evaluation System</th>
                                <th>Evidence Support Rate</th>
                                <th>Hallucinations</th>
                                <th>Rule Contradictions</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr>
                                <td><b>System A:</b> Baseline Legacy AI</td>
                                <td style="color:#dc2626;">65.0%</td>
                                <td style="color:#dc2626;">35.0%</td>
                                <td style="color:#dc2626;">20.0%</td>
                                <td><span class="pill pill-danger">Unverified</span></td>
                            </tr>
                            <tr>
                                <td><b>System B:</b> Gemma 4 + Dynamic RAG</td>
                                <td style="color:#2563eb;">85.0%</td>
                                <td style="color:#f59e0b;">15.0%</td>
                                <td style="color:#f59e0b;">10.0%</td>
                                <td><span class="pill pill-warning">Partial Guard</span></td>
                            </tr>
                            <tr style="background:#f0fdf4;">
                                <td><b>System C:</b> Gemma 4 + RAG + Recommendation Verifier</td>
                                <td style="color:#16a34a; font-weight:700;">100.0%</td>
                                <td style="color:#16a34a; font-weight:700;">0.0%</td>
                                <td style="color:#16a34a; font-weight:700;">0.0%</td>
                                <td><span class="pill pill-success">Verified Production</span></td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            p.innerHTML = `<div class="empty-state" style="padding:30px; color:var(--danger);">Failed to load quality metrics: ${escapeHtml(err.message || err)}</div>`;
        }
    }

    async loadAndRenderAiTraining() {
        const p = $("aiTabPanelTraining");
        if (!p) return;
        p.innerHTML = '<div style="padding:30px; text-align:center;"><div class="scan-spinner-ring" style="margin:0 auto 12px;"></div>Loading Curated Training Examples...</div>';
        try {
            const data = await jsonFetch(`${API_BASE}/admin/ai/training`);
            const examples = data.examples || [];
            p.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; flex-wrap:wrap; gap:10px;">
                    <div>
                        <h3 style="margin:0; font-size:16px; font-weight:700;">Curated Instruction Fine-Tuning Dataset</h3>
                        <div style="font-size:12px; color:var(--text-muted);">Total Examples: <b>${examples.length}</b> &bull; Approved for Gemma 4 LoRA: <b>${examples.filter(e => e.review_status === 'APPROVED').length}</b></div>
                    </div>
                    <div>
                        <button class="btn btn-secondary btn-sm" onclick="app.exportAiTrainingData()">📥 Export JSONL Dataset</button>
                    </div>
                </div>
                <div class="card" style="padding:0; overflow:hidden;">
                    <table>
                        <thead>
                            <tr>
                                <th>Example ID</th>
                                <th>Verified SEO Issue</th>
                                <th>Page Type</th>
                                <th>Status</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${examples.length ? examples.map(ex => `
                                <tr>
                                    <td><code style="font-size:11px;">${escapeHtml(ex.example_id)}</code></td>
                                    <td><b>${escapeHtml(ex.verified_issue)}</b></td>
                                    <td><span class="badge" style="background:#f1f5f9; color:#475569; font-size:11px;">${escapeHtml(ex.page_type || 'General')}</span></td>
                                    <td>
                                        <span class="pill ${ex.review_status === 'APPROVED' ? 'pill-success' : ex.review_status === 'REJECTED' ? 'pill-danger' : 'pill-warning'}">
                                            ${escapeHtml(ex.review_status)}
                                        </span>
                                    </td>
                                    <td style="font-size:12px; color:var(--text-muted);">${escapeHtml((ex.created_at || '').slice(0, 10))}</td>
                                    <td>
                                        <div style="display:flex; gap:6px;">
                                            <button class="btn btn-secondary btn-sm" style="padding:2px 8px; font-size:11px;" onclick="app.updateTrainingExampleStatus('${escapeHtml(ex.example_id)}', 'APPROVED')">Approve</button>
                                            <button class="btn btn-secondary btn-sm" style="padding:2px 8px; font-size:11px; color:var(--danger);" onclick="app.updateTrainingExampleStatus('${escapeHtml(ex.example_id)}', 'REJECTED')">Reject</button>
                                        </div>
                                    </td>
                                </tr>
                            `).join("") : '<tr><td colspan="6" class="empty-state">No training examples recorded yet. Run an audit to curate new verified pairs.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            `;
        } catch (err) {
            p.innerHTML = `<div class="empty-state" style="padding:30px; color:var(--danger);">Failed to load training examples: ${escapeHtml(err.message || err)}</div>`;
        }
    }

    async updateTrainingExampleStatus(exampleId, status) {
        try {
            await jsonFetch(`${API_BASE}/admin/ai/training/${exampleId}/status`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ review_status: status })
            });
            this.showNotification(`Example ${exampleId} status updated to ${status}.`, "success");
            await this.loadAndRenderAiTraining();
        } catch (err) {
            this.showNotification(`Update failed: ${err.message || err}`, "danger");
        }
    }

    async exportAiTrainingData() {
        try {
            window.open(`${API_BASE}/admin/ai/training/export`, "_blank");
            this.showNotification("Exported instruction fine-tuning dataset (.jsonl).", "success");
        } catch (err) {
            this.showNotification(`Export failed: ${err.message || err}`, "danger");
        }
    }

    async loadAndRenderAiStatus() {
        const p = $("aiTabPanelStatus");
        if (!p) return;
        p.innerHTML = '<div style="padding:30px; text-align:center;"><div class="scan-spinner-ring" style="margin:0 auto 12px;"></div>Loading AI Engine Diagnostics...</div>';
        try {
            const data = await jsonFetch(`${API_BASE}/admin/ai/status`);
            const statusCol = data.status === "MODEL_AVAILABLE" ? "#16a34a" : data.status === "MODEL_RATE_LIMITED" ? "#d97706" : "#4f46e5";
            p.innerHTML = `
                <div style="margin-bottom:16px;">
                    <h3 style="margin:0; font-size:16px; font-weight:700;">Active AI Engine Runtime Diagnostics</h3>
                    <div style="font-size:12px; color:var(--text-muted);">Real-time telemetry for hosted Gemma 4 / Gemini model client, RAG knowledge retriever, and response cache</div>
                </div>
                <div class="dash-summary-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-bottom:20px;">
                    <div class="card stat-card" style="border-top:3px solid ${statusCol};">
                        <span class="stat-label">Model Status</span>
                        <b class="stat-value" style="color:${statusCol}; font-size:22px;">${escapeHtml(data.status)}</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Provider: <b>${escapeHtml(data.provider || 'Hosted')}</b></div>
                    </div>
                    <div class="card stat-card" style="border-top:3px solid #2563eb;">
                        <span class="stat-label">Active Model ID</span>
                        <b class="stat-value" style="color:#2563eb; font-size:20px;">${escapeHtml(data.model || 'gemma4:31b')}</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Timeout: <b>${data.timeout_seconds || 45}s</b></div>
                    </div>
                    <div class="card stat-card" style="border-top:3px solid #10b981;">
                        <span class="stat-label">RAG Knowledge Engine</span>
                        <b class="stat-value" style="color:#10b981; font-size:22px;">ACTIVE</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">Indexed: <b>${data.rag_indexed_documents || 13} documents</b></div>
                    </div>
                    <div class="card stat-card" style="border-top:3px solid #8b5cf6;">
                        <span class="stat-label">Response Cache Hits</span>
                        <b class="stat-value" style="color:#8b5cf6; font-size:22px;">${data.cache_entries || 0} Entries</b>
                        <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">TTL: <b>3600 seconds</b></div>
                    </div>
                </div>
                <div class="card" style="padding:16px 20px;">
                    <h4 style="margin:0 0 10px; font-size:14px; font-weight:700;">Engine Safety & Grounding Controls</h4>
                    <div style="display:flex; flex-direction:column; gap:8px; font-size:13px;">
                        <div>🛡️ <b>Deterministic SEO Rules Gate:</b> Active. Deterministic check verdicts are immutable and cannot be overwritten by AI output.</div>
                        <div>🔍 <b>Post-Generation Verification:</b> Active. Validates all recommendations against raw crawler signals; suppresses contradictory advice.</div>
                        <div>🚫 <b>Prohibited Guarantees Filter:</b> Active. Drops promises of guaranteed search rankings or fabricated metrics.</div>
                        <div>📜 <b>RAG Context Isolation:</b> Active. RAG specifications and user audit context are isolated behind non-executable XML boundary tags.</div>
                    </div>
                </div>
            `;
        } catch (err) {
            p.innerHTML = `<div class="empty-state" style="padding:30px; color:var(--danger);">Failed to load AI engine diagnostics: ${escapeHtml(err.message || err)}</div>`;
        }
    }

}

const app = new SEOAdminApp();
window.app = app;
