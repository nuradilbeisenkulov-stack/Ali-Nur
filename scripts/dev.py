"""One-command local development server; owns and stops only its child processes."""
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import httpx
from app.config import ROOT, setting

CPU = setting("SUPPORT_AI_BACKEND", "ollama") == "llamacpp"
URL = setting("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

def ready():
 try:
  return httpx.get(URL + ('/health' if CPU else '/api/tags'), timeout=1, trust_env=False).status_code == 200
 except httpx.HTTPError:
  return False

def main():
 children=[]
 try:
  if setting('SUPPORT_AI_BACKEND', 'gemini') != 'gemini' and not ready():
   binary=ROOT/'work/ollama/ollama'
   executable=str(binary) if binary.exists() else shutil.which('ollama')
   if not executable:
    raise SystemExit('Ollama не найдена. Установите с ollama.com либо используйте SUPPORT_AI=off make run.')
   env={**os.environ,'OLLAMA_MODELS':str(ROOT/'work/models'),'OLLAMA_NO_CLOUD':'1'}
   command=[executable,'serve']
   if CPU:
    manifest=ROOT/'work/models/manifests/registry.ollama.ai/library/qwen3/1.7b'
    if not manifest.exists(): raise SystemExit('Веса не найдены. Сначала make ai-serve и make ai-pull.')
    data=json.loads(manifest.read_text())
    layer=next(layer for layer in data['layers'] if layer['mediaType']=='application/vnd.ollama.image.model')
    weights=ROOT/'work/models/blobs'/layer['digest'].replace(':','-')
    from urllib.parse import urlsplit
    endpoint=urlsplit(URL)
    if endpoint.hostname not in {'localhost','127.0.0.1','::1'}: raise SystemExit('Допустим только локальный сервер.')
    command=[str(ROOT/'work/ollama/llama-server'),'-m',str(weights),'--device','none','--no-op-offload','--no-kv-offload','-ngl','0','-c','4096','--host',endpoint.hostname,'--port',str(endpoint.port or 11435)]
   child=subprocess.Popen(command,env=env); children.append(child)
   for _ in range(60):
    if ready(): break
    if child.poll() is not None: raise SystemExit('Ollama не запустилась. Проверьте сообщение выше.')
    time.sleep(.5)
   else: raise SystemExit('Таймаут запуска Ollama.')
  print('Support Copilot: http://127.0.0.1:8000 — Ctrl+C для остановки',flush=True)
  child=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000']);children.append(child)
  child.wait()
 except KeyboardInterrupt: pass
 finally:
  for child in reversed(children):
   if child.poll() is None:
    child.terminate()
    try: child.wait(timeout=10)
    except subprocess.TimeoutExpired: child.kill()
if __name__=='__main__': main()
