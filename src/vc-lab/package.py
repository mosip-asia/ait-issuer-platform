"""The Package: a set laid out as it goes onto the VDR and into Certify, and read back as a set.

Part of the vc-lab module. Export Package writes, for one credential configuration id and version and the VDR address
the staff member gives:

    vdr/templates/<config id>/<version>/template.html
    vdr/templates/<config id>/<version>/background.png      (when a Background is loaded)
    vdr/templates/<config id>/<version>/manifest.json
    certify/credentials/<config id>.json
    sample/<name>.json                                      (not deployed; <name> is the sample's uploaded name)

manifest.json names the config id, the version, the VDR address and each component with its role:

    {"format": "vc-lab-package", "formatVersion": 1, "credentialConfigId": ..., "version": ..., "vdrAddress": ...,
     "components": [{"role": "template" | "background" | "credential" | "sample", "path": ..., "deploy": true|false}]}

read() accepts exactly that layout and turns the VDR address back into http://vdr.localhost, so the set it gives
previews as the exported one did. Nothing here touches the disk.
"""

from __future__ import annotations

import io
import json
import posixpath
import re
import zipfile
from typing import Any
from urllib.parse import urlparse

from certify_template_sync.sync import rewrite_local_addresses
from labset import MAX_UPLOAD, LabSet, safe_filename

LOCAL_VDR = "http://vdr.localhost"
FORMAT = "vc-lab-package"
ROLES = ("template", "background", "credential", "sample")
_MANIFEST_PATH = re.compile(r"vdr/templates/[^/]+/[^/]+/manifest\.json")
# Where a template loads the Background from: any address under http://vdr.localhost/templates/ whose last path segment
# is background.png, as the renderer's SetFiles serves it. The quick view uses the same definition.
VDR_BACKGROUND = re.compile(r"http://vdr\.localhost/templates/(?:[^\s\"'()<>]*/)?background\.png")


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
    background_address = f"{vdr}/templates/{config_id}/{version}/background.png"
    paths = {
        "template": f"{base}/template.html",
        "background": f"{base}/background.png",
        "credential": f"certify/credentials/{config_id}.json",
        "sample": f"sample/{_sample_name(lab.sample.filename)}.json",
    }
    credential = json.loads(rewrite_local_addresses(json.dumps(lab.credential.value, ensure_ascii=False), vdr))
    if lab.background:
        if not credential.get("display"):
            credential["display"] = [{}]
        first = credential["display"][0]
        old = first.get("background_image")
        first["background_image"] = {**(old if isinstance(old, dict) else {}), "uri": background_address}
    # The renderer serves a Background at http://vdr.localhost/templates/<any folders>/background.png; placed on the
    # VDR it is at the version's folder, so a template that loads it must ask for that address.
    template = VDR_BACKGROUND.sub(lambda _: background_address, lab.template.value)
    contents = {
        "template": rewrite_local_addresses(template, vdr).encode("utf-8"),
        "background": lab.background.data if lab.background else None,
        "credential": json.dumps(credential, indent=2, ensure_ascii=False).encode("utf-8"),
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
                    "credential": f"certify/credentials/{config_id}.json"}
        for role, path in listed.items():
            if role == "sample":
                ok = path.startswith("sample/") and path.endswith(".json") and posixpath.dirname(path) == "sample"
            else:
                ok = path == expected[role]
            if not ok:
                raise ValueError(f"the {role} is listed at {path!r}, which is not where a package puts it")
        if unlisted := sorted(set(names) - set(listed.values()) - {manifests[0]}):
            raise ValueError(f"the package holds {unlisted[0]!r}, which its manifest does not list")
        if absent := sorted(set(listed.values()) - set(names)):
            raise ValueError(f"the manifest lists {absent[0]!r}, which the package does not hold")

        vdr = manifest["vdrAddress"]
        files: dict[str, tuple[str, bytes]] = {}
        for role, path in listed.items():
            data = z.read(path)
            if role in ("template", "credential"):
                data = data.decode("utf-8").replace(vdr, LOCAL_VDR).encode("utf-8")
            files[role] = (posixpath.basename(path), data)
    LabSet.from_files(files)
    return files, {"configId": config_id, "version": version, "vdrAddress": vdr}


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


def _sample_name(filename: str) -> str:
    """The uploaded sample's name without its .json, as one safe path part."""
    name = safe_filename(filename, "sample")
    return name[:-5] if name.lower().endswith(".json") and len(name) > 5 else name
