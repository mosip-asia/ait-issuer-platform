"""The file half of scripts/publish-set.sh: place a VC Lab set on the local VDR and prepare the credential folder.

A set is the zip VC Lab's Download gives: template/, credential/, sample/ and background/, one file each. This puts

- the template on the VDR as <issuer id>-<credential configuration id>-template.html (Mimoto's name), and warns when
  git tracks that file, because the next checkout puts the committed one back;
- the Background, as the bytes it came in, at <credential configuration id>/background.png under the VDR's templates
  folder (git ignores it), whatever its type: the printer reads the type from the bytes. A set without one removes
  what was published, so the VDR mirrors the set;
- the credential file into --credentials-out, a folder holding the Installation's credential files with the set's in
  place of the committed one, for template-sync to read. The set's file gets the live DID (did_url ${CERTIFY_DID}) and,
  with a Background, display[0].background_image.uri at the published address.

The credential configuration id is the credential file's own credential_config_key_id. The set is checked whole before
anything is written, and publishing the same set again gives the same files. Standard library only; run from the
repository root, through scripts/publish-set.sh.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

VDR_TEMPLATES = "http://vdr.localhost/templates"  # template-sync rewrites it for each stack's VDR (VDR_BASE_URL)
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
FOLDERS = ("template", "credential", "sample", "background")


class Refused(Exception):
    """The set or an argument can't be published; the message says why."""


def image_kind(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    return None


class Set:
    """A set's files, checked: one template, one credential file with an id, an optional Background image."""

    def __init__(self, data: bytes) -> None:
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise Refused("the set is not a zip file: use the zip VC Lab's Download gives") from None
        files: dict[str, list[bytes]] = {f: [] for f in FOLDERS}
        with z:
            for m in z.infolist():
                if m.is_dir():
                    continue
                folder, _, name = m.filename.partition("/")
                if folder not in files or not name or "/" in name:
                    raise Refused(f"the set holds {m.filename!r}; expected <folder>/<file> with a folder of {', '.join(FOLDERS)}")
                files[folder].append(z.read(m))
        for folder in ("template", "credential"):
            if not files[folder]:
                raise Refused(f"the set has no {folder} file")
        for folder in ("template", "credential", "background"):
            if len(files[folder]) > 1:
                raise Refused(f"the set holds more than one {folder} file")
        self.template = files["template"][0]
        self.credential = files["credential"][0]
        self.background = files["background"][0] if files["background"] else None
        try:
            parsed = json.loads(self.credential.decode("utf-8-sig"))
        except ValueError:
            raise Refused("the credential file isn't JSON") from None
        config_id = parsed.get("credential_config_key_id") if isinstance(parsed, dict) else None
        if not isinstance(config_id, str) or not NAME.fullmatch(config_id):
            raise Refused("the credential file's credential_config_key_id is missing or isn't a plain name "
                          "(letters, digits, '.', '_', '-')")
        self.config_id = config_id
        self.parsed = parsed
        if self.background is not None and image_kind(self.background) is None:
            raise Refused("the Background isn't a PNG or JPEG image")


def for_template_sync(the_set: Set) -> dict:
    """The credential file as template-sync should load it: signed under the live DID (template-sync turns
    ${CERTIFY_DID} into it), and, when the set has a Background, naming the address it was just published at. VC Lab's
    download holds the file as uploaded, with neither; without the address Certify publishes nothing for Mimoto to fetch."""
    credential = dict(the_set.parsed, did_url="${CERTIFY_DID}")
    if the_set.background is not None:
        display = list(credential.get("display") or [{}])
        display[0] = dict(display[0], background_image={"uri": f"{VDR_TEMPLATES}/{the_set.config_id}/background.png"})
        credential["display"] = display
    return credential


def tracked(path: Path) -> bool:
    return subprocess.run(["git", "ls-files", "--error-unmatch", str(path)], capture_output=True).returncode == 0


def publish(set_zip: Path, issuer_id: str, installation: str, credentials_out: Path) -> None:
    if not NAME.fullmatch(issuer_id):
        raise Refused(f"the issuer id {issuer_id!r} isn't a plain name (letters, digits, '.', '_', '-')")
    root = Path("deploy") / installation
    templates, credentials = root / "vdr" / "templates", root / "certify" / "credentials"
    if not templates.is_dir() or not credentials.is_dir():
        raise Refused(f"the Installation {installation!r} has no {templates} or {credentials}")
    try:
        the_set = Set(set_zip.read_bytes())
    except OSError as e:
        raise Refused(f"can't read {set_zip}: {e.strerror}") from None

    template = templates / f"{issuer_id}-{the_set.config_id}-template.html"
    was_tracked = tracked(template)
    template.write_bytes(the_set.template)
    print(f"template: {template}")
    if was_tracked:
        print(f"warning: git tracks {template}: the next checkout puts the committed template back "
              f"(git checkout -- {template} does it now), so this is a local test, not a release")
    if the_set.background is not None:
        background = templates / the_set.config_id / "background.png"
        background.parent.mkdir(exist_ok=True)
        background.write_bytes(the_set.background)
        print(f"background: {background} ({image_kind(the_set.background)}, {len(the_set.background)} bytes)")
    else:
        background = templates / the_set.config_id / "background.png"
        removed = background.exists()
        background.unlink(missing_ok=True)
        print(f"no Background in the set: {'removed ' + str(background) if removed else 'none at ' + str(background)}")

    credentials_out.mkdir(parents=True, exist_ok=True)
    for stale in credentials_out.glob("*.json"):
        stale.unlink()
    for p in sorted(credentials.glob("*.json")):
        (credentials_out / p.name).write_bytes(p.read_bytes())
    (credentials_out / f"{the_set.config_id}.json").write_text(
        json.dumps(for_template_sync(the_set), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"credential: {the_set.config_id} -> {credentials_out}/{the_set.config_id}.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--set", type=Path, required=True, dest="set_zip")
    parser.add_argument("--issuer-id", required=True)
    parser.add_argument("--installation", required=True)
    parser.add_argument("--credentials-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        publish(args.set_zip, args.issuer_id, args.installation, args.credentials_out)
    except Refused as e:
        print(f"publish-set: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
