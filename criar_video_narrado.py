import argparse
import math
import os
import re
import shutil
import subprocess
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from openai import OpenAI
from yt_dlp.utils import DownloadError

ARQUIVO_TEXTO_PADRAO = "texto.txt"
ARQUIVO_TITULO_PADRAO = "titulo.txt"
PASTA_SAIDA_PADRAO = "video_narrado"
PASTA_PARTES = "partes"
PASTA_ASSETS = "assets"
ARQUIVO_VIDEO_BASE = "background.mp4"
ARQUIVO_AUDIO = "narracao.mp3"
MODELO_TTS = "gpt-4o-mini-tts"
MODELO_TRANSCRICAO = "whisper-1"
VOZ_PADRAO = "coral"
LARGURA_VIDEO = 1080
ALTURA_VIDEO = 1920
FONTE_LEGENDA = "Janda Manatee Solid"
TAMANHO_FONTE_LEGENDA = 24
CONTORNO_LEGENDA = 5
MAX_CARACTERES_LEGENDA = 12
DURACAO_MAXIMA_PARTE = 60.0
PADDING_ABERTURA = 0.4
PADDING_ENCERRAMENTO = 0.6
TAMANHO_FONTE_TITULO = 44
TAMANHO_FONTE_PARTE = 28
TAMANHO_FONTE_ENCERRAMENTO = 34
CONTORNO_TEXTO_CARD = 6
MAX_CARACTERES_TITULO = 32
ESPACAMENTO_LINHAS_TITULO = -10
POSICAO_Y_TITULO = 0.20
MARGEM_TITULO_PARTE = 180
TEXTO_ENCERRAMENTO = "assista a pr\u00f3xima parte no youtube"
TEXTO_ENCERRAMENTO_FALA = "Assista \u00e0 pr\u00f3xima parte no YouTube."
INSTRUCOES_PADRAO = (
    "Fale com naturalidade, em portugues do Brasil, com ritmo claro e envolvente."
)
StatusCallback = Callable[[str], None]


@dataclass
class Legenda:
    inicio: float
    fim: float
    texto: str


@dataclass
class PartePlano:
    indice: int
    total: int
    inicio_conteudo: float
    fim_conteudo: float
    duracao_conteudo: float
    duracao_abertura_slot: float
    duracao_encerramento_audio: float
    caminho_audio_abertura: Path
    caminho_audio_encerramento: Path
    texto_abertura_card: str
    duracao_saida: float


def informar(status_callback: StatusCallback | None, mensagem: str) -> None:
    if status_callback is not None:
        status_callback(mensagem)


def carregar_env(caminho: str = ".env") -> None:
    arquivo = Path(caminho)
    if not arquivo.exists():
        return

    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue

        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def localizar_ffmpeg() -> Path | None:
    ffmpeg_no_path = shutil.which("ffmpeg")
    if ffmpeg_no_path:
        return Path(ffmpeg_no_path).resolve()

    pasta_winget = Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages"
    if pasta_winget.exists():
        candidatos = sorted(
            pasta_winget.glob("**/ffmpeg.exe"),
            key=lambda caminho: caminho.stat().st_mtime,
            reverse=True,
        )
        if candidatos:
            return candidatos[0].resolve()

    return None


def localizar_ffprobe(ffmpeg: Path) -> Path:
    ffprobe = ffmpeg.with_name("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
    if ffprobe.exists():
        return ffprobe

    ffprobe_no_path = shutil.which("ffprobe")
    if ffprobe_no_path:
        return Path(ffprobe_no_path).resolve()

    raise SystemExit("O ffprobe nao foi encontrado junto do ffmpeg.")


def garantir_dependencias() -> tuple[Path, Path]:
    ffmpeg = localizar_ffmpeg()
    if ffmpeg is None:
        raise SystemExit(
            "O ffmpeg nao foi encontrado. Instale o ffmpeg e deixe-o no PATH para "
            "baixar o video em boa qualidade e renderizar as legendas no MP4."
        )

    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "Defina OPENAI_API_KEY no ambiente ou no arquivo .env antes de executar."
        )

    ffprobe = localizar_ffprobe(ffmpeg)
    return ffmpeg, ffprobe


def ler_texto(caminho_arquivo: str) -> str:
    arquivo = Path(caminho_arquivo).expanduser().resolve()
    if not arquivo.exists():
        raise SystemExit(f"Arquivo de texto nao encontrado: {arquivo}")

    texto = arquivo.read_text(encoding="utf-8").strip()
    if not texto:
        raise SystemExit(f"O arquivo esta vazio: {arquivo}")

    return texto


def salvar_texto(texto: str, arquivo_saida: Path) -> Path:
    arquivo_saida.parent.mkdir(parents=True, exist_ok=True)
    arquivo_saida.write_text(texto, encoding="utf-8")
    return arquivo_saida


def baixar_video(url: str, pasta_saida: Path, ffmpeg: Path) -> Path:
    arquivo_saida = pasta_saida / ARQUIVO_VIDEO_BASE
    opcoes = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/mp4/b",
        "merge_output_format": "mp4",
        "outtmpl": str(pasta_saida / "background.%(ext)s"),
        "ffmpeg_location": str(ffmpeg.parent),
        "noplaylist": True,
        "windowsfilenames": True,
        "quiet": False,
    }

    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            ydl.download([url])
    except DownloadError as erro:
        raise SystemExit(f"Falha ao baixar o video: {erro}") from erro

    if not arquivo_saida.exists():
        candidatos = sorted(pasta_saida.glob("background.*"))
        if not candidatos:
            raise SystemExit("Nao consegui localizar o video baixado.")
        arquivo_saida = candidatos[0]

    return arquivo_saida


def gerar_audio(
    client: OpenAI,
    texto: str,
    arquivo_saida: Path,
    voz: str,
    instrucoes: str,
) -> Path:
    arquivo_saida.parent.mkdir(parents=True, exist_ok=True)
    with client.audio.speech.with_streaming_response.create(
        model=MODELO_TTS,
        voice=voz,
        input=texto,
        instructions=instrucoes,
        response_format="mp3",
    ) as response:
        response.stream_to_file(arquivo_saida)

    return arquivo_saida


def obter_duracao_midia(ffprobe: Path, arquivo: Path) -> float:
    resultado = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(arquivo),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(resultado.stdout.strip())


def _ler_campo(item: object, chave: str):
    if isinstance(item, dict):
        return item.get(chave)
    return getattr(item, chave, None)


def transcrever_audio(client: OpenAI, arquivo_audio: Path):
    # Os timestamps de palavra sao usados para fazer a legenda andar com a narracao.
    with arquivo_audio.open("rb") as audio_file:
        retorno = client.audio.transcriptions.create(
            model=MODELO_TRANSCRICAO,
            file=audio_file,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )

    palavras = _ler_campo(retorno, "words") or []
    if not palavras:
        raise SystemExit(
            "A transcricao nao retornou timestamps de palavra para montar as legendas."
        )
    return palavras


def normalizar_texto_legenda(texto: str) -> str:
    texto = re.sub(r"\s+([,.;:!?])", r"\1", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar_texto_fala(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def dividir_palavra_se_necessario(item, max_caracteres: int):
    texto = (_ler_campo(item, "word") or "").strip()
    inicio = _ler_campo(item, "start")
    fim = _ler_campo(item, "end")
    if not texto or inicio is None or fim is None:
        return []

    inicio = float(inicio)
    fim = float(fim)
    if len(texto) <= max_caracteres:
        return [{"texto": texto, "inicio": inicio, "fim": fim}]

    partes = [texto[i : i + max_caracteres] for i in range(0, len(texto), max_caracteres)]
    duracao_total = max(fim - inicio, 0.01)
    quantidade_partes = len(partes)
    palavras_divididas = []

    for indice, parte in enumerate(partes):
        inicio_parte = inicio + (duracao_total * indice / quantidade_partes)
        fim_parte = inicio + (duracao_total * (indice + 1) / quantidade_partes)
        palavras_divididas.append(
            {
                "texto": parte,
                "inicio": inicio_parte,
                "fim": fim_parte,
            }
        )

    return palavras_divididas


def criar_legendas(
    palavras,
    max_palavras: int = 5,
    max_caracteres: int = MAX_CARACTERES_LEGENDA,
    max_duracao: float = 2.6,
):
    legendas = []
    bloco = []
    inicio_bloco = None

    for palavra in palavras:
        palavras_processadas = dividir_palavra_se_necessario(palavra, max_caracteres)
        for item in palavras_processadas:
            if inicio_bloco is None:
                inicio_bloco = item["inicio"]

            texto_candidato = normalizar_texto_legenda(
                " ".join([*([parte["texto"] for parte in bloco]), item["texto"]])
            )
            duracao_candidata = item["fim"] - inicio_bloco
            excedeu_limite = (
                bloco
                and (
                    len(bloco) >= max_palavras
                    or len(texto_candidato) > max_caracteres
                    or duracao_candidata > max_duracao
                )
            )

            if excedeu_limite:
                texto_bloco = normalizar_texto_legenda(
                    " ".join(parte["texto"] for parte in bloco)
                )
                legendas.append(
                    Legenda(
                        inicio=inicio_bloco,
                        fim=bloco[-1]["fim"],
                        texto=texto_bloco,
                    )
                )
                bloco = []
                inicio_bloco = item["inicio"]

            bloco.append(item)

            texto_bloco = normalizar_texto_legenda(" ".join(parte["texto"] for parte in bloco))
            duracao = bloco[-1]["fim"] - inicio_bloco
            fecha_bloco = any(item["texto"].endswith(sinal) for sinal in ".!?;:")
            atingiu_limite = (
                len(bloco) >= max_palavras
                or len(texto_bloco) >= max_caracteres
                or duracao >= max_duracao
            )

            if fecha_bloco or atingiu_limite:
                legendas.append(
                    Legenda(
                        inicio=inicio_bloco,
                        fim=bloco[-1]["fim"],
                        texto=texto_bloco,
                    )
                )
                bloco = []
                inicio_bloco = None

    if bloco:
        texto_bloco = normalizar_texto_legenda(" ".join(item["texto"] for item in bloco))
        legendas.append(
            Legenda(
                inicio=inicio_bloco if inicio_bloco is not None else bloco[0]["inicio"],
                fim=bloco[-1]["fim"],
                texto=texto_bloco,
            )
        )

    return legendas


def formatar_tempo_srt(segundos: float) -> str:
    total_ms = max(0, int(round(segundos * 1000)))
    horas, resto = divmod(total_ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segundos, milissegundos = divmod(resto, 1000)
    return f"{horas:02}:{minutos:02}:{segundos:02},{milissegundos:03}"


def salvar_legendas(legendas, arquivo_saida: Path) -> Path:
    linhas = []
    for indice, legenda in enumerate(legendas, start=1):
        linhas.append(str(indice))
        linhas.append(
            f"{formatar_tempo_srt(legenda.inicio)} --> "
            f"{formatar_tempo_srt(legenda.fim)}"
        )
        linhas.append(legenda.texto)
        linhas.append("")

    arquivo_saida.write_text("\n".join(linhas), encoding="utf-8")
    return arquivo_saida


def quebrar_texto(texto: str, largura_maxima: int) -> str:
    linhas = []
    for bloco in texto.splitlines():
        bloco = bloco.strip()
        if not bloco:
            if linhas and linhas[-1] != "":
                linhas.append("")
            continue

        linhas.extend(textwrap.wrap(bloco, width=largura_maxima, break_long_words=False))

    return "\n".join(linhas).strip()


def obter_duracao_narracao(palavras) -> float:
    return max(float(_ler_campo(palavra, "end") or 0.0) for palavra in palavras)


def montar_texto_abertura_card(titulo: str) -> str:
    return quebrar_texto(titulo, MAX_CARACTERES_TITULO)


def montar_texto_abertura_fala(titulo: str, indice: int, total: int) -> str:
    titulo_fala = normalizar_texto_fala(titulo)
    return f"{titulo_fala}. Parte {indice} de {total}."


def calcular_posicao_y_parte(texto_abertura_card: str) -> int:
    quantidade_linhas = max(1, texto_abertura_card.count("\n") + 1)
    altura_linha = TAMANHO_FONTE_TITULO + (CONTORNO_TEXTO_CARD * 2) + max(0, ESPACAMENTO_LINHAS_TITULO)
    altura_bloco = TAMANHO_FONTE_TITULO + max(0, quantidade_linhas - 1) * altura_linha
    return int((ALTURA_VIDEO * POSICAO_Y_TITULO) + altura_bloco + MARGEM_TITULO_PARTE)


def limpar_saidas_antigas(pasta_partes: Path) -> None:
    for padrao in ("parte_*.mp4", "parte_*.srt", "parte_*_titulo.txt", "parte_*_encerramento.txt"):
        for arquivo in pasta_partes.glob(padrao):
            arquivo.unlink(missing_ok=True)

    pasta_assets = pasta_partes / PASTA_ASSETS
    if pasta_assets.exists():
        for arquivo in pasta_assets.glob("*.mp3"):
            arquivo.unlink(missing_ok=True)


def preparar_planos_partes(
    client: OpenAI,
    ffprobe: Path,
    palavras,
    titulo: str,
    pasta_partes: Path,
    voz: str,
    instrucoes: str,
    status_callback: StatusCallback | None = None,
):
    duracao_narracao = obter_duracao_narracao(palavras)
    pasta_assets = pasta_partes / PASTA_ASSETS
    pasta_assets.mkdir(parents=True, exist_ok=True)

    total_partes = max(1, math.ceil(duracao_narracao / 48.0))
    duracao_abertura_slot = 0.0
    duracao_encerramento_audio = 0.0
    caminhos_abertura = {}
    caminho_encerramento = pasta_assets / "encerramento.mp3"

    for _ in range(6):
        informar(status_callback, "Gerando fala de encerramento...")
        gerar_audio(
            client,
            TEXTO_ENCERRAMENTO_FALA,
            caminho_encerramento,
            voz,
            instrucoes,
        )
        duracao_encerramento_audio = obter_duracao_midia(ffprobe, caminho_encerramento)

        duracao_abertura_slot = 0.0
        caminhos_abertura = {}
        for indice in range(1, total_partes + 1):
            caminho_abertura = pasta_assets / f"parte_{indice:02d}_abertura.mp3"
            informar(status_callback, f"Gerando fala de abertura da parte {indice}/{total_partes}...")
            gerar_audio(
                client,
                montar_texto_abertura_fala(titulo, indice, total_partes),
                caminho_abertura,
                voz,
                instrucoes,
            )
            duracao_audio_abertura = obter_duracao_midia(ffprobe, caminho_abertura)
            caminhos_abertura[indice] = (caminho_abertura, duracao_audio_abertura)
            duracao_abertura_slot = max(
                duracao_abertura_slot,
                duracao_audio_abertura + PADDING_ABERTURA,
            )

        duracao_conteudo_por_parte = (
            DURACAO_MAXIMA_PARTE
            - duracao_abertura_slot
            - duracao_encerramento_audio
            - PADDING_ENCERRAMENTO
        )
        if duracao_conteudo_por_parte <= 5:
            raise SystemExit(
                "A abertura e o encerramento ficaram longos demais para caber em partes de 60 segundos."
            )

        novo_total = max(1, math.ceil(duracao_narracao / duracao_conteudo_por_parte))
        if novo_total == total_partes:
            break
        total_partes = novo_total
    else:
        raise SystemExit("Nao foi possivel estabilizar o calculo das partes.")

    planos = []
    texto_abertura_card = montar_texto_abertura_card(titulo)
    for indice in range(1, total_partes + 1):
        inicio_conteudo = (indice - 1) * duracao_conteudo_por_parte
        fim_conteudo = min(duracao_narracao, inicio_conteudo + duracao_conteudo_por_parte)
        duracao_conteudo = max(0.01, fim_conteudo - inicio_conteudo)
        caminho_abertura, _ = caminhos_abertura[indice]

        planos.append(
            PartePlano(
                indice=indice,
                total=total_partes,
                inicio_conteudo=inicio_conteudo,
                fim_conteudo=fim_conteudo,
                duracao_conteudo=duracao_conteudo,
                duracao_abertura_slot=duracao_abertura_slot,
                duracao_encerramento_audio=duracao_encerramento_audio,
                caminho_audio_abertura=caminho_abertura,
                caminho_audio_encerramento=caminho_encerramento,
                texto_abertura_card=texto_abertura_card,
                duracao_saida=DURACAO_MAXIMA_PARTE,
            )
        )

    return planos


def criar_palavras_da_parte(palavras, parte: PartePlano):
    palavras_filtradas = []

    for palavra in palavras:
        texto = (_ler_campo(palavra, "word") or "").strip()
        inicio = _ler_campo(palavra, "start")
        fim = _ler_campo(palavra, "end")
        if not texto or inicio is None or fim is None:
            continue

        inicio = float(inicio)
        fim = float(fim)
        if fim <= parte.inicio_conteudo or inicio >= parte.fim_conteudo:
            continue

        inicio_relativo = max(inicio, parte.inicio_conteudo) - parte.inicio_conteudo
        fim_relativo = min(fim, parte.fim_conteudo) - parte.inicio_conteudo

        palavras_filtradas.append(
            {
                "word": texto,
                "start": inicio_relativo + parte.duracao_abertura_slot,
                "end": fim_relativo + parte.duracao_abertura_slot,
            }
        )

    return palavras_filtradas


def renderizar_parte(
    ffmpeg: Path,
    video_fundo: Path,
    audio_narracao: Path,
    legenda: Path,
    texto_abertura: Path,
    texto_encerramento: Path,
    parte: PartePlano,
    video_saida: Path,
) -> Path:
    estilo_legenda = (
        "Alignment=2,"
        f"FontName={FONTE_LEGENDA},"
        f"FontSize={TAMANHO_FONTE_LEGENDA},"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        f"Outline={CONTORNO_LEGENDA},"
        "Shadow=0,"
        "MarginV=110"
    )
    inicio_encerramento = parte.duracao_abertura_slot + parte.duracao_conteudo
    duracao_congelamento_final = parte.duracao_saida - inicio_encerramento
    delay_conteudo_ms = int(round(parte.duracao_abertura_slot * 1000))
    delay_encerramento_ms = int(round(inicio_encerramento * 1000))
    posicao_y_parte = calcular_posicao_y_parte(parte.texto_abertura_card)

    filtro_video = (
        f"[0:v]"
        f"scale={LARGURA_VIDEO}:{ALTURA_VIDEO}:force_original_aspect_ratio=increase,"
        f"crop={LARGURA_VIDEO}:{ALTURA_VIDEO},"
        f"trim=start={parte.inicio_conteudo}:end={parte.fim_conteudo},"
        "setpts=PTS-STARTPTS,"
        f"tpad=start_duration={parte.duracao_abertura_slot}:start_mode=clone:"
        f"stop_duration={duracao_congelamento_final}:stop_mode=clone,"
        "setsar=1,"
        f"subtitles={legenda.name}:force_style='{estilo_legenda}',"
        f"drawtext=font='{FONTE_LEGENDA}':textfile={texto_abertura.name}:"
        f"fontcolor=white:fontsize={TAMANHO_FONTE_TITULO}:"
        f"borderw={CONTORNO_TEXTO_CARD}:bordercolor=black:"
        f"line_spacing={ESPACAMENTO_LINHAS_TITULO}:"
        f"x=(w-text_w)/2:y=(h*{POSICAO_Y_TITULO}):"
        f"enable='between(t,0,{parte.duracao_abertura_slot})',"
        f"drawtext=font='{FONTE_LEGENDA}':text='Parte {parte.indice}/{parte.total}':"
        f"fontcolor=white:fontsize={TAMANHO_FONTE_PARTE}:"
        f"borderw={CONTORNO_TEXTO_CARD}:bordercolor=black:"
        f"x=(w-text_w)/2:y={posicao_y_parte}:"
        f"enable='between(t,0,{parte.duracao_abertura_slot})',"
        f"drawtext=font='{FONTE_LEGENDA}':textfile={texto_encerramento.name}:"
        f"fontcolor=white:fontsize={TAMANHO_FONTE_ENCERRAMENTO}:"
        f"borderw={CONTORNO_TEXTO_CARD}:bordercolor=black:"
        "line_spacing=8:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"enable='between(t,{inicio_encerramento},{parte.duracao_saida})'[v]"
    )
    filtro_audio = (
        f"anullsrc=r=24000:cl=mono:d={parte.duracao_saida}[base];"
        "[1:a]"
        f"atrim=start={parte.inicio_conteudo}:end={parte.fim_conteudo},"
        "asetpts=PTS-STARTPTS,aresample=24000,"
        f"adelay={delay_conteudo_ms}:all=1[audio_conteudo];"
        "[2:a]asetpts=PTS-STARTPTS,aresample=24000[audio_abertura];"
        "[3:a]asetpts=PTS-STARTPTS,aresample=24000,"
        f"adelay={delay_encerramento_ms}:all=1[audio_encerramento];"
        "[base][audio_abertura][audio_conteudo][audio_encerramento]"
        "amix=inputs=4:normalize=0:dropout_transition=0,"
        f"atrim=0:{parte.duracao_saida}[a]"
    )
    filtro_complexo = f"{filtro_video};{filtro_audio}"

    comando = [
        str(ffmpeg),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(video_fundo),
        "-i",
        str(audio_narracao),
        "-i",
        str(parte.caminho_audio_abertura),
        "-i",
        str(parte.caminho_audio_encerramento),
        "-filter_complex",
        filtro_complexo,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-t",
        str(parte.duracao_saida),
        str(video_saida),
    ]

    try:
        subprocess.run(
            comando,
            check=True,
            cwd=str(legenda.parent),
        )
    except subprocess.CalledProcessError as erro:
        raise SystemExit(f"Falha ao renderizar a parte {parte.indice}: {erro}") from erro

    return video_saida


def criar_videos_em_partes(
    client: OpenAI,
    ffmpeg: Path,
    ffprobe: Path,
    video_fundo: Path,
    audio_narracao: Path,
    palavras,
    titulo: str,
    pasta_saida: Path,
    voz: str,
    instrucoes: str,
    status_callback: StatusCallback | None = None,
):
    pasta_partes = pasta_saida / PASTA_PARTES
    pasta_partes.mkdir(parents=True, exist_ok=True)
    limpar_saidas_antigas(pasta_partes)

    informar(status_callback, "Preparando as partes de 1 minuto...")
    planos = preparar_planos_partes(
        client,
        ffprobe,
        palavras,
        titulo,
        pasta_partes,
        voz,
        instrucoes,
        status_callback,
    )

    arquivos_saida = []
    for parte in planos:
        informar(status_callback, f"Renderizando a parte {parte.indice}/{parte.total}...")
        palavras_da_parte = criar_palavras_da_parte(palavras, parte)
        legendas = criar_legendas(palavras_da_parte)

        prefixo = f"parte_{parte.indice:02d}"
        arquivo_legenda = salvar_legendas(legendas, pasta_partes / f"{prefixo}.srt")
        arquivo_texto_abertura = salvar_texto(
            parte.texto_abertura_card,
            pasta_partes / f"{prefixo}_titulo.txt",
        )
        arquivo_texto_encerramento = salvar_texto(
            quebrar_texto(TEXTO_ENCERRAMENTO, 20),
            pasta_partes / f"{prefixo}_encerramento.txt",
        )
        arquivo_video = pasta_partes / f"{prefixo}.mp4"

        renderizar_parte(
            ffmpeg,
            video_fundo,
            audio_narracao,
            arquivo_legenda,
            arquivo_texto_abertura,
            arquivo_texto_encerramento,
            parte,
            arquivo_video,
        )
        arquivos_saida.append(arquivo_video)

    informar(status_callback, "Renderizacao concluida.")
    return arquivos_saida


def processar_video(
    url: str,
    titulo: str,
    texto: str,
    pasta_saida: str | Path = PASTA_SAIDA_PADRAO,
    voz: str = VOZ_PADRAO,
    instrucoes: str = INSTRUCOES_PADRAO,
    status_callback: StatusCallback | None = None,
):
    informar(status_callback, "Carregando ambiente...")
    carregar_env()
    informar(status_callback, "Validando dependencias...")
    ffmpeg, ffprobe = garantir_dependencias()

    pasta_saida = Path(pasta_saida).expanduser().resolve()
    pasta_saida.mkdir(parents=True, exist_ok=True)

    client = OpenAI()
    informar(status_callback, "Baixando o video de fundo do YouTube...")
    video_fundo = baixar_video(url, pasta_saida, ffmpeg)
    informar(status_callback, "Gerando a narracao principal...")
    audio_narracao = gerar_audio(
        client,
        texto,
        pasta_saida / ARQUIVO_AUDIO,
        voz,
        instrucoes,
    )
    informar(status_callback, "Transcrevendo a narracao para montar as legendas...")
    palavras = transcrever_audio(client, audio_narracao)

    return criar_videos_em_partes(
        client,
        ffmpeg,
        ffprobe,
        video_fundo,
        audio_narracao,
        palavras,
        titulo,
        pasta_saida,
        voz,
        instrucoes,
        status_callback,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa um video do YouTube, gera narracao TTS e cria varias partes "
            "de ate 1 minuto com abertura, legenda e encerramento."
        )
    )
    parser.add_argument("url", help="URL do video do YouTube")
    parser.add_argument(
        "-t",
        "--texto",
        default=ARQUIVO_TEXTO_PADRAO,
        help=f"Arquivo com o texto da narracao. Padrao: {ARQUIVO_TEXTO_PADRAO}",
    )
    parser.add_argument(
        "--titulo",
        default=ARQUIVO_TITULO_PADRAO,
        help=f"Arquivo com o titulo base de todas as partes. Padrao: {ARQUIVO_TITULO_PADRAO}",
    )
    parser.add_argument(
        "-o",
        "--saida",
        default=PASTA_SAIDA_PADRAO,
        help=f"Pasta onde os arquivos serao criados. Padrao: {PASTA_SAIDA_PADRAO}",
    )
    parser.add_argument(
        "-v",
        "--voz",
        default=VOZ_PADRAO,
        help=f"Voz do TTS. Padrao: {VOZ_PADRAO}",
    )
    parser.add_argument(
        "--instrucoes",
        default=INSTRUCOES_PADRAO,
        help="Instrucao opcional para controlar o estilo da narracao.",
    )
    args = parser.parse_args()

    texto = ler_texto(args.texto)
    titulo = ler_texto(args.titulo)
    arquivos_saida = processar_video(
        url=args.url,
        titulo=titulo,
        texto=texto,
        pasta_saida=args.saida,
        voz=args.voz,
        instrucoes=args.instrucoes,
    )

    print("Partes geradas com sucesso:")
    for arquivo in arquivos_saida:
        print(arquivo)


if __name__ == "__main__":
    main()
