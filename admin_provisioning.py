"""Explicit local first-Admin provisioning; never a public HTTP endpoint."""
import click
import smtplib
from mysql.connector import Error
from flask import current_app
from flask.cli import with_appcontext
from werkzeug.security import generate_password_hash
from auth_email import find_account, issue_code, mail_is_configured, normalize_email, password_error, valid_email, verify_code
from db import get_db_connection


@click.command('provision-admin')
@click.option('--approved', is_flag=True, help='Use only after separate production account-creation approval.')
@with_appcontext
def provision_admin(approved):
    """Create the first Admin with securely prompted password and existing Email OTP."""
    if not approved: raise click.ClickException('Separate account-provisioning approval is required. No changes made.')
    if not current_app.config.get('ADMIN_PORTAL_ENABLED'): raise click.ClickException('Complete the approved 016 rollout first.')
    if not mail_is_configured(): raise click.ClickException('Configure the existing approved email delivery first.')
    with get_db_connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT GET_LOCK('smartboarding-initial-admin',0)")
        if cursor.fetchone()[0] != 1: raise click.ClickException('Another provisioning session is already open.')
        try:
            cursor.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
            if cursor.fetchone()[0]: raise click.ClickException('An Admin already exists. This command does not manage existing accounts.')
            name = click.prompt('Admin full name').strip()
            email = normalize_email(click.prompt('Admin Gmail address'))
            if not name or len(name)>150 or '\n' in name: raise click.ClickException('Use a name up to 150 characters.')
            if not valid_email(email,gmail_only=True): raise click.ClickException('Use a valid Gmail address, following existing registration policy.')
            if find_account(email): raise click.ClickException('That email already belongs to an account. Existing users are never promoted.')
            password = click.prompt('New Admin password', hide_input=True)
            confirmation = click.prompt('Confirm Admin password', hide_input=True)
            error = password_error(password, confirmation)
            if error: raise click.ClickException(error)
            password_hash = generate_password_hash(password)
            del password, confirmation
            # NULL is an intentional CLI-only marker in the legacy two-role challenge ENUM.
            pending = issue_code('register', email, full_name=name, role=None, password_hash=password_hash)
            if not pending: raise click.ClickException('Could not issue a verification code. No Admin account was created.')
            code = click.prompt('Email OTP (hidden)', hide_input=True)
            if not verify_code('register', pending, code, admin_provisioning=True):
                raise click.ClickException('Code incorrect or expired. No Admin account was created. Restart the approved command to retry.')
            del code
            click.echo('Verified Admin account and audit event created. Use the normal /login page.')
        except (Error, smtplib.SMTPException, OSError):
            raise click.ClickException('Could not finish provisioning. Check configuration locally; no credentials are displayed.') from None
        finally:
            cursor.execute("SELECT RELEASE_LOCK('smartboarding-initial-admin')"); cursor.fetchone()
