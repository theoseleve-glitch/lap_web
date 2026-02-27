"""Tests for PROMPT 5B — Account UI Implementation (Next.js Frontend).

Validates:
- Account route group structure (layout, pages)
- Shared components in components/account/
- React hooks (useAccount, useEntitlements, useBilling, useUsage, useAuth)
- Zustand stores (entitlements-store, account-store)
- Design system consistency (dark theme, brand colors)
"""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _PROJECT_ROOT.parent
_LAP_ROOT = _REPO_ROOT / "lap-website"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ===========================================================================
# A) Account route group structure
# ===========================================================================

class TestAccountRouteGroup:
    """Account pages exist with correct structure."""

    def _account_dir(self):
        return _LAP_ROOT / "src" / "app" / "app" / "account"

    def test_layout_exists(self):
        assert (self._account_dir() / "layout.tsx").exists()

    def test_root_page_exists(self):
        assert (self._account_dir() / "page.tsx").exists()

    def test_profile_page_exists(self):
        assert (self._account_dir() / "profile" / "page.tsx").exists()

    def test_security_page_exists(self):
        assert (self._account_dir() / "security" / "page.tsx").exists()

    def test_billing_page_exists(self):
        assert (self._account_dir() / "billing" / "page.tsx").exists()

    def test_usage_page_exists(self):
        assert (self._account_dir() / "usage" / "page.tsx").exists()

    def test_data_page_exists(self):
        assert (self._account_dir() / "data" / "page.tsx").exists()

    def test_support_page_exists(self):
        assert (self._account_dir() / "support" / "page.tsx").exists()


class TestAccountLayout:
    """Account layout has sidebar navigation."""

    def _layout(self):
        return (_LAP_ROOT / "src" / "app" / "app" / "account" / "layout.tsx").read_text()

    def test_is_client_component(self):
        assert "'use client'" in self._layout()

    def test_has_sidebar(self):
        assert "aside" in self._layout() or "sidebar" in self._layout().lower()

    def test_profile_nav_link(self):
        assert "Profile" in self._layout()

    def test_security_nav_link(self):
        assert "Security" in self._layout()

    def test_billing_nav_link(self):
        layout = self._layout()
        assert "Billing" in layout or "Plan" in layout

    def test_usage_nav_link(self):
        assert "Usage" in self._layout()

    def test_data_nav_link(self):
        layout = self._layout()
        assert "Data" in layout or "Privacy" in layout

    def test_support_nav_link(self):
        assert "Support" in self._layout()

    def test_active_state_detection(self):
        assert "usePathname" in self._layout()

    def test_back_to_dashboard_link(self):
        assert "dashboard" in self._layout().lower()


class TestAccountRootRedirect:
    """Root /account page redirects to profile."""

    def test_redirects_to_profile(self):
        source = (_LAP_ROOT / "src" / "app" / "app" / "account" / "page.tsx").read_text()
        assert "redirect" in source.lower()
        assert "profile" in source


# ===========================================================================
# B) Shared account components
# ===========================================================================

class TestAccountComponents:
    """Shared components in components/account/."""

    def _comp_dir(self):
        return _LAP_ROOT / "src" / "components" / "account"

    def test_components_dir_exists(self):
        assert self._comp_dir().is_dir()

    def test_section_card_exists(self):
        assert (self._comp_dir() / "SectionCard.tsx").exists()

    def test_form_field_exists(self):
        assert (self._comp_dir() / "FormField.tsx").exists()

    def test_toggle_switch_exists(self):
        assert (self._comp_dir() / "ToggleSwitch.tsx").exists()

    def test_progress_ring_exists(self):
        assert (self._comp_dir() / "ProgressRing.tsx").exists()

    def test_confirmation_dialog_exists(self):
        assert (self._comp_dir() / "ConfirmationDialog.tsx").exists()

    def test_status_badge_exists(self):
        assert (self._comp_dir() / "StatusBadge.tsx").exists()

    def test_barrel_export_exists(self):
        assert (self._comp_dir() / "index.ts").exists()


class TestSectionCardComponent:
    """SectionCard component structure."""

    def _source(self):
        return (_LAP_ROOT / "src" / "components" / "account" / "SectionCard.tsx").read_text()

    def test_is_client_component(self):
        assert "'use client'" in self._source()

    def test_accepts_title_prop(self):
        assert "title" in self._source()

    def test_accepts_children(self):
        assert "children" in self._source()

    def test_uses_brand_fonts(self):
        source = self._source()
        assert "font-monument" in source or "font-telemetry" in source


class TestToggleSwitchComponent:
    """ToggleSwitch is accessible."""

    def _source(self):
        return (_LAP_ROOT / "src" / "components" / "account" / "ToggleSwitch.tsx").read_text()

    def test_has_role_switch(self):
        assert 'role="switch"' in self._source()

    def test_has_aria_checked(self):
        assert "aria-checked" in self._source()

    def test_supports_disabled(self):
        assert "disabled" in self._source()


class TestProgressRingComponent:
    """ProgressRing renders SVG with value/max."""

    def _source(self):
        return (_LAP_ROOT / "src" / "components" / "account" / "ProgressRing.tsx").read_text()

    def test_uses_svg(self):
        assert "<svg" in self._source()

    def test_accepts_value_and_max(self):
        source = self._source()
        assert "value" in source
        assert "max" in source

    def test_handles_unlimited(self):
        """When max is null, shows infinity symbol."""
        source = self._source()
        assert "null" in source
        # infinity symbol or unlimited text
        assert "\u221E" in source or "Unlimited" in source or "unlimited" in source


class TestConfirmationDialogComponent:
    """ConfirmationDialog is modal with confirm/cancel."""

    def _source(self):
        return (_LAP_ROOT / "src" / "components" / "account" / "ConfirmationDialog.tsx").read_text()

    def test_has_dialog_element(self):
        assert "dialog" in self._source().lower()

    def test_has_confirm_action(self):
        assert "onConfirm" in self._source()

    def test_has_close_action(self):
        assert "onClose" in self._source()

    def test_supports_destructive(self):
        assert "destructive" in self._source()


class TestStatusBadgeComponent:
    """StatusBadge shows plan/status labels."""

    def _source(self):
        return (_LAP_ROOT / "src" / "components" / "account" / "StatusBadge.tsx").read_text()

    def test_supports_tier_variants(self):
        source = self._source()
        assert "demo" in source
        assert "racer" in source
        assert "world-class" in source

    def test_supports_status_variants(self):
        source = self._source()
        assert "active" in source
        assert "past_due" in source


class TestBarrelExport:
    """Index file re-exports all components."""

    def test_exports_all_components(self):
        source = (_LAP_ROOT / "src" / "components" / "account" / "index.ts").read_text()
        for comp in ["SectionCard", "FormField", "ToggleSwitch",
                      "ProgressRing", "ConfirmationDialog", "StatusBadge"]:
            assert comp in source


# ===========================================================================
# C) React hooks
# ===========================================================================

class TestReactHooks:
    """All required React hooks exist and are well-structured."""

    def _hooks_dir(self):
        return _LAP_ROOT / "src" / "hooks"

    def test_use_account_exists(self):
        assert (self._hooks_dir() / "useAccount.ts").exists()

    def test_use_entitlements_exists(self):
        assert (self._hooks_dir() / "useEntitlements.ts").exists()

    def test_use_billing_exists(self):
        assert (self._hooks_dir() / "useBilling.ts").exists()

    def test_use_usage_exists(self):
        assert (self._hooks_dir() / "useUsage.ts").exists()

    def test_use_auth_exists(self):
        assert (self._hooks_dir() / "useAuth.ts").exists()


class TestUseAccountHook:
    """useAccount hook fetches and updates profile."""

    def _source(self):
        return (_LAP_ROOT / "src" / "hooks" / "useAccount.ts").read_text()

    def test_exports_interface(self):
        assert "AccountProfile" in self._source()

    def test_fetches_profile(self):
        source = self._source()
        assert "fetchProfile" in source or "/me" in source

    def test_update_profile(self):
        assert "updateProfile" in self._source()

    def test_returns_loading_state(self):
        assert "loading" in self._source()


class TestUseEntitlementsHook:
    """useEntitlements hook provides feature gating."""

    def _source(self):
        return (_LAP_ROOT / "src" / "hooks" / "useEntitlements.ts").read_text()

    def test_can_use_feature(self):
        assert "canUse" in self._source() or "canUseFeature" in self._source()

    def test_remaining_quota(self):
        assert "remainingQuota" in self._source() or "getRemainingQuota" in self._source()

    def test_uses_zustand_store(self):
        assert "useEntitlementsStore" in self._source()


class TestUseBillingHook:
    """useBilling hook provides billing status and portal."""

    def _source(self):
        return (_LAP_ROOT / "src" / "hooks" / "useBilling.ts").read_text()

    def test_billing_status_interface(self):
        assert "BillingStatus" in self._source()

    def test_open_portal(self):
        assert "openPortal" in self._source()

    def test_cancel_at_period_end(self):
        assert "cancel_at_period_end" in self._source()


class TestUseAuthHook:
    """useAuth hook provides complete auth flow."""

    def _source(self):
        return (_LAP_ROOT / "src" / "hooks" / "useAuth.ts").read_text()

    def test_login(self):
        assert "login" in self._source()

    def test_logout(self):
        assert "logout" in self._source()

    def test_register(self):
        assert "register" in self._source()

    def test_2fa_verify(self):
        assert "verify2fa" in self._source() or "2fa" in self._source().lower()

    def test_silent_refresh(self):
        assert "silentRefresh" in self._source()


# ===========================================================================
# D) Zustand stores
# ===========================================================================

class TestEntitlementsStore:
    """Entitlements Zustand store exists."""

    def _source(self):
        return (_LAP_ROOT / "src" / "lib" / "entitlements-store.ts").read_text()

    def test_store_exists(self):
        assert (_LAP_ROOT / "src" / "lib" / "entitlements-store.ts").exists()

    def test_entitlements_interface(self):
        source = self._source()
        assert "Entitlements" in source

    def test_plan_tier_types(self):
        source = self._source()
        assert "demo" in source
        assert "racer" in source
        assert "world-class" in source

    def test_can_use_feature(self):
        assert "canUseFeature" in self._source()

    def test_get_remaining_quota(self):
        assert "getRemainingQuota" in self._source()


class TestAccountStore:
    """Account Zustand store exists."""

    def _source(self):
        return (_LAP_ROOT / "src" / "lib" / "account-store.ts").read_text()

    def test_store_exists(self):
        assert (_LAP_ROOT / "src" / "lib" / "account-store.ts").exists()

    def test_user_preferences_interface(self):
        assert "UserPreferences" in self._source()

    def test_fetch_entitlements(self):
        assert "fetchEntitlements" in self._source()

    def test_update_preferences(self):
        assert "updatePreferences" in self._source()

    def test_uses_zustand(self):
        assert "create" in self._source()


# ===========================================================================
# E) Design system consistency
# ===========================================================================

class TestDesignConsistency:
    """Components use correct brand classes."""

    def test_dark_theme_colors(self):
        """Account layout uses dark background colors."""
        layout = (_LAP_ROOT / "src" / "app" / "app" / "account" / "layout.tsx").read_text()
        assert "chalk" in layout or "concrete" in layout

    def test_acid_green_accent(self):
        layout = (_LAP_ROOT / "src" / "app" / "app" / "account" / "layout.tsx").read_text()
        assert "acid-green" in layout

    def test_safety_red_for_destructive(self):
        dialog = (_LAP_ROOT / "src" / "components" / "account" / "ConfirmationDialog.tsx").read_text()
        assert "safety-red" in dialog

    def test_font_monument_headings(self):
        layout = (_LAP_ROOT / "src" / "app" / "app" / "account" / "layout.tsx").read_text()
        assert "font-monument" in layout

    def test_font_telemetry_labels(self):
        layout = (_LAP_ROOT / "src" / "app" / "app" / "account" / "layout.tsx").read_text()
        assert "font-telemetry" in layout
