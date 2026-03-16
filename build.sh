#!/usr/bin/env bash
# build.sh — runs during Render build phase
set -e

echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🎬 Installing ffmpeg into HOME/bin (writable on Render)..."
mkdir -p "$HOME/bin"
curl -L "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
     -o /tmp/ffmpeg.tar.xz
tar -xf /tmp/ffmpeg.tar.xz -C /tmp/
FFDIR=$(find /tmp -maxdepth 1 -name "ffmpeg-*-amd64-static" -type d | head -1)
cp "$FFDIR/ffmpeg"  "$HOME/bin/ffmpeg"
cp "$FFDIR/ffprobe" "$HOME/bin/ffprobe"
chmod +x "$HOME/bin/ffmpeg" "$HOME/bin/ffprobe"
export PATH="$HOME/bin:$PATH"
echo "✅ ffmpeg installed: $($HOME/bin/ffmpeg -version | head -1)"

echo "✅ Build complete!"