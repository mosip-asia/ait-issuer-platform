# ait-mimoto's two changes to Mimoto

`CredentialPDFGeneratorService.java` is upstream Mimoto's file with two added lines. `docker/Dockerfile.mimoto` compiles it against the libraries inside `injistack/mimoto:0.21.0` and puts the class into that image's jar, which gives `ghcr.io/mosip-asia/ait-mimoto`. `scripts/build.sh` builds the image; `compose.mimoto.yaml` runs it locally.

## Upstream

- Repository: <https://github.com/inji/mimoto> (also reachable as `mosip/mimoto`)
- Tag `v0.21.0`, commit `48259310977b06c72401a41b666852362bf20bbc`
- File: `src/main/java/io/mosip/mimoto/service/CredentialPDFGeneratorService.java`

## Licence

Mimoto is licensed under the Mozilla Public License, v. 2.0 (MPL-2.0). This file is a modified copy of an MPL-2.0 file and stays under MPL-2.0. The upstream file carries no licence header of its own; the licence is the upstream repository's `LICENSE`.

> This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

## The changes

### 1. `$credentialSubject`

In `generatePdfForVerifiableCredential`, after the template's variables are collected (the `data` map that holds `rowProperties`), one line adds the claims as Mimoto received them:

```java
data.put("credentialSubject", credentialProperties);
```

`credentialProperties` is the map the method already has from `extractCredentialClaims`. A template then reads lists and objects whole, for example `#foreach($term in $credentialSubject.courses)`. `$credentialSubject` is the claims as received, so it skips what `rowProperties` does to them (SD-JWT disclosure masking under `mosip.injiweb.mask.disclosures`, and dropping the face): a template that prints from it decides what shows. `$rowProperties` and every other variable are unchanged, so a template written for upstream Mimoto prints the same. Only the Velocity path (v1 data model) changes; the SVG path doesn't use these variables.

### 2. `SecureUberspector`

In `renderVCInCredentialTemplate`, the Velocity properties also set `runtime.introspector.uberspect` to `org.apache.velocity.util.introspection.SecureUberspector`. A template then can't reach Java internals: `$credentialSubject.getClass().forName("java.lang.Runtime")` prints as written instead of running. The committed templates don't use such calls and print the same. VC Lab's preview runs the same setting (`docs/adr/0002-vc-lab-previews-through-its-own-copy-of-the-print-code.md`). Velocity 1.7 has a known bypass of this class (CVE-2020-13936); upgrading Velocity is a separate change.

A comment beginning `// ait-mimoto` marks each line. To see the whole change against upstream:

```bash
git clone --depth 1 --branch v0.21.0 https://github.com/inji/mimoto.git /tmp/mimoto
diff /tmp/mimoto/src/main/java/io/mosip/mimoto/service/CredentialPDFGeneratorService.java src/mimoto/CredentialPDFGeneratorService.java
```
