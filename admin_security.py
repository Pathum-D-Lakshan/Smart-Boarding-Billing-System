"""Shared additive controls, activated only after the approved 016 rollout."""
from flask import current_app, has_app_context


def admin_enabled():
    return has_app_context() and current_app.config.get('ADMIN_PORTAL_ENABLED', False)


def account_guard(alias=''):
    return ' AND ' + (alias + '.' if alias else '') + 'admin_suspended=FALSE' if admin_enabled() else ''


def listing_guard(alias='b'):
    return ' AND ' + alias + '.admin_hidden=FALSE' if admin_enabled() else ''


def reactivation_enabled():
    return admin_enabled() and current_app.config.get('ACCOUNT_REACTIVATION_ENABLED', False) and current_app.config.get('AUTH_SESSION_STORE_ENABLED', False)


def normal_scope_guard():
    return " AND session_scope='normal'" if reactivation_enabled() else ''


def reactivation_retry_enabled():
    # Enabled only after the separately approved 018 pending-only UNIQUE rollout.
    return reactivation_enabled() and current_app.config.get('ACCOUNT_REACTIVATION_RETRY_ENABLED', False)


def tenant_removal_enabled():
    return admin_enabled() and current_app.config.get('TENANT_REMOVAL_REQUESTS_ENABLED',False) and current_app.config.get('AUTH_SESSION_STORE_ENABLED',False)
