import os
from pathlib import Path

import streamlit as st
from openai import OpenAI

from criar_video_narrado import INSTRUCOES_PADRAO, VOZ_PADRAO, processar_video

BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_TITULO = BASE_DIR / "titulo.txt"
ARQUIVO_TEXTO = BASE_DIR / "texto.txt"
ARQUIVO_ENV = BASE_DIR / ".env"
PASTA_AMOSTRAS_VOZ = BASE_DIR / "data" / "voz_exemplo"

VOZES_DISPONIVEIS = [
    "alloy", "ash", "ballad", "coral", "echo",
    "fable", "nova", "onyx", "sage", "shimmer", "verse",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ler_texto_inicial(arquivo: Path) -> str:
    if not arquivo.exists():
        return ""
    return arquivo.read_text(encoding="utf-8").strip()


def salvar_texto_arquivo(arquivo: Path, conteudo: str) -> None:
    arquivo.write_text(conteudo.strip(), encoding="utf-8")


def ler_chave_env() -> str:
    chave = os.environ.get("OPENAI_API_KEY", "")
    if chave:
        return chave
    if ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("OPENAI_API_KEY="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def salvar_chave_env(chave: str) -> None:
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


def gerar_historia_ia(tema: str, num_linhas: int) -> tuple[str, str]:
    client = OpenAI()
    resposta = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce e um roteirista criativo de videos curtos para redes sociais. "
                    "Escreva historias envolventes em portugues do Brasil, com linguagem clara e dinamica, "
                    "sem asteriscos nem marcacoes de formatacao."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Crie uma historia sobre o tema: '{tema}'.\n"
                    f"A historia deve ter aproximadamente {num_linhas} linhas de texto.\n"
                    "Responda APENAS neste formato (nada mais):\n"
                    "TITULO: <titulo curto e impactante>\n"
                    "TEXTO: <texto completo da historia, sem repetir o titulo>"
                ),
            },
        ],
        temperature=0.85,
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
    return titulo, "\n".join(linhas_texto).strip()


# ---------------------------------------------------------------------------
# Modal de configuracao da API Key
# ---------------------------------------------------------------------------

@st.dialog("Chave da OpenAI")
def modal_chave_api() -> None:
    chave_atual = ler_chave_env()
    nova_chave = st.text_input(
        "API Key",
        value=chave_atual,
        type="password",
        placeholder="sk-...",
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Salvar", type="primary", use_container_width=True):
            if nova_chave.strip():
                salvar_chave_env(nova_chave.strip())
                st.success("Chave salva com sucesso!")
                st.rerun()
            else:
                st.error("Informe uma chave valida.")
    with col2:
        if st.button("Fechar", use_container_width=True):
            st.rerun()


# ---------------------------------------------------------------------------
# App principal
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Gerador de videos narrados", layout="wide")

    # Cabecalho com botao de API Key
    col_titulo, col_chave = st.columns([5, 1])
    with col_titulo:
        st.title("Gerador de videos narrados")
        st.caption(
            "Gera dois videos: vertical de 1 minuto (1080x1920, audio 1.5x) "
            "e paisagem completo (1920x1080, velocidade normal)."
        )
    with col_chave:
        st.write("")
        chave_ok = bool(ler_chave_env())
        label_btn = "API Key (configurada)" if chave_ok else "API Key (nao configurada)"
        if st.button(label_btn, use_container_width=True, type="secondary"):
            modal_chave_api()

    if not chave_ok:
        st.warning("Configure sua chave da OpenAI antes de continuar.")

    # Session state
    if "titulo" not in st.session_state:
        st.session_state["titulo"] = ler_texto_inicial(ARQUIVO_TITULO)
    if "texto" not in st.session_state:
        st.session_state["texto"] = ler_texto_inicial(ARQUIVO_TEXTO)

    st.divider()

    # --- Secao: conteudo ---
    st.subheader("Conteudo da narracao")

    modo = st.radio(
        "Modo",
        ["Escrever manualmente", "Gerar com IA"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if modo == "Gerar com IA":
        col1, col2 = st.columns([4, 1])
        with col1:
            tema = st.text_input(
                "Tema da historia",
                placeholder="Ex: Uma IA que ganhou consciencia propria",
            )
        with col2:
            num_linhas = st.number_input(
                "Linhas", min_value=3, max_value=60, value=10, step=1
            )

        if st.button("Gerar historia", type="primary"):
            if not tema.strip():
                st.error("Informe o tema da historia.")
            elif not ler_chave_env():
                st.error("Configure a chave da OpenAI primeiro.")
            else:
                with st.spinner("Gerando historia com IA..."):
                    try:
                        titulo_ia, texto_ia = gerar_historia_ia(tema.strip(), int(num_linhas))
                        st.session_state["titulo"] = titulo_ia
                        st.session_state["texto"] = texto_ia
                        st.rerun()
                    except Exception as erro:
                        st.error(f"Erro ao gerar historia: {erro}")

        st.write("")

    titulo = st.text_input("Titulo", key="titulo")
    texto = st.text_area("Texto da narracao", height=280, key="texto")

    st.divider()

    # --- Secao: configuracoes do video ---
    st.subheader("Video")

    url = st.text_input("Link do video do YouTube")

    col1, col2, col3 = st.columns(3)
    with col1:
        pasta_saida = st.text_input("Pasta de saida", value="video_narrado")
    with col2:
        indice_padrao = VOZES_DISPONIVEIS.index(VOZ_PADRAO) if VOZ_PADRAO in VOZES_DISPONIVEIS else 0
        voz = st.selectbox("Voz", options=VOZES_DISPONIVEIS, index=indice_padrao)
        amostra = PASTA_AMOSTRAS_VOZ / f"{voz}.mp3"
        if amostra.exists():
            with st.expander("Ouvir exemplo desta voz"):
                st.audio(str(amostra), format="audio/mp3")
    with col3:
        instrucoes = st.text_input("Instrucoes da voz", value=INSTRUCOES_PADRAO)

    st.write("")
    gerar = st.button("Gerar videos", type="primary", use_container_width=True)

    if not gerar:
        return

    titulo_final = titulo.strip()
    texto_final = texto.strip()

    if not url.strip():
        st.error("Informe o link do video.")
        return
    if not titulo_final:
        st.error("Informe o titulo.")
        return
    if not texto_final:
        st.error("Informe o texto da narracao.")
        return
    if not ler_chave_env():
        st.error("Configure a chave da OpenAI primeiro.")
        return

    salvar_texto_arquivo(ARQUIVO_TITULO, titulo_final)
    salvar_texto_arquivo(ARQUIVO_TEXTO, texto_final)

    mensagens: list[str] = []
    status_box = st.empty()

    def atualizar_status(mensagem: str) -> None:
        mensagens.append(mensagem)
        status_box.code("\n".join(mensagens[-10:]))

    try:
        with st.spinner("Gerando os videos, isso pode levar alguns minutos..."):
            arquivos_saida = processar_video(
                url=url.strip(),
                titulo=titulo_final,
                texto=texto_final,
                pasta_saida=BASE_DIR / pasta_saida.strip(),
                voz=voz,
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

    nomes = {
        "video_vertical.mp4": "Video vertical (1080x1920, 1.5x)",
        "video_paisagem.mp4": "Video paisagem (1920x1080, normal)",
    }
    col1, col2 = st.columns(2)
    for coluna, arquivo in zip([col1, col2], arquivos_saida):
        with coluna:
            st.subheader(nomes.get(arquivo.name, arquivo.name))
            st.video(str(arquivo))


if __name__ == "__main__":
    main()
