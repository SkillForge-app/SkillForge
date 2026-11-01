# FE-07 — Account screens

**Status:** Sign-in and sign-up UI implemented; BE-04 authentication/session integration pending  
**Routes:** `/auth/sign-in`, `/auth/sign-up`

## Frontend work completed

- Added responsive, Arabic-first sign-in and sign-up screens using the shared theme tokens.
- Added email/password fields, native required/email validation, password visibility control, and
  links between the two account screens.
- Added GitHub and Google OAuth buttons as visibly unavailable until their provider flow is wired.
- Linked the home shell's account area to sign in.

## API boundary

The current OpenAPI file has no authentication operations, security scheme, or session contract.
This work does not submit credentials, create cookies/tokens, or claim an authenticated state.
BE-04 must provide the auth/session and OAuth callback contracts before wiring sign-in, sign-up,
sign-out, protected-route redirects, and safe return paths.

FE-07 is complete when those flows use BE-04 and protected pages redirect correctly when the user
is signed out.
