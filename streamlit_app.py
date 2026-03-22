from pathlib import Path

import streamlit as st

from criar_video_narrado import INSTRUCOES_PADRAO, VOZ_PADRAO, processar_video

BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_TITULO = BASE_DIR / "titulo.txt"
ARQUIVO_TEXTO = BASE_DIR / "texto.txt"


def ler_texto_inicial(arquivo: Path) -> str:
    if not arquivo.exists():
        return ""
    return arquivo.read_text(encoding="utf-8").strip()


def salvar_texto(arquivo: Path, conteudo: str) -> None:
    arquivo.write_text(conteudo.strip(), encoding="utf-8")


def main() -> None:
    st.set_page_config(page_title="Gerador de videos narrados", layout="wide")
    st.title("Gerador de videos narrados")
    st.caption(
        "Preencha o titulo, o texto e o link do video. O app gera as partes "
        "de 1 minuto com abertura, legenda e encerramento."
    )

    with st.form("formulario_video"):
        url = st.text_input("Link do video do YouTube")
        titulo = st.text_input("Titulo", value=ler_texto_inicial(ARQUIVO_TITULO))
        texto = st.text_area(
            "Texto da narracao",
            value=ler_texto_inicial(ARQUIVO_TEXTO),
            height=320,
        )

        coluna1, coluna2 = st.columns(2)
        with coluna1:
            pasta_saida = st.text_input("Pasta de saida", value="video_narrado")
        with coluna2:
            voz = st.text_input("Voz", value=VOZ_PADRAO)

        instrucoes = st.text_input("Instrucoes da voz", value=INSTRUCOES_PADRAO)
        enviar = st.form_submit_button("Gerar videos")

    if not enviar:
        return

    if not url.strip():
        st.error("Informe o link do video.")
        return
    if not titulo.strip():
        st.error("Informe o titulo.")
        return
    if not texto.strip():
        st.error("Informe o texto da narracao.")
        return

    salvar_texto(ARQUIVO_TITULO, titulo)
    salvar_texto(ARQUIVO_TEXTO, texto)

    mensagens: list[str] = []
    status_box = st.empty()

    def atualizar_status(mensagem: str) -> None:
        mensagens.append(mensagem)
        status_box.code("\n".join(mensagens[-10:]))

    try:
        with st.spinner("Gerando os videos, isso pode levar alguns minutos..."):
            arquivos_saida = processar_video(
                url=url.strip(),
                titulo=titulo.strip(),
                texto=texto.strip(),
                pasta_saida=BASE_DIR / pasta_saida.strip(),
                voz=voz.strip() or VOZ_PADRAO,
                instrucoes=instrucoes.strip() or INSTRUCOES_PADRAO,
                status_callback=atualizar_status,
            )
    except SystemExit as erro:
        st.error(str(erro))
        return
    except Exception as erro:
        st.exception(erro)
        return

    st.success("Videos gerados com sucesso.")
    st.subheader("Arquivos gerados")
    for arquivo in arquivos_saida:
        st.write(str(arquivo))

    if arquivos_saida:
        st.subheader("Preview da primeira parte")
        st.video(str(arquivos_saida[0]))


if __name__ == "__main__":
    main()
