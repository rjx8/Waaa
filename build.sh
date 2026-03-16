#!/usr/bin/env bash
# build.sh — runs during Render build phase
set -e

echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🎬 Installing ffmpeg (static binary)..."
mkdir -p /opt/ffmpeg
curl -L "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" \
     -o /tmp/ffmpeg.tar.xz
tar -xf /tmp/ffmpeg.tar.xz -C /tmp/
cp /tmp/ffmpeg-*-amd64-static/ffmpeg  /opt/ffmpeg/ffmpeg
cp /tmp/ffmpeg-*-amd64-static/ffprobe /opt/ffmpeg/ffprobe
chmod +x /opt/ffmpeg/ffmpeg /opt/ffmpeg/ffprobe
ln -sf /opt/ffmpeg/ffmpeg  /usr/local/bin/ffmpeg
ln -sf /opt/ffmpeg/ffprobe /usr/local/bin/ffprobe
echo "✅ ffmpeg $(ffmpeg -version | head -1)"

echo "✅ Build complete!"