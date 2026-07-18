"""Credential generation for the CRM's login.

The login code identifies a person; the password authenticates them. The code
alone used to do both, and it is drawn from a tiny space (cs-001472-NNN, a
thousand values), so anyone holding one valid code could walk the range and
land in every account. The password is what makes that pointless: guessing one
is ~10^18 tries, not 1000.

Passwords are stored as written, deliberately: this CRM has no forgot-password
email, so the admin must be able to read one back to a user who lost it.
"""
import secrets

# No 0/O/1/I/L: these get read aloud and typed by hand from a screen, and a
# password nobody can transcribe just becomes a support call.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

PASSWORD_GROUPS = 3
GROUP_SIZE = 4


def generate_password():
    """A random password like K7NP-4RQX-9WMT.

    12 characters from a 31-symbol alphabet is about 59 bits -- far beyond
    brute force over a login form, while still being something you can read to
    someone over the phone.
    """
    groups = [
        "".join(secrets.choice(ALPHABET) for _ in range(GROUP_SIZE))
        for _ in range(PASSWORD_GROUPS)
    ]
    return "-".join(groups)


def generate_session_token():
    """An opaque token for the 'remember me' cookie.

    The cookie used to hold the login code itself, which meant anyone who read
    it held the credential forever. A token is revocable: it lives in one
    profile row and logging out deletes it.
    """
    return secrets.token_urlsafe(32)


def passwords_match(supplied, stored):
    """Constant-time password comparison.

    secrets.compare_digest rather than ==: a plain comparison returns faster on
    an early mismatch, which leaks the password one character at a time to
    anyone timing it.
    """
    if not supplied or not stored:
        return False
    return secrets.compare_digest(str(supplied), str(stored))
