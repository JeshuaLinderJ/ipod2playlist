#!/bin/sh
# Regenerates the tiny silent audio files used by tests. Needs ffmpeg; tests do not.
set -e
cd "$(dirname "$0")"
SRC="-f lavfi -i anullsrc=r=22050:cl=mono -t 0.5 -y -loglevel error"
ffmpeg $SRC -b:a 16k silence.mp3
ffmpeg $SRC -b:a 16k -c:a aac silence.m4a
ffmpeg $SRC -c:a flac silence.flac
ffmpeg $SRC -ar 8000 -c:a pcm_u8 silence.wav
