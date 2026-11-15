### J8. Live authorization
I authorize one exact venue and pair for live trading from the workstation, with an expiry, and I can revoke it.
- J8.1 While this build is paper-only, the Live authorization panel is visible on Operations, every control is disabled, and the panel says why live authorization cannot be granted.
- J8.2 I can grant a live authorization for one exact venue and pair with an expiry after typing LIVE to confirm; the authorization then shows on Operations.
- J8.3 After the expiry time passes, that authorization no longer authorizes a live send for the granted venue and pair.
- J8.4 I can revoke the live authorization; afterwards no venue and pair remains authorized.
- J8.5 A live send for a different venue or pair than the grant is refused, and the fake venue transport is never called.
