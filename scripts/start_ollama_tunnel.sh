#!/bin/bash
# Helper script to start Cloudflare tunnel for Ollama on macOS

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install from https://ollama.com/download or run: brew install ollama"
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Installing cloudflared via Homebrew..."
  brew install cloudflared
fi

echo "Checking if Ollama is running on port 11434..."
if ! curl -s http://127.0.0.1:11434/ >/dev/null 2>&1; then
  echo "Starting Ollama in background..."
  ollama serve >/dev/null 2>&1 &
  sleep 2
fi

echo ""
echo "================================================================="
echo " Starting Cloudflare Tunnel for Ollama (Port 11434)"
echo " Copy the https://*.trycloudflare.com URL below into Render:"
echo " Set OLLAMA_URL = https://<your-tunnel-url>/api/generate"
echo "================================================================="
echo ""

cloudflared tunnel --url http://localhost:11434

