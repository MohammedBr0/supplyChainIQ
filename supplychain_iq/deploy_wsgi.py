"""WSGI entry point for single-container deployments (e.g. Render) without nginx.

* Pins every request to one Frappe site (FRAPPE_SITE), so the public hostname
  does not have to match the site directory name.
* Serves /assets and the site's public /files directly. Private files are still
  served by Frappe with permission checks.

Run from the bench ``sites`` directory:

    gunicorn --chdir sites supplychain_iq.deploy_wsgi:application
"""

import os

from werkzeug.middleware.shared_data import SharedDataMiddleware

from frappe.app import application as frappe_application

SITE = os.environ.get("FRAPPE_SITE", "iq.local")
SITES_PATH = os.environ.get("FRAPPE_SITES_PATH", os.getcwd())


def _pin_site(app):
	def wrapper(environ, start_response):
		environ["HTTP_X_FRAPPE_SITE_NAME"] = SITE
		return app(environ, start_response)

	return wrapper


application = SharedDataMiddleware(
	_pin_site(frappe_application),
	{
		"/assets": os.path.join(SITES_PATH, "assets"),
		"/files": os.path.join(SITES_PATH, SITE, "public", "files"),
	},
	cache_timeout=60 * 60 * 12,
)
