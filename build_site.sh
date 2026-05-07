#!/bin/bash

# 1. Clean previous distribution
echo "Cleaning site/ directory..."
rm -rf site/

# 2. Build Versioned Documentation
# This creates site/documentation/v0.1 and site/documentation/latest
echo "Executing Mike (Versioned Build: v0.1)..."
uv run mike build v0.1 latest --prefix documentation

# 3. Assemble Landing Page
# Copy the index.html and its assets folder to the root of /site
echo "Injecting Landing Page into site/ ..."
cp landing/index.html site/
cp -r landing/assets site/

echo "------------------------------------------------"
echo "Success: Versioned distribution ready in /site"
echo "Check /site/documentation/versions.json for integrity."
echo "Ready to commit and push to GitHub Pages."