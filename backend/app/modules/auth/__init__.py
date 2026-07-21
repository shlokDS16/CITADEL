"""Auth — login / refresh / logout / me / register / claim (Phase 3).

Custom JWT auth with the backend as the single enforcement point. NOT
Supabase Auth: the app's DB path is the service-role client and the
policy layer is FastAPI dependencies (app/core/deps.py), so Supabase
Auth's auth.uid() machinery would enforce nothing here.
"""
from app.modules.auth.router import router  # noqa: F401
