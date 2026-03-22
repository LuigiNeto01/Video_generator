import argparse
import shutil
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

PASTA_SAIDA_PADRAO = "downloads"
FORMATO_COM_FFMPEG = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/mp4/b"
FORMATO_SEM_FFMPEG = "b[ext=mp4]/mp4/b"


def baixar_video(url: str, pasta_saida: str) -> None:
    destino = Path(pasta_saida).expanduser().resolve()
    destino.mkdir(parents=True, exist_ok=True)

    ffmpeg_disponivel = shutil.which("ffmpeg") is not None
    formato = FORMATO_COM_FFMPEG if ffmpeg_disponivel else FORMATO_SEM_FFMPEG

    opcoes = {
        "format": formato,
        "outtmpl": str(destino / "%(title).200B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "windowsfilenames": True,
    }

    if ffmpeg_disponivel:
        opcoes["merge_output_format"] = "mp4"

    if not ffmpeg_disponivel:
        print(
            "Aviso: ffmpeg nao foi encontrado. "
            "Vou tentar baixar um MP4 unico; a qualidade pode ser menor."
        )

    try:
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            ydl.download([url])
    except DownloadError as erro:
        raise SystemExit(f"Falha ao baixar o video: {erro}") from erro

    print(f"Download concluido. Arquivo salvo em: {destino}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa um video do YouTube e salva em MP4."
    )
    parser.add_argument("url", help="URL do video do YouTube")
    parser.add_argument(
        "-o",
        "--saida",
        default=PASTA_SAIDA_PADRAO,
        help=f"Pasta onde o MP4 sera salvo. Padrao: {PASTA_SAIDA_PADRAO}",
    )
    args = parser.parse_args()

    baixar_video(args.url, args.saida)


if __name__ == "__main__":
    main()
