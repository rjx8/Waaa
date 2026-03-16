#!/usr/bin/env bash
# build.sh — runs during Render build phase
set -e

echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🎬 Installing ffmpeg..."
apt-get update -qq
apt-get install -y -qq ffmpeg

echo "✅ Build complete!"
