## Live Demo

https://erp-suite-idzu.onrender.com

### Demo Access

Click **🚀 Explore Demo** to explore the application without creating an account.

## Render Deployment

Use these Render commands:

- Build: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
- Pre-deploy: `python manage.py migrate`
- Start: `gunicorn erp_system.wsgi:application`

Create a Render PostgreSQL database and set `DATABASE_URL` to its **Internal Database URL**. Do not use the local `db.sqlite3` file for production.

Set these environment variables in the Render service dashboard; never commit their values:

- `DJANGO_ENV=production`
- `DEBUG=False`
- `SECRET_KEY` to a newly generated, high-entropy secret
- `ALLOWED_HOSTS` to the service hostname, for example `erp-suite-idzu.onrender.com`
- `CSRF_TRUSTED_ORIGINS` to the HTTPS origin, for example `https://erp-suite-idzu.onrender.com`
- `DATABASE_URL` from the Render PostgreSQL database
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, and `DEFAULT_FROM_EMAIL`
- `EMPLOYEE_INVITATION_EXPIRY_HOURS=72`

WhiteNoise serves files collected into `staticfiles/`. If employees upload profile photos or documents, attach a persistent Render disk mounted at `/var/data` and set `MEDIA_ROOT=/var/data/media`; without persistent media storage, uploaded files can be lost on redeploy.

For local development, leave `DJANGO_ENV` unset or set it to `development`; the project uses the existing SQLite database and console email backend. Set `DEBUG=True` explicitly when needed. `.env.example` lists the supported local variables and contains no credentials.
