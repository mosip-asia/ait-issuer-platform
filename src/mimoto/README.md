# ait-mimoto's one change to Mimoto

`CredentialPDFGeneratorService.java` is upstream Mimoto's file with one added line. `docker/Dockerfile.mimoto` compiles it against the libraries inside `injistack/mimoto:0.21.0` and puts the class into that image's jar, which gives `ghcr.io/mosip-asia/ait-mimoto`. `scripts/build.sh` builds the image; `compose.mimoto.yaml` runs it locally.

## Upstream

- Repository: <https://github.com/inji/mimoto> (also reachable as `mosip/mimoto`)
- Tag `v0.21.0`, commit `48259310977b06c72401a41b666852362bf20bbc`
- File: `src/main/java/io/mosip/mimoto/service/CredentialPDFGeneratorService.java`

## Licence

Mimoto is licensed under the Mozilla Public License, v. 2.0 (MPL-2.0). This file is a modified copy of an MPL-2.0 file and stays under MPL-2.0. The upstream file carries no licence header of its own; the licence is the upstream repository's `LICENSE`.

> This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain one at https://mozilla.org/MPL/2.0/.

## The change

In `generatePdfForVerifiableCredential`, after the template's variables are collected (the `data` map that holds `rowProperties`), one line adds the claims as Mimoto received them:

```java
data.put("credentialSubject", credentialProperties);
```

`credentialProperties` is the map the method already has from `extractCredentialClaims`. A template then reads lists and objects whole, for example `#foreach($term in $credentialSubject.courses)`. `$rowProperties` and every other variable are unchanged, so a template written for upstream Mimoto prints the same. Only the Velocity path (v1 data model) changes; the SVG path doesn't use these variables.

A comment beginning `// ait-mimoto:` marks the line. To see the whole change against upstream:

```bash
git clone --depth 1 --branch v0.21.0 https://github.com/inji/mimoto.git /tmp/mimoto
diff /tmp/mimoto/src/main/java/io/mosip/mimoto/service/CredentialPDFGeneratorService.java src/mimoto/CredentialPDFGeneratorService.java
```
