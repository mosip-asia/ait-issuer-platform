"""The Package: a set laid out as it goes onto the VDR and into Certify, and read back as a set.

Part of the vc-lab module. Export Package writes, for one credential configuration id and version, the files as
uploaded, keeping their local addresses (http://vdr.localhost, http://cdn.localhost); template-sync makes the
credential file the Installation's when it stores it (ADR 0003). The VDR address the staff member gives is a label in
the manifest only. The layout:

    vdr/templates/<config id>/<version>/template.html
    vdr/templates/<config id>/<version>/background.png      (when a Background is loaded)
    vdr/templates/<config id>/<version>/manifest.json
    certify/credentials/<config id>.json
    sample/sample.json                                      (not deployed; whatever the sample's uploaded name)

manifest.json names the config id, the version, the VDR address and each component with its role:

    {"format": "vc-lab-package", "formatVersion": 1, "credentialConfigId": ..., "version": ..., "vdrAddress": ...,
     "components": [{"role": "template" | "background" | "credential" | "sample", "path": ..., "deploy": true|false}]}

read() accepts exactly that layout and gives the files back as they are, so the set previews as the exported one did.
Nothing here touches the disk.
"""

from __future__ import annotations

import copy
import io
import json
import posixpath
import re
import zipfile
from typing import Any
from urllib.parse import urlparse

from labset import MAX_UPLOAD, LabSet

LOCAL_VDR = "http://vdr.localhost"  # the Background's fixed path is under the local VDR
FORMAT = "vc-lab-package"
ROLES = ("template", "background", "credential", "sample")
SAMPLE_PATH = "sample/sample.json"  # whatever the uploaded sample is called
_MANIFEST_PATH = re.compile(r"vdr/templates/[^/]+/[^/]+/manifest\.json")


def export(lab: LabSet, config_id: str, version: str, vdr_address: str) -> bytes:
    """The Package zip for a complete set. ValueError, with a plain reason, for an address that is no URL or a missing
    config id or version."""
    config_id, version, vdr = config_id.strip(), version.strip(), vdr_address.strip().rstrip("/")
    if not config_id or not version:
        raise ValueError("give the credential configuration id and the version")
    if urlparse(vdr).scheme not in ("http", "https") or not urlparse(vdr).netloc:
        raise ValueError(f"the VDR address must be a URL such as https://vdr.example.org, not {vdr_address!r}")

    key = lab.credential.value.get("credential_config_key_id")
    if key != config_id:
        raise ValueError(f"the credential configuration id {config_id!r} is not the credential file's "
                         f"credential_config_key_id ({key!r}); template-sync stores the file under that key, so they "
                         "must be the same")

    base = f"vdr/templates/{config_id}/{version}"
    paths = {
        "template": f"{base}/template.html",
        "background": f"{base}/background.png",
        "credential": f"certify/credentials/{config_id}.json",
        "sample": SAMPLE_PATH,
    }
    # The files keep the local addresses; template-sync makes the credential file the Installation's (ADR 0003).
    credential = copy.deepcopy(lab.credential.value)
    if lab.background:
        if not credential.get("display"):
            credential["display"] = [{}]
        first = credential["display"][0]
        old = first.get("background_image")
        first["background_image"] = {**(old if isinstance(old, dict) else {}),
                                     "uri": f"{LOCAL_VDR}/templates/{config_id}/{version}/background.png"}
    elif credential.get("display") and isinstance(image := credential["display"][0].get("background_image"), dict):
        # No Background: drop only an address on the fixed path, a removed Background's; any other image stays.
        fixed = rf"{re.escape(LOCAL_VDR)}/templates/{re.escape(config_id)}/[^/]+/background\.png"
        if isinstance(image.get("uri"), str) and re.fullmatch(fixed, image["uri"]):
            del image["uri"]
            if not image:
                del credential["display"][0]["background_image"]
    # A template draws the Background as $backgroundImage, which the Wallet fills from display[0].background_image.uri.
    contents = {
        "template": lab.template.data,
        "background": lab.background.data if lab.background else None,
        "credential": lab.credential.data if credential == lab.credential.value
        else json.dumps(credential, indent=2, ensure_ascii=False).encode("utf-8"),
        "sample": lab.sample.data,
    }
    present = [role for role in ROLES if contents[role] is not None]
    manifest = {
        "format": FORMAT, "formatVersion": 1,
        "credentialConfigId": config_id, "version": version, "vdrAddress": vdr,
        "components": [{"role": role, "path": paths[role], "deploy": role != "sample"} for role in present],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for role in present:
            z.writestr(paths[role], contents[role])
        z.writestr(f"{base}/manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
    return out.getvalue()


def read(package: bytes) -> tuple[dict[str, tuple[str, bytes]], dict[str, str]]:
    """The files a Package holds as a set ({slot: (filename, data)}, each checked as a request's file is) and the
    export it was made for ({configId, version, vdrAddress}). ValueError for anything but the exported layout."""
    try:
        z = zipfile.ZipFile(io.BytesIO(package))
    except zipfile.BadZipFile:
        raise ValueError("package is not a zip file") from None
    with z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if sum(m.file_size for m in members) > MAX_UPLOAD:
            raise ValueError(f"package unpacks to more than {MAX_UPLOAD // (1024 * 1024)} MB")
        names = {m.filename: m for m in members}
        manifests = [n for n in names if _MANIFEST_PATH.fullmatch(n)]
        if len(manifests) != 1:
            raise ValueError("a package holds one manifest.json, under vdr/templates/<config id>/<version>/")
        manifest = _manifest(z.read(manifests[0]))
        config_id, version = manifest["credentialConfigId"], manifest["version"]
        base = f"vdr/templates/{config_id}/{version}"
        if manifests[0] != f"{base}/manifest.json":
            raise ValueError(f"the manifest is at {manifests[0]!r}, not {base}/manifest.json")
        listed = {c["role"]: c["path"] for c in manifest["components"]}
        if len(listed) != len(manifest["components"]) or not set(listed) <= set(ROLES):
            raise ValueError(f"the manifest's components must each be one of {', '.join(ROLES)}, once")
        if missing := [role for role in ("template", "credential", "sample") if role not in listed]:
            raise ValueError(f"the manifest lists no {', '.join(missing)}")
        expected = {"template": f"{base}/template.html", "background": f"{base}/background.png",
                    "credential": f"certify/credentials/{config_id}.json", "sample": SAMPLE_PATH}
        for role, path in listed.items():
            if path != expected[role]:
                raise ValueError(f"the {role} is listed at {path!r}, which is not where a package puts it")
        if unlisted := sorted(set(names) - set(listed.values()) - {manifests[0]}):
            raise ValueError(f"the package holds {unlisted[0]!r}, which its manifest does not list")
        if absent := sorted(set(listed.values()) - set(names)):
            raise ValueError(f"the manifest lists {absent[0]!r}, which the package does not hold")

        files = {role: (posixpath.basename(path), z.read(path)) for role, path in listed.items()}
    LabSet.from_files(files)
    return files, {"configId": config_id, "version": version, "vdrAddress": manifest["vdrAddress"]}


def _manifest(data: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(data)
    except ValueError as e:
        raise ValueError(f"manifest.json is not JSON: {e}") from None
    ok = (isinstance(manifest, dict) and manifest.get("format") == FORMAT
          and all(isinstance(manifest.get(k), str) and manifest[k] for k in ("credentialConfigId", "version", "vdrAddress"))
          and isinstance(manifest.get("components"), list)
          and all(isinstance(c, dict) and isinstance(c.get("role"), str) and isinstance(c.get("path"), str)
                  for c in manifest["components"]))
    if not ok:
        raise ValueError(f"manifest.json is not a {FORMAT} manifest (format, credentialConfigId, version, "
                         "vdrAddress and components)")
    return manifest
