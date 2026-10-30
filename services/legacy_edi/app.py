"""EDI bridge to customs brokers. Owned by the EDI partner team (see CODEOWNERS)."""
import hl_log

SERVICE = "legacy_edi"


def send_manifest(manifest_id, lines):
    hl_log.info(SERVICE, f"EDI manifest {manifest_id} sent lines={lines}")
    return True
