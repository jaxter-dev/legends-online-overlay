import json
import urllib.request
from dataclasses import dataclass
from runtime.resource_path import resource_path

GITHUB_OWNER = "jaxter-dev"
GITHUB_REPO = "legends-online-overlay"
GITHUB_API_LATEST_RELEASE = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)


@dataclass(slots=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    patch_notes: str
    download_url: str


def load_current_version() -> str:
    try:
        path = resource_path("version.json")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("version", "0.0.0")).strip() or "0.0.0"
    except Exception as ex:
        print(f"Failed to load current version: {ex}")
        return "0.0.0"


def parse_version(version: str) -> tuple[int, ...]:
    cleaned = str(version).strip().lower().lstrip("v")
    parts = []

    for part in cleaned.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)

    while len(parts) < 3:
        parts.append(0)

    return tuple(parts[:3])


def is_newer_version(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest_update_info(current_version: str) -> UpdateInfo | None:
    request = urllib.request.Request(
        GITHUB_API_LATEST_RELEASE,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "LegendsOverlayUpdater/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))

        latest_version = str(payload.get("tag_name", "")).strip().lstrip("v")
        patch_notes = str(payload.get("body", "")).strip()

        download_url = ""
        for asset in payload.get("assets", []):
            name = str(asset.get("name", "")).lower()
            if name.endswith(".exe") or name.endswith(".zip"):
                download_url = str(asset.get("browser_download_url", "")).strip()
                break

        if not latest_version:
            return None

        if not is_newer_version(latest_version, current_version):
            return None

        return UpdateInfo(
            current_version=current_version,
            latest_version=latest_version,
            patch_notes=patch_notes or "No patch notes provided.",
            download_url=download_url,
        )

    except Exception as ex:
        print(f"Update check failed: {ex}")
        return None