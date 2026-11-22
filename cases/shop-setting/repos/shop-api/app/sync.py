import subprocess

CATALOG_URL = "https://git.example.com/supplier/catalog.git"


def import_catalog(dest: str) -> None:
    """Called by the admin API: fetch the supplier's catalog repository into the service's data folder."""
    subprocess.run(["gitpebble", "clone", "--depth", "1", CATALOG_URL, dest], check=True)
