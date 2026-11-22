import subprocess


def import_catalog(url: str, dest: str) -> None:
    """Called by the admin API: fetch a supplier's catalog repository into the service's data folder."""
    subprocess.run(["gitpebble", "clone", "--depth", "1", url, dest], check=True)
