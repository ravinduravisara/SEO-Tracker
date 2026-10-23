/**
 * eSupport SEO • Website Technology Detector Frontend Engine
 * Connects to the real scanner backend API and manages the UI state machine.
 */

(function () {
    class WebsiteTechDetector {
        constructor() {
            this.state = {
                currentScan: null,
                isScanning: false,
                currentTab: "detected", // "detected" | "all"
                catalog: [],
                history: [],
                filterQuery: ""
            };
            this.container = null;
        }

        initView() {
            this.container = document.getElementById("viewTechDetector");
            if (!this.container) return;

            // Render view skeleton if not already rendered
            if (!document.getElementById("tdRoot")) {
                this.renderSkeleton();
            }
            this.bindEvents();

            // Load recent history in background safely
            try {
                this.loadHistory();
            } catch (err) {
                console.warn("[TechDetector] Failed to load initial history:", err);
            }
        }

        renderSkeleton() {
            this.container.innerHTML = `
                <div class="tech-detector-container" id="tdRoot">
                    <!-- HEADER -->
                    <div class="td-header">
                        <div>
                            <h2 class="td-header-title">
                                <span>🔍</span> Website Technology Detector
                            </h2>
                            <p class="td-header-desc">
                                Analyze a website URL to identify its CMS, website platform, frontend frameworks, backend indicators, and other detectable technologies.
                            </p>
                        </div>
                        <div>
                            <span class="td-admin-badge">🛡️ Administrator Only</span>
                        </div>
                    </div>

                    <!-- SCAN FORM -->
                    <div class="td-scan-card">
                        <form id="tdScanForm" onsubmit="window.techDetector.handleScanSubmit(event)">
                            <div class="td-input-group">
                                <div class="td-input-wrapper">
                                    <span class="td-input-icon">🌐</span>
                                    <input 
                                        type="text" 
                                        id="tdUrlInput" 
                                        class="td-url-input" 
                                        placeholder="https://example.com" 
                                        autocomplete="off" 
                                        spellcheck="false"
                                        required
                                    />
                                    <button type="button" id="tdClearBtn" class="td-clear-btn" title="Clear input">&times;</button>
                                </div>
                                <button type="submit" id="tdScanBtn" class="td-btn-scan">
                                    <span>Scan Website</span>
                                    <span>➔</span>
                                </button>
                                <button type="button" id="tdCatalogBtn" class="td-btn-secondary" title="View all 96 cataloged technologies" onclick="window.techDetector.openCatalogModal()">
                                    <span>📚 96 Tech Catalog</span>
                                </button>
                            </div>
                        </form>
                        <div id="tdStatusLine" style="display:none;"></div>
                    </div>

                    <!-- RESULTS AREA (Hidden until scan completed) -->
                    <div id="tdResultsContainer" style="display:none;">
                        <!-- PRIMARY CLASSIFICATION HERO -->
                        <div class="td-primary-card" id="tdPrimaryCard">
                            <div class="td-primary-header">
                                <div>
                                    <div class="td-primary-category" id="tdPrimaryCategory">CMS Platforms</div>
                                    <h3 class="td-primary-title" id="tdPrimaryTitle">WordPress Detected</h3>
                                </div>
                                <div>
                                    <span class="td-pill td-pill-strong" id="tdPrimaryPill">Strong Evidence</span>
                                </div>
                            </div>
                            <div class="td-primary-summary" id="tdPrimarySummary">
                                The website displays confirmed signatures of WordPress.
                            </div>

                            <!-- CUSTOM-DEVELOPED WEBSITE ASSESSMENT CALLOUT -->
                            <div class="td-assessment-box">
                                <div class="td-assessment-label">Architecture Assessment</div>
                                <p class="td-assessment-text" id="tdAssessmentText">
                                    No recognized CMS signature was detected from the available evidence. This website may be custom-developed, use a headless or less common CMS, or conceal its technology indicators.
                                </p>
                            </div>

                            <!-- METADATA & SECURITY HEADERS GRID -->
                            <div class="td-meta-grid">
                                <div class="td-meta-item">
                                    <div class="td-meta-label">Submitted Target</div>
                                    <div class="td-meta-value" id="tdMetaSubmitted">-</div>
                                </div>
                                <div class="td-meta-item">
                                    <div class="td-meta-label">Final Destination URL</div>
                                    <div class="td-meta-value" id="tdMetaFinal">-</div>
                                </div>
                                <div class="td-meta-item">
                                    <div class="td-meta-label">HTTP Status</div>
                                    <div class="td-meta-value" id="tdMetaStatus">-</div>
                                </div>
                                <div class="td-meta-item">
                                    <div class="td-meta-label">Security &amp; SSL</div>
                                    <div class="td-meta-value" id="tdMetaHttps">-</div>
                                </div>
                                <div class="td-meta-item">
                                    <div class="td-meta-label">Scanned At</div>
                                    <div class="td-meta-value" id="tdMetaTimestamp">-</div>
                                </div>
                                <div class="td-meta-item">
                                    <div class="td-meta-label">Total Detected</div>
                                    <div class="td-meta-value" id="tdMetaCount">0 Technologies</div>
                                </div>
                            </div>
                        </div>

                        <!-- ACTION CONTROLS BAR -->
                        <div class="td-action-bar">
                            <button class="td-btn-secondary" onclick="window.techDetector.exportScan('json')">
                                <span>📥 Export Full JSON</span>
                            </button>
                            <button class="td-btn-secondary" onclick="window.techDetector.exportScan('csv')">
                                <span>📊 Export Findings CSV</span>
                            </button>
                            <button class="td-btn-secondary" onclick="window.techDetector.copySummary()">
                                <span id="tdCopyIcon">📋</span> <span id="tdCopyText">Copy Summary</span>
                            </button>
                            <button class="td-btn-secondary" onclick="window.techDetector.resetScan()">
                                <span>🔄 Scan Another Website</span>
                            </button>
                        </div>

                        <!-- SECTION HEADER & TABS -->
                        <div class="td-section-header">
                            <h4 class="td-section-title">
                                <span>🧩</span> Detected Technologies
                            </h4>
                            <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
                                <input 
                                    type="text" 
                                    id="tdFilterInput" 
                                    placeholder="Filter technologies..." 
                                    class="td-url-input" 
                                    style="padding:6px 12px; font-size:13px; width:200px;"
                                    oninput="window.techDetector.handleFilterChange(this.value)"
                                />
                                <div class="td-tabs">
                                    <button class="td-tab active" id="tdTabDetected" onclick="window.techDetector.switchTab('detected')">
                                        Detected Only (<span id="tdDetectedCountTab">0</span>)
                                    </button>
                                    <button class="td-tab" id="tdTabAll" onclick="window.techDetector.switchTab('all')">
                                        All 96 Catalog Entries
                                    </button>
                                </div>
                            </div>
                        </div>

                        <!-- FINDINGS LIST -->
                        <div class="td-findings-grid" id="tdFindingsGrid">
                            <!-- Injected dynamically -->
                        </div>

                        <!-- SECURITY HEADERS SUMMARY -->
                        <div style="margin-top:36px;">
                            <h4 class="td-section-title" style="margin-bottom:14px;">
                                <span>🛡️</span> Observed Security Headers
                            </h4>
                            <div class="td-security-grid" id="tdSecurityGrid">
                                <!-- Injected dynamically -->
                            </div>
                        </div>

                        <!-- SCAN LIMITATIONS DISCLAIMER -->
                        <div style="margin-top:36px; padding:18px 22px; background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px;">
                            <div style="font-weight:800; font-size:13px; color:#475569; text-transform:uppercase; margin-bottom:8px;">
                                Diagnostic Limitations &amp; Uncertainty Disclosures
                            </div>
                            <ul id="tdLimitationsList" style="margin:0; padding-left:20px; font-size:12px; color:#64748B; line-height:1.6;">
                                <!-- Injected dynamically -->
                            </ul>
                        </div>
                    </div>

                    <!-- RECENT HISTORY PANEL -->
                    <div class="td-history-card" id="tdHistoryCard">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <h4 class="td-section-title">
                                <span>📜</span> Recent Scans History (Current Administrator)
                            </h4>
                            <button class="td-btn-secondary" style="padding:6px 12px; font-size:12px;" onclick="window.techDetector.loadHistory()">
                                Refresh History
                            </button>
                        </div>
                        <div id="tdHistoryBody" style="margin-top:12px;">
                            <div style="color:var(--text-muted); font-size:13px;">No scans recorded in this session.</div>
                        </div>
                    </div>
                </div>

                <!-- 96 TECH CATALOG MODAL -->
                <div id="tdCatalogModal" class="td-catalog-modal" style="display:none;">
                    <div class="td-catalog-box">
                        <div class="td-catalog-header">
                            <div>
                                <h3 style="margin:0; font-size:18px; font-weight:800;">Technology Detection Catalog (96 Entries)</h3>
                                <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">
                                    Comprehensive detection signatures covering CMS platforms, builders, frameworks, and web architectures.
                                </div>
                            </div>
                            <button class="modal-close" onclick="window.techDetector.closeCatalogModal()">&times;</button>
                        </div>
                        <div style="padding:12px 24px; border-bottom:1px solid var(--border); background:#F8FAFC;">
                            <input 
                                type="text" 
                                id="tdCatalogSearch" 
                                class="td-url-input" 
                                placeholder="Search all 96 technologies or categories..." 
                                style="padding:8px 14px; font-size:13px;"
                                oninput="window.techDetector.filterCatalog(this.value)"
                            />
                        </div>
                        <div class="td-catalog-body" id="tdCatalogBody">
                            <div style="text-align:center; padding:30px; color:var(--text-muted);">Loading catalog...</div>
                        </div>
                    </div>
                </div>
            `;
        }

        bindEvents() {
            const input = document.getElementById("tdUrlInput");
            const clearBtn = document.getElementById("tdClearBtn");
            if (input && clearBtn) {
                input.addEventListener("input", () => {
                    clearBtn.style.display = input.value.trim() ? "block" : "none";
                });
                clearBtn.addEventListener("click", () => {
                    input.value = "";
                    clearBtn.style.display = "none";
                    input.focus();
                });
            }
        }

        setStatus(msg, type = "loading") {
            const el = document.getElementById("tdStatusLine");
            if (!el) return;
            if (!msg) {
                el.style.display = "none";
                el.innerHTML = "";
                return;
            }
            el.style.display = "flex";
            el.className = `td-status-box ${type}`;
            if (type === "loading") {
                el.innerHTML = `<span class="td-spinner"></span> <span>${this.escape(msg)}</span>`;
            } else if (type === "error") {
                el.innerHTML = `<span>⚠️</span> <span>${this.escape(msg)}</span>`;
            } else {
                el.innerHTML = `<span>ℹ️</span> <span>${this.escape(msg)}</span>`;
            }
        }

        async handleScanSubmit(e) {
            if (e) e.preventDefault();
            if (this.state.isScanning) return;

            const input = document.getElementById("tdUrlInput");
            let rawUrl = (input ? input.value : "").trim();

            if (!rawUrl) {
                this.setStatus("Please enter a website URL to scan.", "error");
                return;
            }

            // Client URL syntax check
            if (!rawUrl.startsWith("http://") && !rawUrl.startsWith("https://")) {
                rawUrl = "https://" + rawUrl;
                input.value = rawUrl;
            }

            // Check if local or private host
            try {
                const parsed = new URL(rawUrl);
                const host = parsed.hostname.toLowerCase();
                if (host === "localhost" || host.startsWith("127.") || host === "::1" || host === "169.254.169.254") {
                    this.setStatus("Scanning localhost or private IP addresses is blocked by SSRF defense.", "error");
                    return;
                }
            } catch (err) {
                this.setStatus("Invalid URL format. Please enter a valid HTTP or HTTPS address.", "error");
                return;
            }

            this.state.isScanning = true;
            const scanBtn = document.getElementById("tdScanBtn");
            if (scanBtn) {
                scanBtn.disabled = true;
                scanBtn.innerHTML = `<span class="td-spinner"></span> <span>Scanning...</span>`;
            }

            this.setStatus("Validating URL and inspecting public response...", "loading");

            try {
                // Call real admin endpoint
                const resp = await jsonFetch("/api/admin/technology-detector/scan", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ url: rawUrl })
                });

                this.state.currentScan = resp;
                this.setStatus("", "");
                this.renderResults(resp);
                this.loadHistory(); // refresh history table
            } catch (err) {
                const msg = err.message || "Failed to inspect the website. Target may be offline, timing out, or blocked.";
                this.setStatus(msg, "error");
            } finally {
                this.state.isScanning = false;
                if (scanBtn) {
                    scanBtn.disabled = false;
                    scanBtn.innerHTML = `<span>Scan Website</span> <span>➔</span>`;
                }
            }
        }

        renderResults(scan) {
            const container = document.getElementById("tdResultsContainer");
            if (!container) return;
            container.style.display = "block";

            // 1. Primary Card
            const catEl = document.getElementById("tdPrimaryCategory");
            const titleEl = document.getElementById("tdPrimaryTitle");
            const pillEl = document.getElementById("tdPrimaryPill");
            const sumEl = document.getElementById("tdPrimarySummary");
            const assessEl = document.getElementById("tdAssessmentText");

            if (catEl) catEl.textContent = scan.primary_category || "Technology Assessment";
            if (titleEl) titleEl.textContent = scan.primary_classification || "Analysis Completed";
            if (sumEl) sumEl.textContent = scan.primary_summary || "";
            if (assessEl) assessEl.textContent = scan.custom_website_assessment || "";

            if (pillEl) {
                if (scan.is_inconclusive) {
                    pillEl.className = "td-pill td-pill-inconclusive";
                    pillEl.textContent = "Inconclusive";
                } else if (scan.primary_classification.includes("WordPress") || scan.primary_classification.includes("Detected")) {
                    pillEl.className = "td-pill td-pill-strong";
                    pillEl.textContent = "Strong Evidence";
                } else {
                    pillEl.className = "td-pill td-pill-possible";
                    pillEl.textContent = "Evidence Observed";
                }
            }

            // 2. Metadata Grid
            const submittedEl = document.getElementById("tdMetaSubmitted");
            const finalEl = document.getElementById("tdMetaFinal");
            const statusEl = document.getElementById("tdMetaStatus");
            const httpsEl = document.getElementById("tdMetaHttps");
            const timeEl = document.getElementById("tdMetaTimestamp");
            const countEl = document.getElementById("tdMetaCount");

            if (submittedEl) submittedEl.textContent = scan.submitted_url;
            if (finalEl) finalEl.textContent = scan.final_url;
            if (statusEl) {
                const code = scan.http_status;
                const color = code >= 200 && code < 300 ? "#059669" : (code >= 300 && code < 400 ? "#D97706" : "#DC2626");
                statusEl.innerHTML = `<span style="color:${color};">●</span> ${code}`;
            }
            if (httpsEl) {
                httpsEl.innerHTML = scan.is_https 
                    ? `<span style="color:#059669;">🔒 HTTPS Active</span>`
                    : `<span style="color:#DC2626;">⚠️ Insecure HTTP</span>`;
            }
            if (timeEl) {
                const date = new Date(scan.scanned_at);
                timeEl.textContent = isNaN(date.getTime()) ? scan.scanned_at : date.toLocaleString();
            }
            if (countEl) countEl.textContent = `${scan.total_detected_count} of 96 Catalog Technologies`;

            const detTabCount = document.getElementById("tdDetectedCountTab");
            if (detTabCount) detTabCount.textContent = scan.total_detected_count;

            // 3. Render Findings
            this.renderFindingsList();

            // 4. Render Security Headers
            const secGrid = document.getElementById("tdSecurityGrid");
            if (secGrid) {
                secGrid.innerHTML = (scan.security_headers || []).map(sh => `
                    <div class="td-sec-card">
                        <div>
                            <div class="td-sec-name">${this.escape(sh.name)}</div>
                            <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">
                                ${sh.present ? (this.escape(sh.value || "Configured")) : "Missing / Not Sent"}
                            </div>
                        </div>
                        <div>
                            ${sh.present 
                                ? `<span class="td-pill td-pill-strong" style="padding:2px 8px; font-size:10px;">Enforced</span>`
                                : `<span class="td-pill td-pill-not-detected" style="padding:2px 8px; font-size:10px;">Absent</span>`}
                        </div>
                    </div>
                `).join("");
            }

            // 5. Render Limitations
            const limList = document.getElementById("tdLimitationsList");
            if (limList) {
                limList.innerHTML = (scan.scan_limitations || []).map(lim => `<li>${this.escape(lim)}</li>`).join("");
            }

            // Scroll smoothly to results
            const primaryCard = document.getElementById("tdPrimaryCard");
            if (primaryCard) {
                primaryCard.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }

        switchTab(tab) {
            this.state.currentTab = tab;
            const detTab = document.getElementById("tdTabDetected");
            const allTab = document.getElementById("tdTabAll");
            if (detTab) detTab.classList.toggle("active", tab === "detected");
            if (allTab) allTab.classList.toggle("active", tab === "all");
            this.renderFindingsList();
        }

        handleFilterChange(q) {
            this.state.filterQuery = (q || "").trim().toLowerCase();
            this.renderFindingsList();
        }

        renderFindingsList() {
            const grid = document.getElementById("tdFindingsGrid");
            if (!grid || !this.state.currentScan) return;

            const scan = this.state.currentScan;
            let list = this.state.currentTab === "detected" 
                ? (scan.detected_technologies || []) 
                : (scan.all_catalog_results || []);

            // Apply text filter if any
            if (this.state.filterQuery) {
                const q = this.state.filterQuery;
                list = list.filter(t => 
                    (t.name || "").toLowerCase().includes(q) ||
                    (t.category || "").toLowerCase().includes(q) ||
                    (t.description || "").toLowerCase().includes(q)
                );
            }

            if (list.length === 0) {
                grid.innerHTML = `
                    <div style="padding:32px; text-align:center; background:#F8FAFC; border:1px solid #E2E8F0; border-radius:12px; color:var(--text-muted);">
                        No technologies matched your current filter criteria.
                    </div>
                `;
                return;
            }

            grid.innerHTML = list.map((tech, idx) => {
                const status = tech.detection_status || "Not Detected";
                let pillClass = "td-pill-not-detected";
                if (status === "Strong Evidence") pillClass = "td-pill-strong";
                else if (status === "Possible") pillClass = "td-pill-possible";
                else if (status === "Inconclusive") pillClass = "td-pill-inconclusive";

                const hasEvidence = Array.isArray(tech.evidence) && tech.evidence.length > 0;
                const panelId = `tdEvPanel_${idx}`;

                return `
                    <div class="td-card">
                        <div class="td-card-top">
                            <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
                                <h4 class="td-tech-name">
                                    ${this.escape(tech.name)}
                                    ${tech.version ? `<span class="td-version-tag">v${this.escape(tech.version)}</span>` : ""}
                                </h4>
                                <span class="td-category-tag">• ${this.escape(tech.category)}</span>
                            </div>
                            <div>
                                <span class="td-pill ${pillClass}">${status}</span>
                            </div>
                        </div>

                        <p class="td-tech-desc">${this.escape(tech.description)}</p>

                        ${hasEvidence ? `
                            <button type="button" class="td-evidence-toggle" onclick="window.techDetector.toggleEvidence('${panelId}')">
                                <span>🔍 View Supporting Evidence (${tech.evidence.length})</span>
                                <span>▾</span>
                            </button>
                            <div id="${panelId}" class="td-evidence-panel">
                                <div style="font-weight:700; font-size:12px; margin-bottom:8px; color:#1E293B;">
                                    Observed Facts vs. Technical Inferences:
                                </div>
                                ${tech.evidence.map(ev => `
                                    <div class="td-evidence-item">
                                        <div class="td-evidence-source">
                                            <span>📌 ${this.escape(ev.source)}</span>
                                            <span class="td-pill ${ev.confidence === 'Strong Evidence' ? 'td-pill-strong' : 'td-pill-possible'}" style="padding:1px 6px; font-size:9px;">
                                                ${ev.confidence}
                                            </span>
                                        </div>
                                        <div class="td-evidence-fact">${this.escape(ev.observed_fact)}</div>
                                        <div class="td-evidence-inference"><b>Inference:</b> ${this.escape(ev.inference)}</div>
                                    </div>
                                `).join("")}
                                <div class="td-limitations-note">
                                    <b>Detection limitation:</b> ${this.escape(tech.limitations)}
                                </div>
                            </div>
                        ` : `
                            <div class="td-limitations-note">
                                <b>Status explanation:</b> ${this.escape(tech.explanation)}
                                <br><b>Known limitation:</b> ${this.escape(tech.limitations)}
                            </div>
                        `}
                    </div>
                `;
            }).join("");
        }

        toggleEvidence(panelId) {
            const el = document.getElementById(panelId);
            if (el) {
                el.classList.toggle("open");
            }
        }

        resetScan() {
            const input = document.getElementById("tdUrlInput");
            if (input) {
                input.value = "";
                input.focus();
            }
            const results = document.getElementById("tdResultsContainer");
            if (results) results.style.display = "none";
            this.setStatus("", "");
        }

        copySummary() {
            if (!this.state.currentScan) return;
            const scan = this.state.currentScan;
            const detectedNames = (scan.detected_technologies || []).map(t => `${t.name} (${t.category})`).join(", ");
            const text = [
                `Website Technology Report: ${scan.submitted_url}`,
                `Primary Finding: ${scan.primary_classification}`,
                `Assessment: ${scan.custom_website_assessment}`,
                `Detected Technologies (${scan.total_detected_count}): ${detectedNames || 'None confirmed'}`,
                `Destination: ${scan.final_url} (HTTP ${scan.http_status})`,
                `Scanned At: ${scan.scanned_at}`
            ].join("\n");

            navigator.clipboard.writeText(text).then(() => {
                const icon = document.getElementById("tdCopyIcon");
                const label = document.getElementById("tdCopyText");
                if (icon && label) {
                    icon.textContent = "✓";
                    label.textContent = "Summary Copied!";
                    setTimeout(() => {
                        icon.textContent = "📋";
                        label.textContent = "Copy Summary";
                    }, 2500);
                }
            }).catch(() => {
                alert("Copied text to clipboard:\n\n" + text);
            });
        }

        async exportScan(format) {
            if (!this.state.currentScan) return;
            const scanId = this.state.currentScan.scan_id;
            try {
                const response = await fetch("/api/admin/technology-detector/export", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {})
                    },
                    body: JSON.stringify({ scan_id: scanId, export_format: format })
                });
                if (!response.ok) {
                    throw new Error("Export failed");
                }
                const blob = await response.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = downloadUrl;
                a.download = format === "json" ? `tech-scan-${scanId.slice(0, 8)}.json` : `tech-scan-${scanId.slice(0, 8)}.csv`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(downloadUrl);
            } catch (err) {
                alert("Failed to export: " + err.message);
            }
        }

        async loadHistory() {
            const body = document.getElementById("tdHistoryBody");
            if (!body) return;
            try {
                const history = await jsonFetch("/api/admin/technology-detector/history");
                this.state.history = history || [];
                if (history.length === 0) {
                    body.innerHTML = `<div style="color:var(--text-muted); font-size:13px; padding:12px 0;">No previous scans recorded for this administrator account.</div>`;
                    return;
                }

                body.innerHTML = `
                    <table class="td-history-table">
                        <thead>
                            <tr>
                                <th>Target Website</th>
                                <th>Primary Finding</th>
                                <th>Detected</th>
                                <th>Date &amp; Time</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${history.map(item => `
                                <tr>
                                    <td>
                                        <b style="color:var(--primary);">${this.escape(item.submitted_url)}</b>
                                        ${item.final_url !== item.submitted_url ? `<div style="font-size:11px; color:var(--text-muted);">↳ ${this.escape(item.final_url)}</div>` : ''}
                                    </td>
                                    <td>
                                        <span class="td-pill ${item.primary_classification.includes('WordPress') || item.primary_classification.includes('Detected') ? 'td-pill-strong' : 'td-pill-possible'}" style="padding:2px 8px; font-size:11px;">
                                            ${this.escape(item.primary_classification)}
                                        </span>
                                    </td>
                                    <td>
                                        <b>${item.detected_count}</b>
                                        <div style="font-size:11px; color:var(--text-muted);">${this.escape((item.top_technologies || []).join(", "))}</div>
                                    </td>
                                    <td style="font-size:12px; color:var(--text-muted);">
                                        ${new Date(item.scanned_at).toLocaleString()}
                                    </td>
                                    <td>
                                        <button class="td-btn-secondary" style="padding:4px 10px; font-size:11px;" onclick="window.techDetector.loadPastScan('${item.scan_id}')">
                                            View Report
                                        </button>
                                    </td>
                                </tr>
                            `).join("")}
                        </tbody>
                    </table>
                `;
            } catch (err) {
                console.warn("Could not load scan history:", err);
            }
        }

        async loadPastScan(scanId) {
            try {
                this.setStatus("Loading past scan results...", "loading");
                const scan = await jsonFetch(`/api/admin/technology-detector/scan/${scanId}`);
                this.state.currentScan = scan;
                this.setStatus("", "");
                const input = document.getElementById("tdUrlInput");
                if (input) input.value = scan.submitted_url;
                this.renderResults(scan);
            } catch (err) {
                this.setStatus("Failed to load past scan: " + err.message, "error");
            }
        }

        async openCatalogModal() {
            const modal = document.getElementById("tdCatalogModal");
            if (!modal) return;
            modal.style.display = "flex";

            if (this.state.catalog.length === 0) {
                try {
                    const data = await jsonFetch("/api/admin/technology-detector/catalog");
                    this.state.catalog = data.catalog || [];
                } catch (err) {
                    console.error("Failed to load catalog:", err);
                }
            }
            this.renderCatalogModal(this.state.catalog);
        }

        closeCatalogModal() {
            const modal = document.getElementById("tdCatalogModal");
            if (modal) modal.style.display = "none";
        }

        filterCatalog(q) {
            const query = (q || "").toLowerCase().trim();
            if (!query) {
                this.renderCatalogModal(this.state.catalog);
                return;
            }
            const filtered = this.state.catalog.filter(e => 
                (e.name || "").toLowerCase().includes(query) ||
                (e.category_name || "").toLowerCase().includes(query) ||
                (e.description || "").toLowerCase().includes(query)
            );
            this.renderCatalogModal(filtered);
        }

        renderCatalogModal(entries) {
            const body = document.getElementById("tdCatalogBody");
            if (!body) return;

            // Group by category
            const grouped = {};
            entries.forEach(e => {
                if (!grouped[e.category_name]) grouped[e.category_name] = [];
                grouped[e.category_name].push(e);
            });

            const catNames = Object.keys(grouped);
            if (catNames.length === 0) {
                body.innerHTML = `<div style="text-align:center; padding:30px; color:var(--text-muted);">No catalog entries match your search.</div>`;
                return;
            }

            body.innerHTML = catNames.map(cat => `
                <div style="margin-bottom:24px;">
                    <div style="font-weight:800; font-size:14px; color:#1E293B; margin-bottom:10px; border-bottom:1px solid #E2E8F0; padding-bottom:4px; display:flex; justify-content:space-between;">
                        <span>${this.escape(cat)}</span>
                        <span style="font-size:12px; color:var(--text-muted);">${grouped[cat].length} entries</span>
                    </div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:10px;">
                        ${grouped[cat].map(item => `
                            <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:10px 12px; font-size:12px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                                    <b style="color:#0F172A;">${this.escape(item.name)}</b>
                                    <span style="font-size:10px; padding:2px 6px; border-radius:4px; background:${item.is_reliably_detectable ? '#ECFDF5; color:#065F46;' : '#FFFBEB; color:#92400E;'}">
                                        ${item.is_reliably_detectable ? 'Public Signatures' : 'Often Concealed'}
                                    </span>
                                </div>
                                <div style="color:#64748B; font-size:11px; line-height:1.4;">${this.escape(item.description)}</div>
                            </div>
                        `).join("")}
                    </div>
                </div>
            `).join("");
        }

        escape(s) {
            return String(s ?? "").replace(/[&<>"']/g, m => ({
                "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
            }[m]));
        }
    }

    // Export singleton
    window.techDetector = new WebsiteTechDetector();

    // Auto-bind immediately if DOM elements exist
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            window.techDetector.bindEvents();
            if (window.app && window.app.state && window.app.state.currentView === "technology_detector") {
                window.techDetector.initView();
            }
        });
    } else {
        window.techDetector.bindEvents();
        if (window.app && window.app.state && window.app.state.currentView === "technology_detector") {
            window.techDetector.initView();
        }
    }
})();
