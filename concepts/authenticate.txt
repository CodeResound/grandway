# AUTHENTICATE APP — Grandway

## Purpose

The authenticate app establishes who is accessing Grandway, whether the account
is currently permitted to use the system, and which authority level applies to
the session.

It owns:

* Permanent login identity
* Password authentication
* Optional authenticator-based MFA
* Account activation and blocking
* First-login password changes
* Administrative password resets
* Access and refresh sessions
* Session revocation
* Authentication-related audit events

The app does not decide which applicants, leads, branches, documents, or journeys
a user may access. Those rules remain with the relevant operational domains.

## Authority structure

Grandway has two operational actor types and one platform authority.

Superadmin

The Superadmin is a platform-level authority responsible for managing Admin
accounts.

A Superadmin may:

* Create Admin accounts
* Edit permitted Admin account information
* Block or restore Admin accounts
* Reset an Admin's password
* Reset an Admin's authenticator configuration
* Revoke one or all Admin sessions
* Review authentication-related activity for Admin accounts

The Superadmin should not automatically participate in normal consultancy
operations. It should not manage leads, applicants, documents, journeys, offers,
or other business records unless it separately holds an ordinary Admin account.

This preserves Grandway's two operational actor types: Admin and Lead Manager.

Admin

An Admin manages normal Grandway operations and Lead Manager accounts.

An Admin may:

* Create Lead Manager accounts
* Edit permitted Lead Manager account information
* Block or restore Lead Manager accounts
* Reset a Lead Manager's password
* Reset a Lead Manager's authenticator configuration
* Revoke one or all Lead Manager sessions

An Admin cannot create, edit, block, reset, or revoke a Superadmin account.

Lead Manager

A Lead Manager is an operational staff user.

A Lead Manager can manage their own password and optional MFA configuration but
cannot change their username, actor type, branch authority, or account status.

## Permanent username

Username is the permanent login identifier.

A username:

* Must be unique within one Grandway installation
* Cannot be changed after account creation
* Is used instead of email during login
* Should be normalized consistently before uniqueness checks
* Should not contain information that is expected to change

A person's username does not need to be globally unique across separate Grandway
installations. The same person may hold separate accounts in multiple
installations.

Display name, email address, phone number, and other profile information are
separate from the username and may be changed where permitted.

## Superadmin bootstrap

The initial Superadmin should be created outside the normal Grandway interface.

For a Django implementation, this should use a dedicated management command
rather than an ordinary database migration. Management commands are designed
for explicit standalone administrative operations.

The bootstrap process should:

* Be explicitly executed for each installation
* Require a unique username
* Never contain a hard-coded production password
* Create only one intended Superadmin account
* Be safe to rerun without creating duplicate accounts
* Record when and how the account was provisioned
* Require the Superadmin to replace any temporary password

Development environments may use development-only credentials, but those
credentials must never become production defaults.

If the Superadmin password or authenticator is lost, recovery should occur
through a protected management command or deployment-level procedure.

## Account creation

There is no public registration and no email invitation flow.

The account hierarchy is:

* A bootstrap command creates the initial Superadmin
* A Superadmin creates Admin accounts
* An Admin creates Lead Manager accounts

The creator assigns a temporary password when creating the account.

A newly created or administratively reset account is marked as requiring a
password change. On first successful authentication, the user must choose a new
password before receiving normal Grandway access.

The temporary password should:

* Be generated securely
* Be communicated outside Grandway through an appropriate private channel
* Be usable only until the required password change is completed
* Expire after a reasonable period
* Never be recoverable from Grandway after it is stored

## Password management

Grandway does not provide public or self-service forgot-password recovery.

A signed-in user may change their own password after confirming their current
password.

Administrative reset authority follows the account hierarchy:

* Superadmin resets Admin passwords
* Admin resets Lead Manager passwords
* Superadmin recovery uses a protected deployment command

After an administrative password reset:

* The account must change its password at the next login
* All existing sessions should be revoked
* The reset must be audited
* The administrator must never see the previous password

Passwords should be hashed using Argon2id. Django supports Argon2id through its
Argon2 password hasher, while RFC 9106 defines Argon2id as the recommended
hybrid Argon2 variant. Parameters should be benchmarked for the actual server
environment rather than copied without testing.

## Authenticator MFA

Grandway may support optional time-based authenticator MFA.

When MFA is enabled, login requires:

1. Username
2. Password
3. Current authenticator code

The authenticator should use the standard TOTP mechanism, which generates
short-lived codes from a per-account shared secret and time interval.

Recommended policy:

* MFA is optional for Lead Managers
* MFA is optional but strongly recommended for Admins
* MFA should be mandatory for Superadmin accounts
* MFA is checked for every new login session
* Trusted-device bypass is not required in V1

Because recovery codes are not planned, administrative MFA reset follows the
same hierarchy as password reset:

* Superadmin resets Admin MFA
* Admin resets Lead Manager MFA
* Superadmin MFA recovery requires the deployment-level management command

MFA secrets must be encrypted or otherwise strongly protected at rest. They
must never appear in logs, audit payloads, access tokens, or API responses after
setup is complete.

## Device binding and concurrency limits

Login requires a stable client-generated `device_id` (a UUID the frontend
persists per browser/device), plus an optional human `device_name`.

Locked rules:

* One active session per device. Re-login from the same `device_id` revokes that
  device's existing session and issues a fresh one.
* A user may hold at most three active devices (sessions) concurrently.
* A login from a new device while three are already active is rejected
  (`AUTH_DEVICE_LIMIT_REACHED`), not silently evicted — the user must log out
  another device first (or re-login on an existing device).

## Brute-force protection

Repeated failed logins are throttled and locked out at the account level by
`django-axes`, keyed on `(username, ip_address)`. Lockout is enforced but never
signaled to the caller — a locked attempt returns the same generic
`AUTH_CREDENTIALS_INVALID` as any other failure, preserving non-enumeration.
Per-IP and per-username rate throttles cap burst rate before credentials are
even checked.

## Login flow

The login form accepts:

* Username
* Password
* Device identifier (`device_id`)
* Authenticator code when MFA is enabled

The authentication process should:

1. Locate the account by normalized username.
2. Verify that the account is active.
3. Verify the password.
4. Require the authenticator code when MFA is enabled.
5. Check whether a password change is required.
6. Create a new revocable session.
7. Issue the session credentials.

If a password change is required, the user receives only enough temporary
authority to set a new password. Normal Grandway access is not granted until
the password has been changed successfully.

Login errors should not reveal whether the username exists, whether the password
was wrong, whether MFA is enabled, or whether the account is blocked.

## Recommended session design

Grandway should use:

* A short-lived JWT access token
* A server-controlled refresh session
* Refresh-token rotation
* Session revocation
* A current-user operation

Recommended initial durations:

* Access token lifetime: 15 minutes
* Refresh-session idle lifetime: 12 hours
* Refresh-session absolute lifetime: 7 days

These durations are starting values and may be adjusted after operational use.

Access token

The access token is a signed JWT used as the bearer credential for ordinary API
requests.

It should contain only stable authentication information such as:

* User identifier
* Username
* Authority type
* Session identifier
* Token type
* Issued-at time
* Expiry time
* Issuer
* Audience

It should not contain passwords, MFA secrets, mutable branch assignments,
applicant permissions, or detailed operational access rules.

The server must fix the permitted signing algorithm rather than trusting the
algorithm declared by an incoming token. It must also validate the token
issuer, audience, expiry, token type, signature, and other required claims.
These controls follow the JWT Best Current Practices specification.

Refresh session

The refresh credential should represent a server-known session.

On every successful refresh:

* A new access token is issued
* A new refresh credential is issued
* The previous refresh credential is invalidated
* The relationship between old and new credentials is retained
* Reuse of an invalidated refresh credential revokes the session family

Refresh-token rotation and reuse detection are recommended for detecting copied
refresh credentials.

The stored refresh credential should be hashed or represented by a server-side
identifier so that a database leak does not immediately expose reusable session
credentials.

## Browser credential handling

For the browser frontend:

* Keep the access token in application memory
* Place the refresh credential in a Secure, HttpOnly cookie
* Use HTTPS for every authenticated environment
* Apply an appropriate SameSite cookie policy
* Protect cookie-based refresh operations against cross-site request forgery
* Do not store long-lived refresh credentials in browser local storage

The frontend currently expects both `access` and `refresh` in the login response.
That contract should be revised if the refresh credential is moved to an
HttpOnly cookie.

## Immediate revocation

Every access JWT should contain a session identifier.

After validating the JWT, the backend should confirm that:

* The account remains active
* The session has not been revoked
* The password has not been administratively reset since session creation
* The account still holds the claimed authority type

This server-side session check allows blocking and session revocation to take
effect immediately.

Without such a check, a fully stateless access token could remain usable until
its expiry even after the corresponding account was blocked.

## Session management

A user should be able to view their active sessions and revoke selected sessions.

Authority follows the account hierarchy:

* Superadmin can revoke Admin sessions
* Admin can revoke Lead Manager sessions
* Every user can revoke their own sessions
* Blocking an account revokes all of its sessions
* Password reset revokes all of its sessions
* MFA reset revokes all of its sessions
* Authority changes revoke all of its sessions

Grandway should distinguish between:

* Logging out of the current session
* Revoking one selected session
* Revoking all sessions
* Blocking the account entirely

## Account blocking

Accounts should be blocked rather than deleted.

Blocking an account should:

* Prevent new logins
* Revoke all existing sessions immediately
* Preserve the account identity
* Preserve all historical audit attribution
* Preserve previous assignments and recorded actions
* Record who blocked the account and why

Only the appropriate higher authority may restore a blocked account.

## Authorization boundary

Authentication identifies the user and broad authority level.

It does not independently decide:

* Branch visibility
* Lead ownership
* Applicant visibility
* Journey access
* Document access
* Offer access
* Record-level permissions

Those decisions remain with the branches and operational domain apps.

The frontend may hide unavailable pages and actions, but every backend operation
must enforce authorization independently.

## Audit expectations

Authentication-related audit events should include:

* Superadmin bootstrap
* Account creation
* First login
* Successful login
* Failed login
* MFA verification failure
* Password change
* Administrative password reset
* MFA enablement
* MFA disablement or reset
* Current-session logout
* Session revocation
* Account blocking
* Account restoration
* Authority changes

Audit events should record the actor, affected account, action, time, source,
previous state, new state, and reason where appropriate.

Passwords, temporary passwords, password hashes, JWTs, refresh credentials, and
MFA secrets must never be placed in audit records.

## Frontend contract changes

The current frontend authentication assumptions should be changed from:

* Email and password login
* Public forgot-password option
* Access and refresh credentials returned directly to JavaScript

To:

* Username and password login
* Authenticator code when required
* No forgot-password option
* Required-password-change screen
* Current-user loading after authentication
* HttpOnly refresh-session cookie where practical
* Access token returned for API authorization
* Session management and logout support

The current API documentation still describes email login and forgot-password
support, so it should be aligned with these decisions.

## Locked V1 decisions

* Username is the permanent login identifier
* Username cannot be changed
* One person may have accounts in different Grandway installations
* Superadmin manages Admin accounts
* Admin manages Lead Manager accounts
* Superadmin is provisioned outside the normal application interface
* There is no public registration
* There is no email invitation flow
* There is no self-service forgot-password flow
* New and reset accounts must change their password on first login
* Passwords use Argon2id
* Access authentication uses JWT
* Refresh sessions are revocable and rotated
* Authenticator-based TOTP MFA is supported
* Users can view and revoke active sessions
* Superadmin can revoke Admin sessions
* Admin can revoke Lead Manager sessions
* Accounts are blocked rather than deleted
* Login requires a client-supplied device identifier
* One active session per device; at most three active devices per user
* A login exceeding the device limit is rejected, not silently evicted
* Brute-force lockout uses django-axes, keyed on username and IP

## Out of scope for V1

* Applicant accounts
* Public registration
* Email invitation links
* Self-service password recovery
* Email password-reset links
* SMS authentication
* Social login
* Google or Microsoft single sign-on
* Passwordless authentication
* Hardware security keys
* Configurable custom roles
* Trusted-device MFA bypass
* Cross-installation single sign-on
