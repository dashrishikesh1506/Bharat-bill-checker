# Bharat Bill Checker

A Flask web app that analyzes Indian utility bills using Gemini or Anthropic. Uploaded bills are sent to the configured AI provider for analysis.

## Run locally on Windows

1. Install Python 3.10 or newer.
2. Open PowerShell in this folder.
3. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install packages:

   ```powershell
   pip install -r requirements-deploy.txt
   ```

5. Copy `.env.example` to `.env` and put your Gemini key after `GEMINI_API_KEY=`. Keep `.env` private; it is excluded from Git.
6. Start the app with `python app.py`, then open http://127.0.0.1:5000.

## Deploy on Render

This repository includes `render.yaml` for a Render Flask web service. Connect the GitHub repository to Render, then add `GEMINI_API_KEY` in the service's Environment settings. Do not upload `.env` or put the key in source code. Render builds with `requirements-deploy.txt` and starts the app with Gunicorn.

The app limits request sizes and applies per-IP request limits to reduce accidental or abusive AI usage. These limits are a basic safeguard, not a substitute for monitoring API usage and quotas.
