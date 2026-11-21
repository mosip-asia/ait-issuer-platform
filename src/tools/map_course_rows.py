"""Write a copy of one credential file that maps `courseRows`, for the print check to publish to the local stack.

The credential file `dev` uses does not map `courseRows` yet: until SIS sends it (ask T4), a mapping would put an
unfilled placeholder into real credentials. The print check needs a credential that carries it, so scripts/print-check.sh
runs this on the committed file and publishes only the copy, to the local Certify.

    python map_course_rows.py --credentials DIR --credential <credential_config_key_id> --out DIR

The copy gets `"courseRows": "${courseRows}"` in `vc_template.credentialSubject`, after `courseList`; nothing else
changes. A file that maps it already is copied as it is.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CLAIM = "courseRows"


def map_course_rows(config: dict) -> dict:
    """`config` with `courseRows` mapped into the credential's subject, placed after `courseList`."""
    subject = config["vc_template"]["credentialSubject"]
    if CLAIM in subject:
        return config
    mapped = {}
    for key, value in subject.items():
        mapped[key] = value
        if key == "courseList":
            mapped[CLAIM] = "${" + CLAIM + "}"
    mapped.setdefault(CLAIM, "${" + CLAIM + "}")
    return {**config, "vc_template": {**config["vc_template"], "credentialSubject": mapped}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--credentials", type=Path, required=True, help="the Installation's credential files")
    parser.add_argument("--credential", required=True, help="the credential_config_key_id to map")
    parser.add_argument("--out", type=Path, required=True, help="an empty folder for the mapped copy")
    args = parser.parse_args()
    for path in sorted(args.credentials.glob("*.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        if config.get("credential_config_key_id") == args.credential:
            text = json.dumps(map_course_rows(config), indent=2, ensure_ascii=False) + "\n"
            (args.out / path.name).write_text(text, encoding="utf-8")
            print(f"mapped {CLAIM} in {path.name}")
            return 0
    print(f"no credential file in {args.credentials} has credential_config_key_id {args.credential}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
