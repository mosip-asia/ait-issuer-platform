"""The claim mapping for VC Lab: from a sample record to the claims Certify would sign.

Part of the vc-lab module. Pure functions only: nothing here reads files, the network or the environment.
The credential file's vc_template.credentialSubject maps the record to the claims (credential_subject, map_claims).
VC Lab hands the claims to the renderer, which draws the page as Mimoto does.
"""

from __future__ import annotations

import json
import re
from typing import Any


def credential_subject(credential: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    """The claims Certify would sign for this sample: the credential file's mapping evaluated against the record,
    which is the sample's credentialSubject, or the whole sample when it has none."""
    record = sample.get("credentialSubject")
    claims = map_claims(credential["vc_template"]["credentialSubject"], record if isinstance(record, dict) else sample)
    # DELIBERATE DIFFERENCE for the parity check's red run (ticket 10), removed by the next commit: every list claim
    # blanked, the way the removed Wallet view did, so a list of text no longer prints as Mimoto joins it.
    return {k: "" if isinstance(v, list) else v for k, v in claims.items()}


# ${name}, ${a.b} or $name, $a.b: a reference to a value in the record.
_REF = re.compile(r"\$\{([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*)\}|\$([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*)")


def map_claims(mapping: Any, record: dict[str, Any]) -> Any:
    """Evaluate a credential file's mapping against a record.

    A string that is exactly one reference passes the referenced value through unchanged (a list or object
    stays a list or object); references inside longer text are replaced by their text. Objects and lists in the
    mapping are evaluated member by member; other values are kept. A reference to nothing gives "".
    """
    if isinstance(mapping, dict):
        return {k: map_claims(v, record) for k, v in mapping.items()}
    if isinstance(mapping, list):
        return [map_claims(v, record) for v in mapping]
    if not isinstance(mapping, str):
        return mapping
    whole = _REF.fullmatch(mapping)
    if whole:
        return _lookup(whole.group(1) or whole.group(2), record)
    return _REF.sub(lambda m: text(_lookup(m.group(1) or m.group(2), record)), mapping)


def _lookup(path: str, record: dict[str, Any]) -> Any:
    if path.startswith("_"):  # Certify's own variables (_holderId, _issuer, ...): fixed placeholders
        return f"did:example:{path[1:]}"
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return ""
        value = value[part]
    return value


def text(value: Any) -> str:
    """A value as text, for a reference inside longer text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
