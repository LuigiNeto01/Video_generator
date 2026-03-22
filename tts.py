import argparse
import os
from pathlib import Path

from openai import OpenAI

ARQUIVO_TEXTO_PADRAO = "texto.txt"
ARQUIVO_AUDIO_PADRAO = "audio.mp3"
MODELO_TTS = "gpt-4o-mini-tts"
VOZ_PADRAO = "coral"
INSTRUCOES_PADRAO = "Fale com voz natural, clara e agradavel em portugues do Brasil."


def ler_texto(caminho_arquivo: str) -> str:
    arquivo = Path(caminho_arquivo).expanduser().resolve()
    if not arquivo.exists():
        raise SystemExit(f"Arquivo de texto nao encontrado: {arquivo}")

    texto = arquivo.read_text(encoding="utf-8").strip()
    if not texto:
        raise SystemExit(f"O arquivo esta vazio: {arquivo}")

    return texto


def gerar_audio(
    texto: str,
    arquivo_saida: str,
    voz: str,
    instrucoes: str,
) -> Path:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit(
            "Defina a variavel de ambiente OPENAI_API_KEY antes de executar o script."
        )

    destino = Path(arquivo_saida).expanduser().resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)

    client = OpenAI()
    with client.audio.speech.with_streaming_response.create(
        model=MODELO_TTS,
        voice=voz,
        input=texto,
        instructions=instrucoes,
        response_format="mp3",
    ) as response:
        response.stream_to_file(destino)

    return destino


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Le um texto de um arquivo e gera um MP3 usando o modelo gpt-4o-mini-tts."
    )
    parser.add_argument(
        "-t",
        "--texto",
        default=ARQUIVO_TEXTO_PADRAO,
        help=f"Arquivo com o texto de entrada. Padrao: {ARQUIVO_TEXTO_PADRAO}",
    )
    parser.add_argument(
        "-o",
        "--saida",
        default=ARQUIVO_AUDIO_PADRAO,
        help=f"Arquivo MP3 de saida. Padrao: {ARQUIVO_AUDIO_PADRAO}",
    )
    parser.add_argument(
        "-v",
        "--voz",
        default=VOZ_PADRAO,
        help=f"Voz usada na geracao. Padrao: {VOZ_PADRAO}",
    )
    parser.add_argument(
        "--instrucoes",
        default=INSTRUCOES_PADRAO,
        help="Instrucao opcional para controlar tom, ritmo ou estilo da fala.",
    )
    args = parser.parse_args()

    texto = ler_texto(args.texto)
    arquivo = gerar_audio(texto, args.saida, args.voz, args.instrucoes)
    print(f"Audio gerado com sucesso em: {arquivo}")


if __name__ == "__main__":
    main()
