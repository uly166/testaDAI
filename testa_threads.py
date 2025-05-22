import base64
import json
import tempfile
from pathlib import Path
import pandas as pd
from pygwalker.api.streamlit import StreamlitRenderer

import streamlit as st
from cryptography.fernet import Fernet
from openai import OpenAI

MODEL_PRICES = {
    # precio por 1K tokens
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4.1-nano": {"input": 0.0001, "output": 0.0004},
    "gpt-4.1-mini": {"input": 0.0004, "output": 0.0016},
    "gpt-4": {"input": 0.03, "output": 0.06},
}


@st.cache_resource
def get_pyg_renderer(df) -> "StreamlitRenderer":
    return StreamlitRenderer(df)


def decode_data(string_data):
    key = st.secrets["key"]
    cipher = Fernet(key.encode())

    data_decodificado = base64.urlsafe_b64decode(string_data.encode()).decode()
    data_decriptado = cipher.decrypt(data_decodificado.encode()).decode()
    return data_decriptado


def add_debug(clave, valor):
    st.session_state.debug.append([clave, valor])


def cargar_datos_thread(thread_id, client):
    runs = client.beta.threads.runs.list(thread_id=thread_id)
    total_price, total_tokens = 0., 0.
    if runs:
        for run in runs:
            total_tokens += run.usage.total_tokens
            model = run.model
            if model in MODEL_PRICES:
                total_price += MODEL_PRICES[model]['input'] * run.usage.prompt_tokens
                total_price += MODEL_PRICES[model]['output'] * run.usage.completion_tokens

    st.session_state['total_price'] = f"${total_price / 1000:.2f}"
    st.session_state['total_tokens'] = total_tokens

    return


def get_messages(id_thread, client):
    cargar_datos_thread(id_thread, client)

    messages = client.beta.threads.messages.list(thread_id=id_thread)
    st.session_state.messages = []
    for i, message in enumerate(messages):
        for item in message.content:
            text_content = ""
            file_name = ""

            if item.type == "text":
                content = item.text.value

                for annotation in item.text.annotations:
                    item.type = "file"
                    text_content = item.text.value

                    if annotation.type == "file_path":
                        text = annotation.text
                        suffix = text.split('.')[-1]
                        content = process_file(annotation.file_path.file_id, client, suffix=suffix)
                        file_name = text
            elif item.type == "image_file":
                content = process_file(item.image_file.file_id, client, suffix="png")
            else:
                print(f"Tipo no reconocido {item.type}")

            dc = {
                "type": item.type,
                "role": message.role,
                "item": item,
                "content": content,
                "text_content": text_content,
                "file_name": file_name,

            }
            add_debug("messages", dc)

            st.session_state.messages.append(dc)

    return messages


# Función para generar respuestas
def generate_response(prompt):
    client = st.session_state.client
    if not st.session_state.id_thread:
        thread = client.beta.threads.create()
        st.session_state.id_thread = thread.id
    id_thread = st.session_state.id_thread
    id_assistant = st.session_state.id_assistant

    client.beta.threads.messages.create(
        thread_id=id_thread,
        role="user",
        content=prompt
    )

    # Ejecutar el asistente
    run = client.beta.threads.runs.create(
        thread_id=id_thread,
        assistant_id=id_assistant
    )

    # Esperar y obtener la respuesta
    while True:
        run_status = client.beta.threads.runs.retrieve(
            thread_id=id_thread,
            run_id=run.id
        )
        if run_status.status in ["completed", "failed"]:
            break

    messages = get_messages(id_thread, client)

    return messages


def process_file(file_id, client, suffix="csv"):
    # Descargar la imagen
    data = client.files.content(file_id)
    data_bytes = data.read()

    # Guardar temporalmente para mostrarla
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(data_bytes)
        return tmp_file.name


def format_price(price):
    """Formatea el precio para mostrarlo en dólares"""
    return f"${price * 1000:.2f} por 750,000 palabras"


#
#
if "client" not in st.session_state:
    st.session_state.client = None
if "id_assistant" not in st.session_state:
    st.session_state.id_assistant = None
if "assistant" not in st.session_state:
    st.session_state.assistant = None
if "file_ids" not in st.session_state:
    st.session_state.file_ids = None
if "id_thread" not in st.session_state:
    st.session_state.id_thread = None

if "total_price" not in st.session_state:
    st.session_state.total_price = None
if "total_tokens" not in st.session_state:
    st.session_state.total_tokens = None
if "messages" not in st.session_state:
    st.session_state.messages = []

if "debug" not in st.session_state:
    st.session_state.debug = []

st.set_page_config(
    page_title="TestaDAI",
    layout="wide",
    page_icon=Path("img/icon_ERP_256.ico"),  # Archivo local (o .ico)
)
#
if not st.session_state.id_assistant:
    client = None

    if st.query_params:
        try:
            data = st.query_params['data']
            data_json = json.loads(decode_data(data))

            api_key = data_json["key"]
            id_assistant = data_json["assistant"]
            file_ids = data_json["file_ids"]

            client = OpenAI(api_key=api_key)

        except Exception as e:
            st.write(f"Error al procesar url :{e}")

    if client:
        assistant = client.beta.assistants.retrieve(id_assistant)
        if assistant:
            st.session_state.client = client
            st.session_state.id_assistant = id_assistant
            st.session_state.assistant = assistant
            st.session_state.file_ids = file_ids
            st.title(assistant.name)
            add_debug("assistant", assistant)

            for tool_resource in assistant.tool_resources:
                type_tool_resource = tool_resource[0]
                if type_tool_resource == "code_interpreter":
                    type_data_tool_resource = tool_resource[1]
                    for file_id in type_data_tool_resource.file_ids:
                        file_data = client.files.retrieve(file_id=file_id)
                        file_name = file_data.filename
                        st.write(f"Fichero asistente :  {file_name}")

            id_thread = st.session_state.id_thread
            if id_thread:
                get_messages(id_thread, client)

if not st.session_state.id_assistant:
    st.markdown("<h2 style='text-align: center;'>⚠️ TOKEN INCORRECTO ⚠️</h2>", unsafe_allow_html=True)
    st.stop()

if "assistant" in st.session_state:
    modelo_seleccionado = st.session_state.assistant.model

with st.sidebar:
    with st.expander("✨ Debug"):
        modo_debug = st.checkbox("Modo debug")
        #if st.button("Nueva conversacion"):
        #    st.session_state.id_thread = None
        st.write(f"id_thread {st.session_state.id_thread}")
        st.subheader(f"Precios para {modelo_seleccionado}:")
        if modelo_seleccionado in MODEL_PRICES:
            prices = MODEL_PRICES[modelo_seleccionado]
            st.write(f"📥 **Entrada (input):** {format_price(prices['input'])}")
            st.write(f"📤 **Salida (output):** {format_price(prices['output'])}")

        # Información adicional
        st.info("""
        💡 Los precios son aproximados y pueden variar. Consulta la documentación oficial de OpenAI para precios actualizados.
        [Precios actualizados](https://openai.com/es-ES/api/pricing/)
        """)

col1, col2 = st.columns(2)
with col1:
    st.header("Datos")
    # Cargamos dataframes, vamos a suponer varios
    client = st.session_state.client
    file_ids = st.session_state.file_ids
    add_debug("id_files", file_ids)

    if file_ids:
        visor_avanzado = st.checkbox("Visor Avanzado")

        for dc in file_ids:
            id_file = dc["id"]
            name = dc["name"]
            st.write(name)
            uploaded_file = process_file(id_file, client)
            df = pd.read_csv(uploaded_file)  # Archivo en UTF-8
            if visor_avanzado:
                renderer = get_pyg_renderer(df)
                renderer.explorer()

            else:
                st.dataframe(df)  # Same as st.write(df)

with col2:
    col2_1, col2_2, col2_3, col2_4 = st.columns([1, 2, 1, 1])

    # Importante, ya que se actualizan anteriormente
    total_price = st.session_state['total_price']
    total_tokens = st.session_state['total_tokens']

    col2_1.header("Chat")
    col2_2.metric("🤖 **Modelo**", modelo_seleccionado)
    col2_3.metric("💰 **Coste**", total_price, help="Costo total de los tokens usados")
    col2_4.metric("🔢 **Tokens**", total_tokens, help="Tokens consumidos en la consulta")

    if prompt := st.chat_input("Haz una pregunta sobre el archivo..."):
        with st.chat_message("assistant"):
            with st.spinner("Analizando archivo..."):
                generate_response(prompt)
    with st.container():
        for msg in st.session_state.messages:
            if msg["role"] != "system":
                with st.chat_message(msg["role"]):
                    if msg["type"] == "text":
                        st.markdown(msg["content"])
                    elif msg["type"] == "image_file":
                        st.image(msg["content"], caption="Imagen generada")
                    elif msg["type"] == "file":
                        st.markdown(msg["text_content"])
                        st.download_button("Descargar documento", data=open(msg["content"], 'r'),
                                           file_name=msg["file_name"], use_container_width=True, icon="📥")

if modo_debug:
    st.subheader("Debug activado")

    st.json(st.session_state.debug)
