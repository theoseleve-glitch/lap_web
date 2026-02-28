# Feature Inventory

Comprehensive testable feature inventory for the Lap Coach Racing telemetry SaaS platform.
Generated as part of the E2E certification harness (Task 12).

**Total items:** 306
**Status:** All items start as `pending`.

| ID | Area | Feature | Tier | Test Method | Parity Ref | Status |
|----|------|---------|------|-------------|------------|--------|
| F-0001 | Auth | User registration (email + password) | All | integration | — | passed |
| F-0002 | Auth | Email validation (format, length, uniqueness) | All | unit + integration | — | passed |
| F-0003 | Auth | Password strength requirements (min length, complexity) | All | unit | — | passed |
| F-0004 | Auth | Login with email and password | All | integration | — | passed |
| F-0005 | Auth | Login error: wrong password returns 401 | All | integration | — | passed |
| F-0006 | Auth | Login error: non-existent user returns 401 (timing-safe) | All | integration | — | passed |
| F-0007 | Auth | JWT access token issuance on login | All | integration | — | passed |
| F-0008 | Auth | Refresh token rotation (single-use, old token invalidated) | All | integration | — | passed |
| F-0009 | Auth | Refresh token stored as httpOnly Secure SameSite=Lax cookie | All | integration | — | no-test |
| F-0010 | Auth | Silent refresh on page load via cookie | All | e2e | — | passed |
| F-0011 | Auth | Logout invalidates refresh token | All | integration | — | passed |
| F-0012 | Auth | Google OAuth redirect to OIDC provider | All | integration | — | passed |
| F-0013 | Auth | Google OAuth callback processes id_token | All | integration | — | passed |
| F-0014 | Auth | GitHub OAuth redirect to authorize URL | All | integration | — | passed |
| F-0015 | Auth | GitHub OAuth callback exchanges code for token | All | integration | — | passed |
| F-0016 | Auth | OAuth email_verified check blocks unverified emails | All | integration | — | passed |
| F-0017 | Auth | OAuth upsert handles race conditions (ON CONFLICT) | All | integration | — | passed |
| F-0018 | Auth | Email verification flow (token generation + confirmation) | All | integration | — | passed |
| F-0019 | Auth | GET /api/v1/me returns current user profile | All | integration | — | passed |
| F-0020 | Auth | Auth middleware verifies JWT signature on protected routes | All | integration | — | passed |
| F-0021 | Auth | Auth middleware path allowlist skips public routes | All | unit | — | passed |
| F-0022 | Auth | Auth middleware _OAUTH_PATH_RE matches OAuth routes | All | unit | — | passed |
| F-0023 | Auth | Auth required guard raises RuntimeError if USE_PG not set | All | unit | — | passed |
| F-0024 | Auth | Token expiry returns 401 and triggers client refresh | All | integration | — | passed |
| F-0025 | Auth | CORS credential handling (Access-Control-Allow-Credentials) | All | integration | — | passed |
| F-0026 | Upload/Ingest | CSV file upload via POST /api/v1/ingest/upload | All | integration | — | passed |
| F-0027 | Upload/Ingest | RaceChrono CSV header detection (Lap #, Speed columns) | All | unit | — | passed |
| F-0028 | Upload/Ingest | RaceBox CSV header detection (alternate column names) | All | unit | — | no-test |
| F-0029 | Upload/Ingest | Streaming ingest path active when TELEMETRY_INGEST_V2=1 | All | unit | — | passed |
| F-0030 | Upload/Ingest | Adaptive chunk sizing via compute_chunk_size(n_cols) | All | unit | — | passed |
| F-0031 | Upload/Ingest | Upload progress SSE stream emits real-time events | All | integration | — | no-test |
| F-0032 | Upload/Ingest | Upload progress polling endpoint returns job status | All | integration | — | no-test |
| F-0033 | Upload/Ingest | Upload resume via Parquet chunk cache (index-based flush) | All | unit | — | passed |
| F-0034 | Upload/Ingest | Upload idempotency via SHA-256 checksum (partial + full) | All | unit | — | passed |
| F-0035 | Upload/Ingest | Large file handling (>1GB) stays under 1GB peak memory | All | benchmark | — | no-test |
| F-0036 | Upload/Ingest | Invalid CSV file rejected with descriptive error | All | integration | — | passed |
| F-0037 | Upload/Ingest | Empty CSV file rejected | All | integration | — | no-test |
| F-0038 | Upload/Ingest | Encoding fallback (UTF-8 to Latin-1) | All | unit | — | passed |
| F-0039 | Upload/Ingest | Delimiter auto-detection (comma, semicolon, tab) | All | unit | — | passed |
| F-0040 | Upload/Ingest | Numeric coercion in-place (no .copy() for memory budget) | All | unit | — | passed |
| F-0041 | Upload/Ingest | Disk space check before cache creation (InsufficientDiskSpace) | All | unit | — | passed |
| F-0042 | Upload/Ingest | Upload size limit enforcement per billing tier | Racer+ | integration | — | passed |
| F-0043 | Upload/Ingest | Upload quota enforcement (monthly count per plan) | All | integration | — | passed |
| F-0044 | Upload/Ingest | Upload job status tracking via JobStore (in-memory + SQLite) | All | unit | — | passed |
| F-0045 | Upload/Ingest | Parquet chunk merge via PyArrow streaming writer (O(1) memory) | All | unit | — | passed |
| F-0046 | Pipeline | GPS quality filtering (satellite count, HDOP threshold) | All | unit | OK_R1 | no-test |
| F-0047 | Pipeline | Derived channel: acceleration from speed | All | unit | OK_R1 | passed |
| F-0048 | Pipeline | Derived channel: yaw rate from heading | All | unit | — | no-test |
| F-0049 | Pipeline | Derived channel: lateral G | All | unit | — | passed |
| F-0050 | Pipeline | Session trimming (start/stop detection by motion) | All | unit | OK_R1 | no-test |
| F-0051 | Pipeline | Track detection via GPS fingerprint matching | All | unit | OK_R1 | passed |
| F-0052 | Pipeline | Track registration for unknown GPS signatures | All | integration | — | no-test |
| F-0053 | Pipeline | Corner detection: apex identification | All | unit | OK_R1 | passed |
| F-0054 | Pipeline | Corner detection: entry point | All | unit | — | passed |
| F-0055 | Pipeline | Corner detection: exit point | All | unit | — | passed |
| F-0056 | Pipeline | Lap segmentation from "Lap #" column | All | unit | OK_R1 | passed |
| F-0057 | Pipeline | Resampling: distance-grid normalization (1000 points) | All | unit | — | no-test |
| F-0058 | Pipeline | Lap time calculation from timestamps | All | unit | OK_R1 | passed |
| F-0059 | Pipeline | Best lap identification (minimum valid lap time) | All | unit | OK_R1 | passed |
| F-0060 | Pipeline | Lap validity detection (incomplete laps, pit laps) | All | unit | OK_R1 | passed |
| F-0061 | Pipeline | Outlier lap filtering (statistical threshold) | All | unit | OK_R1 | passed |
| F-0062 | Pipeline | Speed mean per lap | All | unit | OK_R1 | passed |
| F-0063 | Pipeline | Speed max per lap | All | unit | OK_R1 | passed |
| F-0064 | Pipeline | Braking max per lap (peak deceleration) | All | unit | OK_R1 | passed |
| F-0065 | Pipeline | Acceleration max per lap (peak longitudinal G) | All | unit | OK_R1 | passed |
| F-0066 | Pipeline | Line length per lap (GPS distance) | All | unit | OK_R1 | passed |
| F-0067 | Pipeline | Consistency metrics: coefficient of variation | All | unit | OK_R1 | passed |
| F-0068 | Pipeline | Consistency metrics: standard deviation | All | unit | OK_R1 | passed |
| F-0069 | Pipeline | Robustness metrics computation | All | unit | OK_R1 | passed |
| F-0070 | Pipeline | Reference line computation (ideal racing line) | All | unit | — | passed |
| F-0071 | Pipeline | Curvature profile from reference line | All | unit | — | passed |
| F-0072 | Pipeline | Friction model estimation | All | unit | — | passed |
| F-0073 | Pipeline | Vehicle parameter estimation (mass, tire grip) | All | unit | — | passed |
| F-0074 | Pipeline | Data quality assessment (completeness, noise level) | All | unit | — | no-test |
| F-0075 | Pipeline | Theoretical lap: QSS solver convergence | All | unit | OK_R1 | passed |
| F-0076 | Pipeline | Theoretical lap time output | All | unit | OK_R1 | passed |
| F-0077 | Pipeline | Feature dataset builder (Parquet output) | All | unit | — | no-test |
| F-0078 | Pipeline | ML model training on feature dataset | All | unit | — | no-test |
| F-0079 | Pipeline | Anomaly detection on lap features | All | unit | — | no-test |
| F-0080 | Pipeline | Scoring: Pace sub-score (/25) | All | unit | OK_R1 | passed |
| F-0081 | Pipeline | Scoring: Consistency sub-score (/25) | All | unit | OK_R1 | passed |
| F-0082 | Pipeline | Scoring: Execution sub-score (/25) | All | unit | OK_R1 | passed |
| F-0083 | Pipeline | Scoring: Robustness sub-score (/25) | All | unit | OK_R1 | passed |
| F-0084 | Pipeline | Scoring: Total score (/100) | All | unit | OK_R1 | passed |
| F-0085 | Pipeline | Scoring: Grade assignment (A through F) | All | unit | OK_R1 | passed |
| F-0086 | Pipeline | Coaching guide generation (textual advice) | All | unit | — | passed |
| F-0087 | Pipeline | Driver profile construction from multi-session data | All | unit | — | no-test |
| F-0088 | Pipeline | HTML report generation (Jinja2 template) | All | unit | — | no-test |
| F-0089 | Pipeline | PDF report generation | Racer+ | unit | — | no-test |
| F-0090 | Pipeline | DB persistence: session record | All | integration | — | passed |
| F-0091 | Pipeline | DB persistence: lap records | All | integration | — | passed |
| F-0092 | Pipeline | DB persistence: GPS traces | All | integration | — | no-test |
| F-0093 | Pipeline | DB persistence: scoring results | All | integration | — | passed |
| F-0094 | Pipeline | DB persistence: corner metrics | All | integration | — | passed |
| F-0095 | Pipeline | DB persistence: theoretical data | All | integration | — | no-test |
| F-0096 | Pipeline | Condition phase detection (dry/wet) | All | unit | — | passed |
| F-0097 | Pipeline | Track evolution tracking across sessions | All | unit | — | no-test |
| F-0098 | Pipeline | Grip evolution tracking | All | unit | — | passed |
| F-0099 | Pipeline | Weather timeline integration | All | unit | — | passed |
| F-0100 | Pipeline | Joker lap detection | All | unit | — | passed |
| F-0101 | Pipeline | _safe_step graceful degradation (exception → None, no crash) | All | unit | — | passed |
| F-0102 | Charts | Speed trace chart (best lap speed vs distance) | All | e2e | — | e2e-only |
| F-0103 | Charts | Speed profile overlay (best/avg/worst) | All | e2e | — | e2e-only |
| F-0104 | Charts | Lap time scatter chart (lap number vs time) | All | e2e | — | e2e-only |
| F-0105 | Charts | Lap time bar chart | All | e2e | — | e2e-only |
| F-0106 | Charts | Delta chart (time delta vs best lap) | All | e2e | — | e2e-only |
| F-0107 | Charts | G-G diagram (friction circle) | All | e2e | — | e2e-only |
| F-0108 | Charts | Corner speed comparison chart (per corner) | All | e2e | — | e2e-only |
| F-0109 | Charts | Consistency heatmap (sector deltas across laps) | All | e2e | — | e2e-only |
| F-0110 | Charts | Delta heatmap (laps x segments matrix) | All | e2e | — | e2e-only |
| F-0111 | Charts | Track map (GPS trace overlay on map) | All | e2e | — | e2e-only |
| F-0112 | Charts | Corner replay map (animated corner view) | All | e2e | — | e2e-only |
| F-0113 | Charts | Brake point visualization (braking zones on map) | All | e2e | — | e2e-only |
| F-0114 | Charts | Throttle map (throttle percentage on track) | All | e2e | — | e2e-only |
| F-0115 | Charts | Energy balance chart | All | e2e | — | e2e-only |
| F-0116 | Charts | Fatigue/reaction time chart (lap-over-lap) | All | e2e | — | e2e-only |
| F-0117 | Charts | Driving style radar chart (multi-axis) | All | e2e | — | e2e-only |
| F-0118 | Charts | Performance fingerprint (4-pillar visualization) | All | e2e | — | e2e-only |
| F-0119 | Charts | Corner mastery chart (corner score per corner) | All | e2e | — | e2e-only |
| F-0120 | Charts | Session progression chart (improvement over session) | All | e2e | — | e2e-only |
| F-0121 | Charts | Evolution over sessions chart (multi-session trend) | All | e2e | — | e2e-only |
| F-0122 | Charts | Comparison matrix chart (multi-driver grid) | All | e2e | — | e2e-only |
| F-0123 | Charts | Race strategy chart (stint/tire/fuel overlay) | Racer+ | e2e | — | e2e-only |
| F-0124 | Charts | Sector times chart (per-sector breakdown) | All | e2e | — | e2e-only |
| F-0125 | Charts | Weather correlation chart (grip vs conditions) | All | e2e | — | e2e-only |
| F-0126 | Charts | Trend analysis chart (long-term performance) | All | e2e | — | e2e-only |
| F-0127 | Charts | Position/gap chart (race positions over laps) | All | e2e | — | e2e-only |
| F-0128 | Charts | Stint analysis chart (tire/pace degradation) | Racer+ | e2e | — | e2e-only |
| F-0129 | Charts | Tire degradation chart (grip vs lap count) | Racer+ | e2e | — | e2e-only |
| F-0130 | Charts | Chart dark theme styling (consistent color palette) | All | e2e | — | e2e-only |
| F-0131 | Charts | Chart responsive sizing (mobile + desktop) | All | e2e | — | e2e-only |
| F-0132 | Charts | Chart tooltip interactions (hover data display) | All | e2e | — | e2e-only |
| F-0133 | Charts | Chart zoom/pan interactions | All | e2e | — | e2e-only |
| F-0134 | Charts | Chart data loading states (skeleton/spinner) | All | e2e | — | e2e-only |
| F-0135 | Charts | Chart error states (graceful fallback) | All | e2e | — | e2e-only |
| F-0136 | Charts | Chart export (image download PNG/SVG) | All | e2e | — | e2e-only |
| F-0137 | Exports | CSV export: session data download | All | integration | — | passed |
| F-0138 | Exports | CSV export: corner table download | All | integration | — | no-test |
| F-0139 | Exports | CSV export: delta map download | All | integration | — | no-test |
| F-0140 | Exports | JSON export: session summary | All | integration | — | passed |
| F-0141 | Exports | PDF report download | Racer+ | integration | — | passed |
| F-0142 | Exports | HTML report download | All | integration | — | no-test |
| F-0143 | Exports | Bulk export: multiple sessions at once | Racer+ | integration | — | passed |
| F-0144 | Exports | Export template management (CRUD) | Racer+ | integration | — | no-test |
| F-0145 | Exports | Export format gating per tier (CSV free, PDF racer+) | All | integration | — | passed |
| F-0146 | Exports | Export quota enforcement (monthly limit per plan) | All | integration | — | passed |
| F-0147 | Exports | Export job async processing via Celery | All | integration | — | passed |
| F-0148 | Exports | Export file download link generation | All | integration | — | passed |
| F-0149 | Exports | Export file expiry (time-limited download URL) | All | integration | — | passed |
| F-0150 | Exports | GDPR data export (full user data package) | All | integration | — | passed |
| F-0151 | Exports | GDPR data erasure (account + data deletion) | All | integration | — | passed |
| F-0152 | Billing | Plan definitions: demo tier (free, limited features) | All | unit | — | passed |
| F-0153 | Billing | Plan definitions: racer tier (monthly + annual) | Racer | unit | — | passed |
| F-0154 | Billing | Plan definitions: world_class tier (monthly + annual) | WorldClass | unit | — | passed |
| F-0155 | Billing | Pricing page displays correct plan cards and prices | All | e2e | — | e2e-only |
| F-0156 | Billing | Stripe checkout session creation (POST /api/v1/billing/checkout) | Racer+ | integration | — | passed |
| F-0157 | Billing | Stripe webhook: checkout.session.completed updates plan_tier | All | integration | — | passed |
| F-0158 | Billing | Stripe webhook: customer.subscription.updated syncs status | All | integration | — | passed |
| F-0159 | Billing | Stripe webhook: customer.subscription.deleted downgrades tier | All | integration | — | passed |
| F-0160 | Billing | Stripe webhook: invoice.payment_failed marks past_due | All | integration | — | passed |
| F-0161 | Billing | Stripe webhook signature verification (Stripe-Signature header) | All | integration | — | passed |
| F-0162 | Billing | Plan tier update persisted to users table on payment | All | integration | — | passed |
| F-0163 | Billing | Subscription status tracking (active/past_due/canceled) | All | integration | — | passed |
| F-0164 | Billing | Billing portal redirect (GET /api/v1/billing/portal) | Racer+ | integration | — | passed |
| F-0165 | Billing | Plan upgrade flow (demo → racer → world_class) | All | e2e | — | e2e-only |
| F-0166 | Billing | Plan downgrade flow (world_class → racer → demo) | All | e2e | — | passed |
| F-0167 | Billing | Subscription cancellation (end of billing period) | Racer+ | integration | — | passed |
| F-0168 | Billing | Subscription pause/resume | Racer+ | integration | — | passed |
| F-0169 | Billing | Trial period handling (if configured) | All | integration | — | passed |
| F-0170 | Billing | Annual vs monthly billing toggle | Racer+ | e2e | — | e2e-only |
| F-0171 | Billing | Stripe customer creation on first checkout | All | integration | — | passed |
| F-0172 | Account | Profile display (name, email, plan tier) | All | e2e | — | e2e-only |
| F-0173 | Account | Profile update (display name, avatar) | All | integration | — | passed |
| F-0174 | Account | Password change (current + new password) | All | integration | — | passed |
| F-0175 | Account | Email change triggers re-verification | All | integration | — | passed |
| F-0176 | Account | Avatar/display name rendering in UI | All | e2e | — | e2e-only |
| F-0177 | Account | Notification preferences (email opt-in/out) | All | integration | — | passed |
| F-0178 | Account | Account deletion request (GDPR) | All | integration | — | passed |
| F-0179 | Account | Account data export request (GDPR) | All | integration | — | passed |
| F-0180 | Account | Session history/activity log display | All | e2e | — | e2e-only |
| F-0181 | Account | Connected OAuth accounts display | All | e2e | — | e2e-only |
| F-0182 | Account | API key management (world_class tier only) | WorldClass | integration | — | no-test |
| F-0183 | Account | Workspace selection (switch active workspace) | All | e2e | — | e2e-only |
| F-0184 | Account | Workspace creation (team workspace) | All | integration | — | passed |
| F-0185 | Account | Default personal workspace auto-created on register | All | integration | — | passed |
| F-0186 | Account | Account security settings page renders | All | e2e | — | e2e-only |
| F-0187 | Admin | Admin authentication (superadmin role check) | Admin | integration | — | passed |
| F-0188 | Admin | Admin TOTP 2FA verification (verify_2fa endpoint) | Admin | integration | — | passed |
| F-0189 | Admin | User list/search in race-control panel | Admin | e2e | — | passed |
| F-0190 | Admin | User tier override (manual plan assignment) | Admin | integration | — | passed |
| F-0191 | Admin | Subscription reconciliation (Stripe vs DB sync) | Admin | integration | — | passed |
| F-0192 | Admin | Webhook log viewer (recent Stripe events) | Admin | e2e | — | passed |
| F-0193 | Admin | Revenue snapshot (MRR/ARR calculations) | Admin | e2e | — | passed |
| F-0194 | Admin | Entitlement anomaly detection (usage vs plan mismatch) | Admin | integration | — | passed |
| F-0195 | Admin | Audit log viewer (security events) | Admin | e2e | — | passed |
| F-0196 | Admin | Admin bootstrap (first superadmin user creation) | Admin | integration | — | passed |
| F-0197 | Admin | Retention queue management (churn risk users) | Admin | e2e | — | passed |
| F-0198 | Admin | Entitlement override creation (manual feature grant) | Admin | integration | — | passed |
| F-0199 | Admin | Usage summary per workspace | Admin | e2e | — | passed |
| F-0200 | Admin | Admin security events log (login attempts, changes) | Admin | e2e | — | passed |
| F-0201 | Admin | Admin role requirement enforced on all race-control routes | Admin | integration | — | passed |
| F-0202 | RBAC/Entitlements | Entitlement middleware runs before_request on protected routes | All | integration | — | passed |
| F-0203 | RBAC/Entitlements | Feature gate: comparison (world_class only) | WorldClass | integration | — | passed |
| F-0204 | RBAC/Entitlements | Feature gate: visualization page (racer+) | Racer+ | integration | — | passed |
| F-0205 | RBAC/Entitlements | Feature gate: race_strategy mutations (racer+) | Racer+ | integration | — | passed |
| F-0206 | RBAC/Entitlements | Feature gate: API data access (world_class only) | WorldClass | integration | — | passed |
| F-0207 | RBAC/Entitlements | Feature gate: exports (racer+) | Racer+ | integration | — | passed |
| F-0208 | RBAC/Entitlements | Feature gate: simulations (racer+) | Racer+ | integration | — | passed |
| F-0209 | RBAC/Entitlements | Quota gate: reports (monthly limit per plan) | All | integration | — | passed |
| F-0210 | RBAC/Entitlements | Quota gate: uploads (monthly count per plan) | All | integration | — | passed |
| F-0211 | RBAC/Entitlements | Usage recording after_request hook | All | integration | — | passed |
| F-0212 | RBAC/Entitlements | Entitlement override application (admin-granted) | Admin | integration | — | passed |
| F-0213 | RBAC/Entitlements | Entitlement override expiry (time-limited grants) | Admin | integration | — | passed |
| F-0214 | RBAC/Entitlements | Plan definitions stored in DB table | All | unit | — | passed |
| F-0215 | RBAC/Entitlements | Usage events recording (per-action counters) | All | integration | — | passed |
| F-0216 | RBAC/Entitlements | Usage monthly aggregation (rollup by period) | All | integration | — | passed |
| F-0217 | RBAC/Entitlements | Atomic quota check-and-record (SELECT FOR UPDATE) | All | integration | — | passed |
| F-0218 | RBAC/Entitlements | Subscription status impact: active allows all features | All | integration | — | passed |
| F-0219 | RBAC/Entitlements | Paused subscription blocks mutation endpoints | Racer+ | integration | — | passed |
| F-0220 | RBAC/Entitlements | Canceled subscription grace period (access until period end) | Racer+ | integration | — | passed |
| F-0221 | RBAC/Entitlements | Decorator: @require_feature gates endpoint by feature flag | All | unit | — | passed |
| F-0222 | RBAC/Entitlements | Decorator: @require_report_quota checks quota before action | All | unit | — | passed |
| F-0223 | RBAC/Entitlements | Decorator: @require_upload_size validates file size per tier | All | unit | — | passed |
| F-0224 | RBAC/Entitlements | Rate limiting per tier (plan multipliers applied) | All | integration | — | passed |
| F-0225 | RBAC/Entitlements | Rate limit tiers: 5 levels (auth, read, write, analyze, export) | All | unit | — | passed |
| F-0226 | RBAC/Entitlements | Entitlement snapshot resolution (plan + overrides merged) | All | unit | — | passed |
| F-0227 | Tenant Isolation | RLS policies active on all 44 workspace-scoped tables | All | integration | — | passed |
| F-0228 | Tenant Isolation | SET LOCAL workspace context per-request transaction | All | integration | — | passed |
| F-0229 | Tenant Isolation | X-Workspace-Id header parsing in tenant middleware | All | unit | — | passed |
| F-0230 | Tenant Isolation | Workspace membership verification (_verify_workspace_access) | All | integration | — | passed |
| F-0231 | Tenant Isolation | Default workspace resolution when header absent | All | integration | — | passed |
| F-0232 | Tenant Isolation | Session data isolation: API list returns only workspace sessions | All | integration | — | no-test |
| F-0233 | Tenant Isolation | Session data isolation: API detail rejects cross-workspace ID | All | integration | — | no-test |
| F-0234 | Tenant Isolation | Session data isolation: direct URL blocked for other workspace | All | integration | — | no-test |
| F-0235 | Tenant Isolation | Track data isolation (workspace-scoped tracks) | All | integration | — | no-test |
| F-0236 | Tenant Isolation | Driver data isolation (workspace-scoped drivers) | All | integration | — | no-test |
| F-0237 | Tenant Isolation | Export data isolation (workspace-scoped exports) | All | integration | — | no-test |
| F-0238 | Tenant Isolation | Comparison data isolation (cross-workspace compare blocked) | All | integration | — | no-test |
| F-0239 | Tenant Isolation | Race strategy data isolation (workspace-scoped strategies) | All | integration | — | no-test |
| F-0240 | Tenant Isolation | IDOR prevention: sequential session ID cannot access other ws | All | integration | — | passed |
| F-0241 | Tenant Isolation | IDOR prevention: sequential user ID cannot access other user | All | integration | — | no-test |
| F-0242 | Tenant Isolation | IDOR prevention: guessed workspace ID rejected if not member | All | integration | — | passed |
| F-0243 | Tenant Isolation | Cross-workspace API calls return 403 | All | integration | — | passed |
| F-0244 | Tenant Isolation | Workspace role enforcement (viewer cannot write) | All | integration | — | passed |
| F-0245 | Tenant Isolation | Team member isolation (member sees only own team data) | All | integration | — | passed |
| F-0246 | Tenant Isolation | Storage path isolation (uploads scoped to workspace dir) | All | integration | — | no-test |
| F-0247 | Selling Site | Homepage hero section renders correctly | All | e2e | — | e2e-only |
| F-0248 | Selling Site | Homepage CTA buttons link to registration/pricing | All | e2e | — | e2e-only |
| F-0249 | Selling Site | Navigation links resolve to correct routes | All | e2e | — | e2e-only |
| F-0250 | Selling Site | Pricing page renders with plan cards | All | e2e | — | e2e-only |
| F-0251 | Selling Site | Pricing plan cards show correct feature lists | All | e2e | — | e2e-only |
| F-0252 | Selling Site | Pricing toggle switches between monthly and annual | All | e2e | — | e2e-only |
| F-0253 | Selling Site | Pricing currency display (EUR/USD) | All | e2e | — | e2e-only |
| F-0254 | Selling Site | Product page renders feature descriptions | All | e2e | — | e2e-only |
| F-0255 | Selling Site | Teams page renders team collaboration features | All | e2e | — | e2e-only |
| F-0256 | Selling Site | Circuits/tracks marketing page renders | All | e2e | — | e2e-only |
| F-0257 | Selling Site | DPA page renders data processing agreement | All | e2e | — | e2e-only |
| F-0258 | Selling Site | Security page renders security practices | All | e2e | — | e2e-only |
| F-0259 | Selling Site | Privacy policy page renders full text | All | e2e | — | e2e-only |
| F-0260 | Selling Site | Terms of service page renders full text | All | e2e | — | e2e-only |
| F-0261 | Selling Site | Insights/blog page renders article list | All | e2e | — | e2e-only |
| F-0262 | Selling Site | SEO metadata present (title, description, og tags) | All | e2e | — | e2e-only |
| F-0263 | Selling Site | Sitemap.xml exists and is valid | All | e2e | — | e2e-only |
| F-0264 | Selling Site | Mobile responsive layout (viewport < 768px) | All | e2e | — | e2e-only |
| F-0265 | Selling Site | Dark theme styling consistent across pages | All | e2e | — | e2e-only |
| F-0266 | Selling Site | Cookie consent banner displayed | All | e2e | — | e2e-only |
| F-0267 | Selling Site | A/B experiment assignments (lap_exp_hero, pricing, cta) | All | unit | — | e2e-only |
| F-0268 | Selling Site | UTM parameter tracking in middleware | All | unit | — | e2e-only |
| F-0269 | Selling Site | Persona detection middleware sets audience cookie | All | unit | — | e2e-only |
| F-0270 | Selling Site | Signup CTA navigates to registration flow | All | e2e | — | e2e-only |
| F-0271 | Selling Site | Login CTA navigates to login page | All | e2e | — | e2e-only |
| F-0272 | Old-Tool Parity | Parity: lap time values match for OK_R1 reference session | All | parity | OK_R1 | e2e-only |
| F-0273 | Old-Tool Parity | Parity: lap time values match for OK_R3 reference session | All | parity | OK_R3 | e2e-only |
| F-0274 | Old-Tool Parity | Parity: lap time values match for OK_R4 reference session | All | parity | OK_R4 | e2e-only |
| F-0275 | Old-Tool Parity | Parity: scoring values match for OK_R1 reference session | All | parity | OK_R1 | e2e-only |
| F-0276 | Old-Tool Parity | Parity: scoring values match for OK_R3 reference session | All | parity | OK_R3 | e2e-only |
| F-0277 | Old-Tool Parity | Parity: scoring values match for OK_R4 reference session | All | parity | OK_R4 | e2e-only |
| F-0278 | Old-Tool Parity | Parity: corner count matches reference | All | parity | OK_R1 | e2e-only |
| F-0279 | Old-Tool Parity | Parity: corner metrics (apex speed, entry speed) match | All | parity | OK_R1 | e2e-only |
| F-0280 | Old-Tool Parity | Parity: consistency metrics match reference | All | parity | OK_R1 | e2e-only |
| F-0281 | Old-Tool Parity | Parity: theoretical lap time within tolerance | All | parity | OK_R1 | e2e-only |
| F-0282 | Old-Tool Parity | Parity: best lap identification matches | All | parity | OK_R1 | e2e-only |
| F-0283 | Old-Tool Parity | Parity: track detection selects correct track | All | parity | OK_R1 | e2e-only |
| F-0284 | Old-Tool Parity | Parity: all pipeline steps complete without error | All | parity | OK_R1 | e2e-only |
| F-0285 | Old-Tool Parity | Parity: grade assignment matches reference | All | parity | OK_R1 | e2e-only |
| F-0286 | Old-Tool Parity | Parity: lap validity flags match reference | All | parity | OK_R1 | e2e-only |
| F-0287 | Old-Tool Parity | Parity: speed mean/max within tolerance | All | parity | OK_R1 | e2e-only |
| F-0288 | Old-Tool Parity | Parity: braking/accel max within tolerance | All | parity | OK_R1 | e2e-only |
| F-0289 | Old-Tool Parity | Parity: line length within tolerance | All | parity | OK_R1 | e2e-only |
| F-0290 | Old-Tool Parity | Parity: robustness metrics within tolerance | All | parity | OK_R1 | e2e-only |
| F-0291 | Old-Tool Parity | Parity: overall summary structure matches schema | All | parity | OK_R1 | e2e-only |
| F-0292 | Security | Security headers: HSTS on API (Strict-Transport-Security) | All | integration | — | e2e-only |
| F-0293 | Security | Security headers: CSP on frontend (Content-Security-Policy) | All | e2e | — | e2e-only |
| F-0294 | Security | Security headers: X-Frame-Options DENY | All | integration | — | e2e-only |
| F-0295 | Security | CORS allowed origins enforcement (reject unknown origins) | All | integration | — | passed |
| F-0296 | Security | CSRF protection on state-changing endpoints | All | integration | — | passed |
| F-0297 | Security | SQL injection prevention (parameterized queries only) | All | unit | — | passed |
| F-0298 | Security | XSS prevention (output encoding in templates) | All | e2e | — | e2e-only |
| F-0299 | Security | Rate limiting active and returning 429 on excess | All | integration | — | passed |
| F-0300 | Security | No secrets leaked in API error responses or logs | All | integration | — | no-test |
| F-0301 | Security | No full file paths exposed in API responses (file_name only) | All | unit | — | no-test |
| F-0302 | Security | httpOnly flag set on refresh token cookie | All | integration | — | passed |
| F-0303 | Security | Secure flag set on refresh token cookie | All | integration | — | passed |
| F-0304 | Security | SameSite=Lax set on refresh token cookie | All | integration | — | passed |
| F-0305 | Security | JWT signature verification rejects tampered tokens | All | unit | — | passed |
| F-0306 | Security | Password hashing uses Argon2id (time=3, mem=64K) | All | unit | — | passed |
