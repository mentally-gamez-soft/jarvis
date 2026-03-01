#!/bin/bash

# ==============================================================================
# Docker Image Tagging Script for Registry
# ==============================================================================
# Purpose: Tag local Docker images for registry push
# Usage: ./rename-docker-image-4-registry.sh
# Requirements: Docker installed and images built locally
# ==============================================================================

set -e  # Exit on first error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

# ==============================================================================
# Configuration
# ==============================================================================

# Source image names (built locally)
SOURCE_IMAGE_TRIAGE="jarvis-agent-triage:latest"
SOURCE_IMAGE_FRONTEND="jarvis-agent-triage-frontend:latest"

# Target registry prefix (from environment variable)
REGISTRY_PREFIX="${DOCKERHUB_IMAGE}"

# Target image names
TARGET_IMAGE_TRIAGE="${REGISTRY_PREFIX}:jarvis-agent-triage-latest"
TARGET_IMAGE_FRONTEND="${REGISTRY_PREFIX}:jarvis-agent-triage-frontend-latest"

# ==============================================================================
# Functions
# ==============================================================================

# Print info message
info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

# Print success message
success() {
    echo -e "${GREEN}[SUCCESS]${NC} $*"
}

# Print warning message
warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

# Print error message
error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

# Check if image exists locally
check_image_exists() {
    local image=$1
    if docker image inspect "$image" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Tag a Docker image
tag_image() {
    local source=$1
    local target=$2
    
    info "Tagging image: $source → $target"
    
    if docker tag "$source" "$target"; then
        success "Successfully tagged: $target"
        return 0
    else
        error "Failed to tag image: $source"
        return 1
    fi
}

# ==============================================================================
# Main Execution
# ==============================================================================

echo ""
info "================================"
info "Docker Image Tagging Script"
info "================================"
echo ""

# Check if DOCKERHUB_IMAGE environment variable is set
if [ -z "$DOCKERHUB_IMAGE" ]; then
    error "Environment variable DOCKERHUB_IMAGE is not set"
    echo ""
    info "Please set DOCKERHUB_IMAGE before running this script:"
    echo "  export DOCKERHUB_IMAGE='username/repo'"
    exit 1
fi

info "Using registry prefix: $REGISTRY_PREFIX"
echo ""

# ==============================================================================
# Tag agent-triage image
# ==============================================================================

info "Processing agent-triage image..."
if check_image_exists "$SOURCE_IMAGE_TRIAGE"; then
    success "Source image exists: $SOURCE_IMAGE_TRIAGE"
    if tag_image "$SOURCE_IMAGE_TRIAGE" "$TARGET_IMAGE_TRIAGE"; then
        TRIAGE_SUCCESS=true
    else
        TRIAGE_SUCCESS=false
    fi
else
    error "Source image not found: $SOURCE_IMAGE_TRIAGE"
    warn "Run 'docker-compose build agent-triage' to build the image"
    TRIAGE_SUCCESS=false
fi

echo ""

# ==============================================================================
# Tag frontend image
# ==============================================================================

info "Processing frontend image..."
if check_image_exists "$SOURCE_IMAGE_FRONTEND"; then
    success "Source image exists: $SOURCE_IMAGE_FRONTEND"
    if tag_image "$SOURCE_IMAGE_FRONTEND" "$TARGET_IMAGE_FRONTEND"; then
        FRONTEND_SUCCESS=true
    else
        FRONTEND_SUCCESS=false
    fi
else
    error "Source image not found: $SOURCE_IMAGE_FRONTEND"
    warn "Run 'docker-compose build frontend' to build the image"
    FRONTEND_SUCCESS=false
fi

echo ""

# ==============================================================================
# Summary
# ==============================================================================

info "================================"
info "Summary"
info "================================"

if [ "$TRIAGE_SUCCESS" = true ]; then
    success "Agent-Triage: $TARGET_IMAGE_TRIAGE"
else
    error "Agent-Triage: FAILED"
fi

if [ "$FRONTEND_SUCCESS" = true ]; then
    success "Frontend: $TARGET_IMAGE_FRONTEND"
else
    error "Frontend: FAILED"
fi

echo ""

# ==============================================================================
# Next Steps
# ==============================================================================

if [ "$TRIAGE_SUCCESS" = true ] && [ "$FRONTEND_SUCCESS" = true ]; then
    success "All images tagged successfully!"
    echo ""
    info "Next steps to push to registry:"
    echo "  1. docker push $TARGET_IMAGE_TRIAGE"
    echo "  2. docker push $TARGET_IMAGE_FRONTEND"
    echo ""
    exit 0
else
    error "Some images failed to tag. Please check the errors above."
    echo ""
    exit 1
fi