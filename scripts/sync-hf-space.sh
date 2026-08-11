#!/usr/bin/env bash
#
# sync-hf-space.sh — assemble the Hugging Face Spaces demo tree and push it (v1.1 M39-S1).
#
# The Space repo must contain the FULL build context the combined deploy/huggingface/Dockerfile
# expects (see docs/huggingface-space.md): root Dockerfile + README.md (the Space's front page),
# deploy/ (the Dockerfile + start.sh), pyproject.toml + src/ (pip install ".[service]"), backend/ +
# alembic.ini (the service layer + migrations), frontend/ + docs/ (the Next build reads
# ../docs/openapi.json and the docs corpus). This script assembles exactly that tree from the
# TRACKED files of the current checkout — so node_modules/, .next/, docs/private/, and other
# non-image inputs can never leak into the build context even if they exist locally — writes a
# .dockerignore as a second guard, commits, and pushes.
#
# The push is the maintainer's manual step (docs/private/DECISIONS.md D52 discipline): no CI, no
# HF token in the repo. The script only stages the assembled tree inside the Space repo — it never
# touches this checkout.
#
# Usage: scripts/sync-hf-space.sh <space-repo-dir> [commit-message]
#   <space-repo-dir>   a clone of the HF Space (git remote pointing at huggingface.co)
#   [commit-message]   optional; default "Update Xtalate demo"
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <space-repo-dir> [commit-message]" >&2
    exit 1
fi

SPACE_DIR="$(cd "$1" && pwd)"
COMMIT_MSG="${2:-Update Xtalate demo}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -d "$SPACE_DIR/.git" ]]; then
    echo "error: $1 is not a git repo (a Space clone has a .git dir)" >&2
    exit 1
fi

# The tree is assembled from git ls-files, so untracked local junk can never ride along.
mapfile -t FILES < <(
    cd "$HERE" && git ls-files -- \
        pyproject.toml alembic.ini \
        src backend frontend docs deploy
)

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "error: nothing to sync — is the current checkout a Xtalate repo?" >&2
    exit 1
fi

echo "assembling Space tree in $SPACE_DIR from ${#FILES[@]} tracked files"

# A clean slate keeps deletions (a removed repo file) visible in the push rather than lingering.
git -C "$SPACE_DIR" rm -rfq --ignore-unmatch . >/dev/null 2>&1 || true

# The Space front page + the combined Dockerfile at the root; everything else verbatim.
install -D -m 0644 "$HERE/deploy/huggingface/README.md" "$SPACE_DIR/README.md"
install -D -m 0644 "$HERE/deploy/huggingface/Dockerfile" "$SPACE_DIR/Dockerfile"
for f in "${FILES[@]}"; do
    # deploy/huggingface/README.md and Dockerfile are installed above; skip the duplicates.
    case "$f" in
        deploy/huggingface/README.md | deploy/huggingface/Dockerfile) continue ;;
    esac
    mkdir -p "$SPACE_DIR/$(dirname "$f")"
    install -D -m 0644 "$HERE/$f" "$SPACE_DIR/$f"
done
install -D -m 0755 "$HERE/deploy/huggingface/start.sh" "$SPACE_DIR/deploy/huggingface/start.sh"

# Second guard on the build context size, in case the Space is ever assembled by hand later.
cat > "$SPACE_DIR/.dockerignore" <<'EOF'
.git/
node_modules/
**/node_modules/
**/.next/
.next/
docs/private/
tests/
benchmarks/
plugins/
examples/
playwright-report/
test-results/
*.pyc
__pycache__/
**/__pycache__/
.freebuff/
.env
EOF

git -C "$SPACE_DIR" add -A
git -C "$SPACE_DIR" -c user.name="$(git config user.name || echo 'maintainer')" \
    -c user.email="$(git config user.email || echo 'maintainer@example.invalid')" \
    commit -m "$COMMIT_MSG"
git -C "$SPACE_DIR" push

echo "pushed. HF will rebuild the Space from the new tree."
