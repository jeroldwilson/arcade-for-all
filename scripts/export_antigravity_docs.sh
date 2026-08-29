#!/usr/bin/env bash
set -euo pipefail

# Workspace root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_GEMINI_DIR="${HOME}/.gemini/antigravity-ide"
TARGET_DIR="${PROJECT_ROOT}/docs/antigravity"

echo "=== Consolidating Gemini / Antigravity Context ==="

# 1. Rename 'doc' to 'docs' if 'doc' exists and 'docs' does not
if [ -d "${PROJECT_ROOT}/doc" ] && [ ! -d "${PROJECT_ROOT}/docs" ]; then
    echo "Renaming '${PROJECT_ROOT}/doc' -> '${PROJECT_ROOT}/docs'..."
    if [ -d "${PROJECT_ROOT}/.git" ]; then
        git -C "${PROJECT_ROOT}" mv doc docs
    else
        mv "${PROJECT_ROOT}/doc" "${PROJECT_ROOT}/docs"
    fi
fi

# 2. Create target directory
mkdir -p "${TARGET_DIR}/brain"
mkdir -p "${TARGET_DIR}/knowledge"

# 3. Copy brain directory contents (transcripts, artifacts, plans)
if [ -d "${SOURCE_GEMINI_DIR}/brain" ]; then
    echo "Copying brain artifacts and transcripts from ${SOURCE_GEMINI_DIR}/brain..."
    rsync -av --progress "${SOURCE_GEMINI_DIR}/brain/" "${TARGET_DIR}/brain/"
else
    echo "Notice: ${SOURCE_GEMINI_DIR}/brain does not exist."
fi

# 4. Copy knowledge directory contents
if [ -d "${SOURCE_GEMINI_DIR}/knowledge" ]; then
    echo "Copying knowledge items from ${SOURCE_GEMINI_DIR}/knowledge..."
    rsync -av --progress "${SOURCE_GEMINI_DIR}/knowledge/" "${TARGET_DIR}/knowledge/"
else
    echo "Notice: ${SOURCE_GEMINI_DIR}/knowledge does not exist."
fi

echo "=== Done! Files copied to ${TARGET_DIR} ==="
