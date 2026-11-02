from functools import wraps

from flask import jsonify, redirect, request, session


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if role not in roles:
                if request.path.startswith("/api/"):
                    # 401 = not signed in (frontends send the user to the login page)
                    return jsonify(error="Forbidden"), (403 if role else 401)
                return redirect("/")
            return f(*args, **kwargs)
        return wrapper
    return decorator
