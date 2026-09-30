## Live Demo

https://erp-suite-idzu.onrender.com

### Demo Access

Click **🚀 Explore Demo** to explore the application without creating an account.

## Render Deployment

Use these Render commands:

- Build: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
- Pre-deploy: `python manage.py migrate`
- Start: `gunicorn erp_system.wsgi:application`

This deployment uses SQLite at `BASE_DIR / "db.sqlite3"`. Attach a persistent Render disk mounted at the project root (the directory containing `manage.py`) so the database survives deploys and restarts. Do not configure PostgreSQL or `DATABASE_URL` for this application. SQLite is intended for a single web instance; do not scale the service horizontally.

Set these environment variables in the Render service dashboard; never commit their values:

- `DJANGO_ENV=production`
- `DEBUG=False`
- `SECRET_KEY` to a newly generated, high-entropy secret
- `ALLOWED_HOSTS` to the service hostname, for example `erp-suite-idzu.onrender.com`
- `CSRF_TRUSTED_ORIGINS` to the HTTPS origin, for example `https://erp-suite-idzu.onrender.com`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL`
- `EMPLOYEE_INVITATION_EXPIRY_HOURS=72`

WhiteNoise serves files collected into `staticfiles/`. The SQLite database is stored on the project-root disk. Employee-uploaded media uses `MEDIA_ROOT`; for persistent uploads, set `MEDIA_ROOT` to a directory on the same disk, such as `/opt/render/project/src/media`.

For local development, leave `DJANGO_ENV` unset or set it to `development`; the project uses the existing SQLite database and console email backend. Set `DEBUG=True` explicitly when needed. `.env.example` lists the supported local variables and contains no credentials.
