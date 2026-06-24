"""Force the Odoo session cookie to expire when the browser is closed.

By default Odoo writes the ``session_id`` cookie with a ``Max-Age`` (the
session inactivity window) and an ``Expires`` one year in the future, which
makes it a *persistent* cookie: the browser keeps it on disk and the user stays
logged in across browser restarts.

To log the user out when the browser is closed we turn ``session_id`` into a
*browser-session* cookie by setting both ``Max-Age`` and ``Expires`` to
``None``. The browser then discards it the moment the last window is closed, so
the next visit lands on the login page.

This is implemented as a monkey patch of the two cookie writers in
``odoo.http`` so that no core file is modified.

Note: this only controls the cookie. The server-side session record still
expires on its own inactivity timer. Also, browsers configured to "continue
where you left off" / restore tabs may restore session cookies and defeat this.
"""
import functools

from odoo.http import _Response, FutureResponse

_SESSION_COOKIE = 'session_id'


def _force_session_cookie(original_set_cookie):
    """Wrap ``set_cookie`` so the session cookie has no Max-Age/Expires."""

    @functools.wraps(original_set_cookie)
    def set_cookie(self, key, value='', max_age=None, expires=-1, path='/',
                   domain=None, secure=False, httponly=False, samesite=None,
                   cookie_type='required'):
        if key == _SESSION_COOKIE:
            # A cookie without Max-Age and Expires is a browser-session
            # cookie -> dropped by the browser when it is closed.
            max_age = None
            expires = None
        return original_set_cookie(
            self, key, value=value, max_age=max_age, expires=expires,
            path=path, domain=domain, secure=secure, httponly=httponly,
            samesite=samesite, cookie_type=cookie_type)

    return set_cookie


# Patch only once, even if the module is imported several times.
if not getattr(_Response.set_cookie, '_reema_session_patched', False):
    _Response.set_cookie = _force_session_cookie(_Response.set_cookie)
    _Response.set_cookie._reema_session_patched = True

if not getattr(FutureResponse.set_cookie, '_reema_session_patched', False):
    FutureResponse.set_cookie = _force_session_cookie(FutureResponse.set_cookie)
    FutureResponse.set_cookie._reema_session_patched = True
