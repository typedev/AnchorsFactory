#!/usr/bin/env bash
# Fetch the OFL-licensed font sources used by the guide's example figures
# into docs/guide/tools/_fonts/ (gitignored). Shallow clones; safe to re-run.
#
#   Anek Devanagari  — https://github.com/EkType/Anek         (OFL 1.1)
#   Noto Sans Thai   — https://github.com/notofonts/thai      (OFL 1.1)
#
# UFO masters used by the examples:
#   _fonts/Anek/sources/AnekDevanagari/Masters/AnekDevanagari-Medium.ufo
#   _fonts/thai/sources/NotoSansThai-Regular.ufo
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p _fonts

fetch() {
    local url=$1 dir=_fonts/$2
    if [ -d "$dir/.git" ]; then
        echo "already present: $dir (delete it to re-fetch)"
    else
        git clone --depth 1 "$url" "$dir"
    fi
}

fetch https://github.com/EkType/Anek.git Anek
fetch https://github.com/notofonts/thai.git thai

echo "done. UFOs:"
ls -d _fonts/Anek/sources/AnekDevanagari/Masters/*.ufo _fonts/thai/sources/*.ufo 2>/dev/null | head
