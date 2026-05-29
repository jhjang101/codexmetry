#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

# --- 1. VERSION CAPTURE & VALIDATION ---
INPUT_VERSION=$1

if [ -z "$INPUT_VERSION" ]; then
    echo "--- Codexmetry Site Deployment ---"
    read -p "Enter version number (e.g., 0.1.0): " INPUT_VERSION
fi

# Ensure version is still not empty
if [ -z "$INPUT_VERSION" ]; then
    echo "Error: No version provided. Deployment aborted."
    exit 1
fi

# Extract Major.Minor for Documentation Versioning
# Example: 0.1.5 becomes 0.1
DOC_VERSION=$(echo $INPUT_VERSION | cut -d. -f1,2)

# --- 2. ALIAS OPT-IN ---
read -p "Should this be the LATEST version on the website? (y/n): " IS_LATEST
if [[ "$IS_LATEST" =~ ^[Yy]$ ]]; then
    ALIAS="latest"
    echo "Mode: Deploy $DOC_VERSION and update 'latest' alias."
else
    ALIAS=""
    echo "Mode: Deploy $DOC_VERSION only (preserving current 'latest')."
fi

TEMP_DIR=".deploy_worktree"

echo "Deploying Full Version: $INPUT_VERSION"
echo "Targeting Documentation Version: $DOC_VERSION"

# --- 3. CLEANUP ---
echo "Cleaning working environment..."
rm -rf $TEMP_DIR
git worktree prune

# --- 4. EXECUTE MIKE (Documentation Logic) ---
# This updates the local gh-pages branch with Mike's logic
echo "Executing Mike Deployment ($DOC_VERSION) to branch: gh-pages..."
if [ -n "$ALIAS" ]; then
    uv run mike deploy --update-aliases --deploy-prefix documentation $DOC_VERSION $ALIAS
else
    uv run mike deploy --update-aliases --deploy-prefix documentation $DOC_VERSION
fi

# --- 5. SITE ASSEMBLY (Landing Page Logic) ---
# Create a temporary worktree for the gh-pages branch
# This 'opens' the website universe in a separate folder
echo "Initializing site assembly worktree..."
git worktree add $TEMP_DIR gh-pages

# Inject Custom Landing Page
# We copy the source from landing/ into the root of the gh-pages universe
echo "Injecting custom landing page into branch root..."
cp -r landing/* $TEMP_DIR/

# --- 6. COMMIT & PUBLISH ---
echo "Finalizing site assembly..."
cd $TEMP_DIR
git add .

# Check if there are actual changes to commit
if git diff-index --quiet HEAD --; then
    echo "No changes detected in the site structure. Site is already up to date."
else
    git commit -m "Site Update: $INPUT_VERSION ($DOC_VERSION) docs + landing page assets"
    echo "Pushing to GitHub Pages..."
    git push origin gh-pages
fi

# --- 7. CLEANUP ---
echo "Cleaning up..."
cd ..
rm -rf $TEMP_DIR
git worktree prune

echo "------------------------------------------------"
echo "Success: Hybrid Site (Landing + Docs) is now LIVE."
echo "URL: https://jhjang101.github.io/codexmetry/"