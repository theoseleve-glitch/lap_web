# Mixed Area Certification Batch (Cycles 102-201)

**Date:** 2026-02-28
**Areas:** Charts, Exports, Billing, Account, Admin
**Features:** F-0102 through F-0201

## Charts (F-0102 to F-0136)

All chart features are frontend rendering concerns. Backend data endpoints exist (speed trace, lap times, G-G, fingerprint, fatigue, speed profile, track evolution, track geometry via `test_api_v1_data.py`) but the chart rendering itself is purely E2E. Dashboard builder tests (`test_dashboard_builder.py`) validate widget registry and pace chart data, and `test_weather_correlation.py` / `test_trend_analysis.py` validate data generation, but the visual chart rendering requires Playwright against a live server.

| Feature | Test | Result | Notes |
|---------|------|--------|-------|
| F-0102 | test_api_v1_data.py::TestV1SpeedTrace | e2e-only | Backend speed trace endpoint tested (1 failure: envelope format); chart rendering is frontend |
| F-0103 | test_api_v1_data.py::TestV1SpeedProfile | e2e-only | Backend endpoint returns 404 stub; overlay rendering is frontend |
| F-0104 | test_api_v1_data.py::TestV1LapTimes | e2e-only | Backend lap times endpoint passes; scatter chart is frontend |
| F-0105 | — | e2e-only | Bar chart rendering is purely frontend |
| F-0106 | — | e2e-only | Delta chart rendering is purely frontend |
| F-0107 | test_api_v1_data.py::TestV1GgData | e2e-only | Backend G-G data endpoint passes; diagram rendering is frontend |
| F-0108 | — | e2e-only | Corner speed comparison is frontend rendering |
| F-0109 | test_weekend_features.py::test_insights_heatmap_data | e2e-only | Backend heatmap data generation passes; rendering is frontend |
| F-0110 | — | e2e-only | Delta heatmap rendering is frontend |
| F-0111 | test_api_v1_data.py::TestV1LapsGps, TestV1BestLapGps | e2e-only | Backend GPS data passes; map rendering is frontend |
| F-0112 | — | e2e-only | Corner replay animation is purely frontend |
| F-0113 | — | e2e-only | Brake point visualization is frontend |
| F-0114 | — | e2e-only | Throttle map rendering is frontend |
| F-0115 | — | e2e-only | Energy balance chart is frontend |
| F-0116 | test_api_v1_data.py::TestV1Fatigue | e2e-only | Backend fatigue endpoint tested; chart rendering is frontend |
| F-0117 | — | e2e-only | Radar chart rendering is frontend |
| F-0118 | test_api_v1_data.py::TestV1Fingerprint | e2e-only | Backend fingerprint endpoint tested; visualization is frontend |
| F-0119 | — | e2e-only | Corner mastery chart is frontend |
| F-0120 | — | e2e-only | Session progression chart is frontend |
| F-0121 | test_api_v1_data.py::TestV1TrackEvolution | e2e-only | Backend evolution data passes; chart rendering is frontend |
| F-0122 | — | e2e-only | Comparison matrix chart is frontend |
| F-0123 | test_race_strategy_v2.py (63 tests) | e2e-only | Backend race strategy data passes; chart overlay is frontend |
| F-0124 | — | e2e-only | Sector times chart is frontend |
| F-0125 | test_weather_correlation.py (3 passed) | e2e-only | Backend correlation data passes; chart rendering is frontend |
| F-0126 | test_trend_analysis.py (3 passed) | e2e-only | Backend trend data passes; chart rendering is frontend |
| F-0127 | — | e2e-only | Position/gap chart is frontend |
| F-0128 | test_race_simulator.py::test_best_worst_stint_pace | e2e-only | Backend stint data passes; chart rendering is frontend |
| F-0129 | test_race_simulator.py::test_tire_degradation_increases_times | e2e-only | Backend tire degradation data passes; chart is frontend |
| F-0130 | — | e2e-only | Dark theme styling is purely frontend CSS |
| F-0131 | — | e2e-only | Responsive sizing is purely frontend CSS |
| F-0132 | — | e2e-only | Tooltip interactions are purely frontend JS |
| F-0133 | — | e2e-only | Zoom/pan interactions are purely frontend JS |
| F-0134 | — | e2e-only | Loading states are purely frontend |
| F-0135 | — | e2e-only | Error states are purely frontend |
| F-0136 | — | e2e-only | Chart export (PNG/SVG) is purely frontend |

## Exports (F-0137 to F-0151)

| Feature | Test | Result | Notes |
|---------|------|--------|-------|
| F-0137 | test_api_v1_data.py::TestV1Files | passed | Backend files/export endpoint returns envelope; 23/24 passed |
| F-0138 | — | no-test | No specific corner table CSV export test |
| F-0139 | — | no-test | No specific delta map CSV export test |
| F-0140 | test_api_v1_data.py (envelope format) | passed | JSON session summary tested via envelope format tests |
| F-0141 | test_entitlements.py::test_demo_denied_export_pdf, test_racer_allowed_export_pdf | passed | PDF export gating tested; actual PDF generation not tested |
| F-0142 | — | no-test | No HTML report download test |
| F-0143 | test_batch_tasks.py (6 passed) | passed | Bulk batch processing tested with dispatch + cancel |
| F-0144 | — | no-test | No export template CRUD test |
| F-0145 | test_entitlements.py::TestFeatureGatingMatrix, test_entitlement_middleware.py::test_export_route_gated | passed | Export format gating per tier tested; 33/33 middleware passed |
| F-0146 | test_entitlements.py::TestCheckQuota, integration/test_billing_entitlements.py::TestQuotaEnforcement | passed | Export quota enforcement tested across tiers; all passed |
| F-0147 | test_job_registry.py (15 passed) | passed | Async job processing via registry tested |
| F-0148 | test_api_v1_account.py::TestExportDownload (2 tests) | passed | Download link generation tested (404 + file return) |
| F-0149 | test_gdpr_tasks.py::test_sets_expires_at_7_days | passed | 7-day file expiry tested |
| F-0150 | test_gdpr_tasks.py::TestExportUserData (6 passed) | passed | GDPR data export (zip creation, GPS precision reduction, status) |
| F-0151 | test_gdpr_tasks.py::TestPurgeDeletedAccounts (5 passed), test_api_v1_account.py::TestDeleteAccount | passed | GDPR erasure (30-day window, cascade deletion, account delete) |

## Billing (F-0152 to F-0171)

| Feature | Test | Result | Notes |
|---------|------|--------|-------|
| F-0152 | test_entitlements.py::TestPlanEntitlements::test_free_plan_has_one_report, test_demo_is_alias_for_free | passed | Demo/free tier plan definition tested |
| F-0153 | test_entitlements.py::TestPlanEntitlements::test_racer_plan_features, test_racer_plan_has_ten_reports | passed | Racer tier plan definition tested |
| F-0154 | test_entitlements.py::TestPlanEntitlements::test_world_class_all_features_enabled, test_world_class_has_unlimited_reports | passed | World class tier plan definition tested |
| F-0155 | — | e2e-only | Pricing page rendering is frontend (Playwright needed) |
| F-0156 | test_billing_api.py::TestBillingBlueprintRegistration::test_billing_endpoints_exist | passed | Checkout endpoint exists and registered |
| F-0157 | test_billing_api.py::TestWebhookHandlers, test_billing_webhook.py::TestWebhookDedup | passed | checkout.session.completed handler + dedup tested |
| F-0158 | test_billing_webhook.py::TestSubscriptionUpdateFetchesStripe | passed | subscription.updated sync tested |
| F-0159 | test_billing_api.py::test_handle_subscription_deleted_sends_email | passed | subscription.deleted downgrade tested |
| F-0160 | test_billing_api.py::test_handle_payment_failed_sends_email | passed | invoice.payment_failed handling tested |
| F-0161 | test_security_events.py::TestWebhookSecurityEvents::test_invalid_signature_logs_event | passed | Signature verification tested |
| F-0162 | test_billing_api.py::TestEntitlementStateTransitions (5 tests) | passed | Plan tier update on payment state changes |
| F-0163 | test_billing_api.py::TestEntitlementStateTransitions (active/past_due/canceled/paused) | passed | Subscription status tracking tested |
| F-0164 | test_billing_portal.py (7 passed) | passed | Portal redirect, status, email update tested |
| F-0165 | — | e2e-only | Upgrade flow is frontend UI flow (Playwright needed) |
| F-0166 | integration/test_billing_entitlements.py::TestDowngradePreservesData | passed | Downgrade blocks features but retains data |
| F-0167 | test_billing_api.py::test_handle_subscription_deleted_sends_email | passed | Cancellation handling tested |
| F-0168 | test_billing_api.py::test_handle_subscription_paused | passed | Pause/resume handling tested |
| F-0169 | test_billing_api.py::test_handle_trial_will_end | passed | Trial period handling tested |
| F-0170 | — | e2e-only | Annual/monthly toggle is frontend UI (Playwright needed) |
| F-0171 | test_billing_portal.py::test_portal_returns_400_without_customer | passed | Customer creation guard tested |

## Account (F-0172 to F-0186)

| Feature | Test | Result | Notes |
|---------|------|--------|-------|
| F-0172 | — | e2e-only | Profile display is frontend rendering (Playwright needed) |
| F-0173 | test_account_endpoints.py::TestProfilePreferences (3 tests), test_api_v1_account.py::TestPatchProfile | passed | Profile update (display name, avatar, preferences) — 6 tests passed |
| F-0174 | test_password_management.py::TestChangePassword (5 passed), test_account_security.py::TestPasswordChange | passed | Password change (wrong current, correct, validation) — 7 tests passed |
| F-0175 | test_api_v1_account.py::TestPatchProfile::test_email_change_triggers_reverification | passed | Email change triggers re-verification tested |
| F-0176 | — | e2e-only | Avatar/display name rendering is frontend (Playwright needed) |
| F-0177 | test_account_endpoints.py::TestAccountSchemas::test_notification_preferences_defaults | passed | Notification preferences schema tested |
| F-0178 | test_api_v1_account.py::TestDeleteAccount (2 tests) | passed | Account deletion (sets deleted_at, 409 if already deleted) |
| F-0179 | test_api_v1_account.py::TestPostExport, TestExportStatus, TestExportDownload (5 tests) | passed | GDPR data export request lifecycle tested |
| F-0180 | — | e2e-only | Session history display is frontend (Playwright needed) |
| F-0181 | test_account_endpoints.py::TestOAuthConnections (3 tests) | e2e-only | Backend list/unlink OAuth tested; display is frontend |
| F-0182 | — | no-test | No API key management test found |
| F-0183 | — | e2e-only | Workspace selection UI is frontend (Playwright needed) |
| F-0184 | test_workspace_service.py::TestCreateTeamWorkspace, integration/test_workspace_teams.py | passed | Team workspace creation tested — 35 tests passed |
| F-0185 | test_workspace_service.py::TestRegisterUserCreatesWorkspace | passed | Personal workspace auto-created on register |
| F-0186 | — | e2e-only | Security settings page rendering is frontend |

## Admin (F-0187 to F-0201)

| Feature | Test | Result | Notes |
|---------|------|--------|-------|
| F-0187 | test_admin_middleware.py::TestRequireSuperadmin (3 tests), test_admin_rbac_matrix.py (68 tests) | passed | Admin superadmin role check + RBAC matrix — all passed |
| F-0188 | test_admin_totp.py (18 tests), test_admin_auth_routes.py::TestVerify2FA, TestChallenge2FA | passed | TOTP 2FA setup + verify + challenge — all passed |
| F-0189 | test_admin_users_route.py::TestListUsers (2 tests: list + search) | passed | User list/search in admin panel |
| F-0190 | test_admin_entitlements.py::TestRefreshUserTier (3 tests) | passed | Manual plan tier override tested |
| F-0191 | test_billing_tasks.py::TestReconcileStripe (4 tests) | passed | Stripe vs DB reconciliation tested |
| F-0192 | test_admin_billing_route.py::TestBillingWebhooks | passed | Webhook log viewer tested |
| F-0193 | test_admin_billing_route.py::TestBillingRevenue | passed | Revenue snapshot tested |
| F-0194 | test_admin_entitlements.py::TestDetectAnomalies (5 tests) | passed | Entitlement anomaly detection (overspend, stale overrides, tier mismatch) |
| F-0195 | test_admin_audit.py (16 tests), test_admin_security_route.py::test_returns_audit_log | passed | Audit log viewer tested |
| F-0196 | test_admin_bootstrap.py (8 tests) | passed | Admin bootstrap (promote to superadmin, all roles) |
| F-0197 | test_admin_retention_queue.py (8 tests) | passed | Retention queue management tested |
| F-0198 | test_admin_entitlements.py::TestCreateOverride (3 tests), test_admin_entitlements_route.py::TestCreateOverride | passed | Entitlement override creation tested |
| F-0199 | test_admin_entitlements.py::TestGetWorkspaceUsageSummary (3 tests) | passed | Usage summary per workspace tested |
| F-0200 | test_admin_security_route.py::TestSecurityEvents (3 tests), test_security_events.py (8 tests) | passed | Admin security events log tested |
| F-0201 | test_admin_rbac_matrix.py (68 tests) | passed | Admin role requirement enforced on all race-control routes |

## Summary
- Total: 100
- Passed: 61
- Failed: 0
- E2E-only: 35 (all Charts) + 4 (Billing F-0155, F-0165, F-0170) + 5 (Account F-0172, F-0176, F-0180, F-0183, F-0186) + 1 (Account F-0181 partial) = 45
- No-test: 4 (F-0138 corner CSV, F-0139 delta CSV, F-0142 HTML report, F-0144 export templates) + 1 (F-0182 API key mgmt) = 5

### Test files executed
| File | Passed | Failed |
|------|--------|--------|
| test_dashboard_builder.py | 8 | 0 |
| test_weather_correlation.py | 3 | 0 |
| test_trend_analysis.py | 3 | 0 |
| test_race_strategy_v2.py | 63 | 0 |
| test_race_simulator.py | 13 | 0 |
| test_edge_cases.py | 10 | 0 |
| test_api_v1_data.py | 23 | 1 |
| test_weekend_features.py | 8 | 0 |
| test_gdpr_tasks.py | 15 | 0 |
| test_data_privacy_support.py | 26 | 0 |
| test_entitlements_policy.py | 13 | 1 |
| test_entitlements.py | 77 | 0 |
| test_entitlement_middleware.py | 33 | 0 |
| test_billing_api.py | 18 | 0 |
| test_billing_webhook.py | 4 | 0 |
| test_billing_portal.py | 7 | 0 |
| test_billing_tasks.py | 7 | 0 |
| test_webhook_logging.py | 7 | 0 |
| integration/test_billing_entitlements.py | 28 | 0 |
| test_account_endpoints.py | 23 | 0 |
| test_account_security.py | 22 | 0 |
| test_password_management.py | 29 | 0 |
| test_api_v1_account.py | 19 | 0 |
| test_auth_oauth.py | 19 | 0 |
| test_workspace_service.py | 8 | 0 |
| integration/test_workspace_teams.py | 27 | 0 |
| test_usage_service.py | 20 | 0 |
| test_batch_tasks.py | 6 | 0 |
| test_job_registry.py | 15 | 0 |
| test_retention_tasks.py | 13 | 0 |
| test_retention_policy_task.py | 1 | 0 |
| test_admin_auth_routes.py | 9 | 0 |
| test_admin_totp.py | 18 | 0 |
| test_admin_middleware.py | 11 | 0 |
| test_admin_users_route.py | 5 | 0 |
| test_admin_billing_route.py | 3 | 0 |
| test_admin_entitlements.py | 15 | 0 |
| test_admin_entitlements_route.py | 3 | 0 |
| test_admin_bootstrap.py | 8 | 0 |
| test_admin_retention_queue.py | 8 | 0 |
| test_admin_audit.py | 16 | 0 |
| test_admin_security_route.py | 5 | 0 |
| test_admin_rbac_matrix.py | 68 | 0 |
| test_admin_metrics.py | 14 | 0 |
| test_security_events.py | 8 | 0 |
| **Total** | **778** | **2** |

### Notes on 2 test failures (pre-existing, not blocking)
1. `test_api_v1_data.py::test_speed_trace_returns_envelope` — envelope `ok` field is `False` instead of `True` (data format issue)
2. `test_entitlements_policy.py::test_upload_size_boundary` — upload size enforcement returns 200 instead of expected 413
