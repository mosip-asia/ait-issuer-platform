#!/usr/bin/env bash
# ==============================================================================
# Put a Thai font in a folder of the VDR's templates, for a test template's @font-face. Local only.
# ==============================================================================
# Used by print-check.sh and parity-check.sh. The font is TLWG's Loma, freely licensed (GPL-2+ with a font exception;
# the package's copyright file is kept next to the font), taken from Debian's fonts-tlwg-loma-ttf at run time inside
# the ait-vc image (Debian-based), so no font is committed. The folder must be git-ignored; the caller removes it.
#
# Usage:
#   scripts/thai-font.sh <folder> <ait-vc image>     writes <folder>/thai-font.ttf and <folder>/thai-font.copyright
# ==============================================================================
set -euo pipefail
DIR=$1 IMAGE=$2
mkdir -p "$DIR"
docker run --rm --user root -v "$(readlink -f "$DIR"):/font" -e "OWNER=$(id -u):$(id -g)" "$IMAGE" sh -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends fonts-tlwg-loma-ttf >/dev/null &&
  cp /usr/share/fonts/truetype/tlwg/Loma.ttf /font/thai-font.ttf &&
  cp /usr/share/doc/fonts-tlwg-loma-ttf/copyright /font/thai-font.copyright &&
  chown -R "$OWNER" /font' >/dev/null \
  || { echo "FAIL setup: couldn't take the Thai font from Debian's fonts-tlwg-loma-ttf (is the network up?)" >&2; exit 1; }
echo "Thai font: $(wc -c < "$DIR/thai-font.ttf") bytes from Debian's fonts-tlwg-loma-ttf"
