import asyncio
import json
import os
import threading
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from criar_video_narrado import INSTRUCOES_PADRAO, VOZ_PADRAO, processar_video

BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_ENV = BASE_DIR / ".env"
PASTA_AMOSTRAS = BASE_DIR / "data" / "voz_exemplo"
FRONTEND_DIR = BASE_DIR / "frontend"

VOZES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]

app = FastAPI()
jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _carregar_env() -> None:
    if not ARQUIVO_ENV.exists():
        return
    for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def _ler_chave() -> str:
    chave = os.environ.get("OPENAI_API_KEY", "")
    if chave:
        return chave
    if ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("OPENAI_API_KEY="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _salvar_chave(chave: str) -> None:
    linhas = []
    encontrada = False
    if ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("OPENAI_API_KEY="):
                linhas.append(f'OPENAI_API_KEY="{chave}"')
                encontrada = True
            else:
                linhas.append(linha)
    if not encontrada:
        linhas.append(f'OPENAI_API_KEY="{chave}"')
    ARQUIVO_ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    os.environ["OPENAI_API_KEY"] = chave


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class SaveKeyRequest(BaseModel):
    key: str


class GenerateStoryRequest(BaseModel):
    tema: str
    num_linhas: int = 10


class GenerateVideosRequest(BaseModel):
    url: str
    titulo: str
    texto: str
    pasta_saida: str = "video_narrado"
    voz: str = VOZ_PADRAO
    instrucoes: str = INSTRUCOES_PADRAO


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/key-status")
def key_status():
    return {"configured": bool(_ler_chave())}


@app.post("/api/save-key")
def save_key(body: SaveKeyRequest):
    if not body.key.strip():
        raise HTTPException(status_code=400, detail="Chave invalida.")
    _salvar_chave(body.key.strip())
    return {"ok": True}


@app.post("/api/generate-story")
def generate_story(body: GenerateStoryRequest):
    from openai import OpenAI
    _carregar_env()
    chave = _ler_chave()
    if not chave:
        raise HTTPException(status_code=400, detail="API Key nao configurada.")

    client = OpenAI(api_key=chave)
    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce e um contador de historias que escreve narrativas em primeira pessoa para videos virais no estilo 'Reddit storytime'. "
                    "Seu estilo tem caracteristicas muito especificas:\n"
                    "- Narrativa em primeira pessoa, como se estivesse contando para um amigo\n"
                    "- Comeca com um contexto que mostra quem o narrador ERA (com falhas, privilegios ou ingenuidade)\n"
                    "- Detalhes especificos e reais: numeros, tamanhos, cores, valores — isso da credibilidade\n"
                    "- Paragrafos curtos, linguagem simples e direta, sem palavras rebuscadas\n"
                    "- Tem um momento pivotal onde algo inesperado acontece e muda tudo\n"
                    "- O narrador reage com emocao genuina (chora, fica em choque, se arrepende)\n"
                    "- Termina com uma reflexao sobre o que mudou na vida do narrador e uma licao\n"
                    "- Tom conversacional, como se o narrador estivesse 'desabafando' ou 'confessando'\n"
                    "- Sem introducoes de conto de fadas, sem linguagem poetica ou formal\n"
                    "- Sem asteriscos, sem marcacoes de formatacao, sem titulos internos\n"
                    "Escreva sempre em portugues do Brasil."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Escreva uma historia em primeira pessoa sobre o tema: '{body.tema}'.\n"
                    f"A historia deve ter aproximadamente {body.num_linhas} paragrafos.\n"
                    "Use o estilo confessional/storytime: comece com contexto sobre quem voce era, "
                    "desenvolva o momento que mudou tudo com detalhes especificos, reaja com emocao real, "
                    "e termine com uma reflexao genuina sobre o que aprendeu.\n\n"
                    "Responda APENAS neste formato (nada mais antes ou depois):\n"
                    "TITULO: <titulo curto, intrigante, que da vontade de assistir>\n"
                    "TEXTO: <historia completa em paragrafos, sem repetir o titulo>"
                ),
            },
        ],
        temperature=0.9,
    )

    conteudo = resposta.choices[0].message.content.strip()
    titulo = ""
    linhas_texto: list[str] = []
    modo_texto = False
    for linha in conteudo.splitlines():
        if linha.startswith("TITULO:"):
            titulo = linha.removeprefix("TITULO:").strip()
        elif linha.startswith("TEXTO:"):
            linhas_texto.append(linha.removeprefix("TEXTO:").strip())
            modo_texto = True
        elif modo_texto:
            linhas_texto.append(linha)

    return {"titulo": titulo, "texto": "\n".join(linhas_texto).strip()}


@app.post("/api/generate-videos")
def generate_videos(req: GenerateVideosRequest):
    _carregar_env()
    if not _ler_chave():
        raise HTTPException(status_code=400, detail="API Key nao configurada.")

    job_id = str(uuid4())
    jobs[job_id] = {"status": "running", "messages": [], "result": None, "error": None}

    def run():
        def callback(msg: str):
            jobs[job_id]["messages"].append(msg)

        pasta = BASE_DIR / req.pasta_saida
        try:
            result = processar_video(
                url=req.url,
                titulo=req.titulo,
                texto=req.texto,
                pasta_saida=pasta,
                voz=req.voz,
                instrucoes=req.instrucoes,
                status_callback=callback,
            )
            jobs[job_id]["status"] = "done"
            jobs[job_id]["result"] = [
                f.resolve().relative_to(BASE_DIR.resolve()).as_posix() for f in result
            ]
        except (Exception, SystemExit) as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job nao encontrado.")

    async def generate():
        sent = 0
        while True:
            job = jobs.get(job_id, {})
            messages = job.get("messages", [])

            while sent < len(messages):
                yield f"data: {json.dumps(messages[sent])}\n\n"
                sent += 1

            status = job.get("status")
            if status == "done":
                yield f"event: done\ndata: {json.dumps({'result': job.get('result', [])})}\n\n"
                break
            elif status == "error":
                yield f"event: error\ndata: {json.dumps({'error': job.get('error', '')})}\n\n"
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/voice-sample/{voice}")
def voice_sample(voice: str):
    if voice not in VOZES:
        raise HTTPException(status_code=404)
    path = PASTA_AMOSTRAS / f"{voice}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Amostra nao disponivel.")
    return FileResponse(str(path), media_type="audio/mpeg")


@app.get("/files/{path:path}")
def serve_file(path: str):
    filepath = (BASE_DIR / path).resolve()
    try:
        filepath.relative_to(BASE_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403)
    if not filepath.exists():
        raise HTTPException(status_code=404)
    suffix = filepath.suffix.lower()
    media_types = {".mp4": "video/mp4", ".mp3": "audio/mpeg", ".srt": "text/plain"}
    return FileResponse(str(filepath), media_type=media_types.get(suffix, "application/octet-stream"))


# Serve frontend last (catch-all)
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    _carregar_env()
    uvicorn.run(app, host="0.0.0.0", port=8000)
