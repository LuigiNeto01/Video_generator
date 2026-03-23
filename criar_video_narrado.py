import argparse
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
ARQUIVO_VIDEO_BASE = "background.mp4"
ARQUIVO_AUDIO = "narracao.mp3"
MODELO_TTS = "gpt-4o-mini-tts"
MODELO_TRANSCRICAO = "whisper-1"
VOZ_PADRAO = "coral"

# Portrait (vertical) — 1080x1920, audio 1.5x, max 60s
LARGURA_VERTICAL = 1080
ALTURA_VERTICAL = 1920
VELOCIDADE_AUDIO_VERTICAL = 1.5
DURACAO_MAXIMA_VERTICAL = 60.0
NOME_VIDEO_VERTICAL = "video_vertical.mp4"

# Landscape — 1920x1080, velocidade normal, duracao completa
LARGURA_PAISAGEM = 1920
ALTURA_PAISAGEM = 1080
NOME_VIDEO_PAISAGEM = "video_paisagem.mp4"

# Legendas
FONTE_LEGENDA = "Janda Manatee Solid"
TAMANHO_FONTE_LEGENDA_VERTICAL = 24
TAMANHO_FONTE_LEGENDA_PAISAGEM = 32
CONTORNO_LEGENDA = 3
MAX_CARACTERES_LEGENDA = 12

# Overlays de texto
TAMANHO_FONTE_TITULO_VERTICAL = 44
TAMANHO_FONTE_TITULO_PAISAGEM = 56
CONTORNO_TEXTO = 3
MAX_CARACTERES_TITULO_VERTICAL = 32
MAX_CARACTERES_TITULO_PAISAGEM = 45
ESPACAMENTO_LINHAS_TITULO = -10
POSICAO_Y_TITULO = 0.10

TAMANHO_FONTE_ENCERRAMENTO = 48
TEXTO_ENCERRAMENTO_VERTICAL = "Parte 2 no link da bio"
DURACAO_OVERLAY_ENCERRAMENTO = 5.0

INSTRUCOES_PADRAO = (
    "Fale com naturalidade, em portugues do Brasil, com ritmo claro e envolvente."
)

StatusCallback = Callable[[str], None]


@dataclass
class Legenda:
    inicio: float
    fim: float
    texto: str


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
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
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
        palavras_divididas.append({"texto": parte, "inicio": inicio_parte, "fim": fim_parte})
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
                    Legenda(inicio=inicio_bloco, fim=bloco[-1]["fim"], texto=texto_bloco)
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
                    Legenda(inicio=inicio_bloco, fim=bloco[-1]["fim"], texto=texto_bloco)
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


def criar_legendas_velocidade(palavras, velocidade: float, duracao_maxima: float):
    """Cria legendas com timestamps ajustados pela velocidade, limitadas a duracao_maxima."""
    palavras_ajustadas = []
    for palavra in palavras:
        texto = (_ler_campo(palavra, "word") or "").strip()
        inicio = _ler_campo(palavra, "start")
        fim = _ler_campo(palavra, "end")
        if not texto or inicio is None or fim is None:
            continue
        inicio_adj = float(inicio) / velocidade
        fim_adj = float(fim) / velocidade
        if inicio_adj >= duracao_maxima:
            break
        palavras_ajustadas.append({
            "word": texto,
            "start": inicio_adj,
            "end": min(fim_adj, duracao_maxima),
        })
    return criar_legendas(palavras_ajustadas)


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
            f"{formatar_tempo_srt(legenda.inicio)} --> {formatar_tempo_srt(legenda.fim)}"
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


def encontrar_duracao_titulo(palavras, titulo: str) -> float:
    """Estima o tempo de fim do titulo na transcricao pelo numero de palavras."""
    num_palavras = len(titulo.split())
    if num_palavras > 0 and len(palavras) >= num_palavras:
        return float(_ler_campo(palavras[num_palavras - 1], "end") or 3.0)
    return 3.0


def renderizar_video_vertical(
    ffmpeg: Path,
    video_fundo: Path,
    audio_narracao: Path,
    legenda: Path,
    texto_titulo: Path,
    texto_encerramento: Path,
    duracao_titulo: float,
    duracao_saida: float,
    video_saida: Path,
) -> Path:
    """Renderiza o video 1080x1920 com audio a 1.5x e overlay de encerramento."""
    estilo_legenda = (
        "Alignment=2,"
        f"FontName={FONTE_LEGENDA},"
        f"FontSize={TAMANHO_FONTE_LEGENDA_VERTICAL},"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        f"Outline={CONTORNO_LEGENDA},"
        "Shadow=0,"
        "MarginV=110"
    )
    inicio_encerramento = max(0.0, duracao_saida - DURACAO_OVERLAY_ENCERRAMENTO)

    filtro_video = (
        f"[0:v]"
        f"scale={LARGURA_VERTICAL}:{ALTURA_VERTICAL}:force_original_aspect_ratio=increase,"
        f"crop={LARGURA_VERTICAL}:{ALTURA_VERTICAL},"
        "setpts=PTS-STARTPTS,"
        "setsar=1,"
        f"subtitles={legenda.name}:force_style='{estilo_legenda}',"
        f"drawtext=font='{FONTE_LEGENDA}':textfile={texto_titulo.name}:"
        f"fontcolor=white:fontsize={TAMANHO_FONTE_TITULO_VERTICAL}:"
        f"borderw={CONTORNO_TEXTO}:bordercolor=black:"
        f"line_spacing={ESPACAMENTO_LINHAS_TITULO}:"
        f"x=(w-text_w)/2:y=(h*{POSICAO_Y_TITULO}):"
        f"enable='between(t,0,{duracao_titulo:.3f})',"
        f"drawtext=font='{FONTE_LEGENDA}':textfile={texto_encerramento.name}:"
        f"fontcolor=white:fontsize={TAMANHO_FONTE_ENCERRAMENTO}:"
        f"borderw={CONTORNO_TEXTO}:bordercolor=black:"
        "line_spacing=8:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"enable='between(t,{inicio_encerramento:.3f},{duracao_saida:.3f})'[v]"
    )
    filtro_audio = (
        f"[1:a]atempo={VELOCIDADE_AUDIO_VERTICAL},"
        f"atrim=0:{duracao_saida:.3f},"
        "asetpts=PTS-STARTPTS[a]"
    )
    filtro_complexo = f"{filtro_video};{filtro_audio}"

    comando = [
        str(ffmpeg), "-y",
        "-stream_loop", "-1",
        "-i", str(video_fundo),
        "-i", str(audio_narracao),
        "-filter_complex", filtro_complexo,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{duracao_saida:.3f}",
        str(video_saida),
    ]

    try:
        subprocess.run(comando, check=True, cwd=str(legenda.parent))
    except subprocess.CalledProcessError as erro:
        raise SystemExit(f"Falha ao renderizar o video vertical: {erro}") from erro

    return video_saida


def renderizar_video_paisagem(
    ffmpeg: Path,
    video_fundo: Path,
    audio_narracao: Path,
    legenda: Path,
    texto_titulo: Path,
    duracao_titulo: float,
    duracao_saida: float,
    video_saida: Path,
) -> Path:
    """Renderiza o video 1920x1080 com audio em velocidade normal e duracao completa."""
    estilo_legenda = (
        "Alignment=2,"
        f"FontName={FONTE_LEGENDA},"
        f"FontSize={TAMANHO_FONTE_LEGENDA_PAISAGEM},"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        f"Outline={CONTORNO_LEGENDA},"
        "Shadow=0,"
        "MarginV=60"
    )

    filtro_video = (
        f"[0:v]"
        f"scale={LARGURA_PAISAGEM}:{ALTURA_PAISAGEM}:force_original_aspect_ratio=increase,"
        f"crop={LARGURA_PAISAGEM}:{ALTURA_PAISAGEM},"
        "setpts=PTS-STARTPTS,"
        "setsar=1,"
        f"subtitles={legenda.name}:force_style='{estilo_legenda}',"
        f"drawtext=font='{FONTE_LEGENDA}':textfile={texto_titulo.name}:"
        f"fontcolor=white:fontsize={TAMANHO_FONTE_TITULO_PAISAGEM}:"
        f"borderw={CONTORNO_TEXTO}:bordercolor=black:"
        f"line_spacing={ESPACAMENTO_LINHAS_TITULO}:"
        f"x=(w-text_w)/2:y=(h*{POSICAO_Y_TITULO}):"
        f"enable='between(t,0,{duracao_titulo:.3f})'[v]"
    )

    comando = [
        str(ffmpeg), "-y",
        "-stream_loop", "-1",
        "-i", str(video_fundo),
        "-i", str(audio_narracao),
        "-filter_complex", filtro_video,
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{duracao_saida:.3f}",
        str(video_saida),
    ]

    try:
        subprocess.run(comando, check=True, cwd=str(legenda.parent))
    except subprocess.CalledProcessError as erro:
        raise SystemExit(f"Falha ao renderizar o video paisagem: {erro}") from erro

    return video_saida


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

    # A narracao comeca com o titulo e depois conta a historia
    texto_narracao = f"{titulo}. {texto}"

    informar(status_callback, "Gerando a narracao principal...")
    audio_narracao = gerar_audio(
        client, texto_narracao, pasta_saida / ARQUIVO_AUDIO, voz, instrucoes
    )

    informar(status_callback, "Transcrevendo a narracao para montar as legendas...")
    palavras = transcrever_audio(client, audio_narracao)

    duracao_narracao = obter_duracao_midia(ffprobe, audio_narracao)
    duracao_titulo = encontrar_duracao_titulo(palavras, titulo)

    # Arquivos de texto para os overlays (drawtext)
    arquivo_titulo_vertical = salvar_texto(
        quebrar_texto(titulo, MAX_CARACTERES_TITULO_VERTICAL),
        pasta_saida / "titulo_vertical.txt",
    )
    arquivo_titulo_paisagem = salvar_texto(
        quebrar_texto(titulo, MAX_CARACTERES_TITULO_PAISAGEM),
        pasta_saida / "titulo_paisagem.txt",
    )
    arquivo_encerramento = salvar_texto(
        quebrar_texto(TEXTO_ENCERRAMENTO_VERTICAL, 22),
        pasta_saida / "encerramento.txt",
    )

    # --- Video vertical (1080x1920, 1.5x, max 60s) ---
    duracao_vertical = min(duracao_narracao / VELOCIDADE_AUDIO_VERTICAL, DURACAO_MAXIMA_VERTICAL)
    duracao_titulo_vertical = duracao_titulo / VELOCIDADE_AUDIO_VERTICAL

    informar(status_callback, "Criando legendas para o video vertical (1.5x)...")
    legendas_vertical = criar_legendas_velocidade(palavras, VELOCIDADE_AUDIO_VERTICAL, duracao_vertical)
    arquivo_srt_vertical = salvar_legendas(legendas_vertical, pasta_saida / "legendas_vertical.srt")

    informar(status_callback, "Renderizando o video vertical (1080x1920, audio 1.5x)...")
    arquivo_vertical = renderizar_video_vertical(
        ffmpeg,
        video_fundo,
        audio_narracao,
        arquivo_srt_vertical,
        arquivo_titulo_vertical,
        arquivo_encerramento,
        duracao_titulo_vertical,
        duracao_vertical,
        pasta_saida / NOME_VIDEO_VERTICAL,
    )

    # --- Video paisagem (1920x1080, velocidade normal, duracao completa) ---
    informar(status_callback, "Criando legendas para o video paisagem (velocidade normal)...")
    legendas_paisagem = criar_legendas(palavras)
    arquivo_srt_paisagem = salvar_legendas(legendas_paisagem, pasta_saida / "legendas_paisagem.srt")

    informar(status_callback, "Renderizando o video paisagem (1920x1080, velocidade normal)...")
    arquivo_paisagem = renderizar_video_paisagem(
        ffmpeg,
        video_fundo,
        audio_narracao,
        arquivo_srt_paisagem,
        arquivo_titulo_paisagem,
        duracao_titulo,
        duracao_narracao,
        pasta_saida / NOME_VIDEO_PAISAGEM,
    )

    informar(status_callback, "Renderizacao concluida.")
    return [arquivo_vertical, arquivo_paisagem]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa um video do YouTube, gera narracao TTS e cria dois videos: "
            "vertical de 1 minuto (1.5x) e paisagem em velocidade normal."
        )
    )
    parser.add_argument("url", help="URL do video do YouTube")
    parser.add_argument(
        "-t", "--texto",
        default=ARQUIVO_TEXTO_PADRAO,
        help=f"Arquivo com o texto da narracao. Padrao: {ARQUIVO_TEXTO_PADRAO}",
    )
    parser.add_argument(
        "--titulo",
        default=ARQUIVO_TITULO_PADRAO,
        help=f"Arquivo com o titulo. Padrao: {ARQUIVO_TITULO_PADRAO}",
    )
    parser.add_argument(
        "-o", "--saida",
        default=PASTA_SAIDA_PADRAO,
        help=f"Pasta onde os arquivos serao criados. Padrao: {PASTA_SAIDA_PADRAO}",
    )
    parser.add_argument(
        "-v", "--voz",
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

    print("Videos gerados com sucesso:")
    for arquivo in arquivos_saida:
        print(arquivo)


if __name__ == "__main__":
    main()
