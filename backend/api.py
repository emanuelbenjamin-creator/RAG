import os
import json
import time
import random
import queue
import threading
import traceback
import requests
from collections import OrderedDict

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from supabase import create_client
from typesafe_sdk import TypeSafeClient, Noul

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ilvssohttgguxdijhuyo.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # sigue usándose SOLO para la generación (LLM)
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")  # CAMBIO: nueva, para embeddings de la query
TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")

# [MEJORA 8] Diagnóstico sin exponer ningún fragmento de la key.
print(f"[DEBUG] GEMINI_API_KEY presente: {bool(GEMINI_API_KEY)}")
print(f"[DEBUG] VOYAGE_API_KEY presente: {bool(VOYAGE_API_KEY)}")
print(f"[DEBUG] SUPABASE_KEY presente: {bool(SUPABASE_KEY)}")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY, VOYAGE_API_KEY]):
    raise SystemExit(
        "[ERROR] Faltan variables de entorno: SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY o "
        "VOYAGE_API_KEY. Revisa la configuración de Environment variables en Northflank."
    )

# CAMBIO: embeddings ahora con Voyage. Misma dimensión (1024) que ya usa la
# tabla en Supabase — NO se toca match_documentos ni el esquema.
VOYAGE_URL = "https://ai.mongodb.com/v1/embeddings"
VOYAGE_MODEL = "voyage-4-lite"
EMBEDDING_DIM = 1024  # sin cambios: default de voyage-4-lite = default anterior de Gemini

MATCH_THRESHOLD = 0.65
MATCH_COUNT = 8

MATCH_COUNT_COMPUESTA = 14
PALABRAS_UMBRAL_COMPUESTA = 25
SIGNOS_INTERROGACION_UMBRAL_COMPUESTA = 2

MARCADOR_SUGERENCIAS = "---SUGERENCIAS---"

# La generación de texto (LLM) sigue en Gemini, sin cambios. Solo el
# embedding de la query pasó a Voyage.
MODELOS_CHAIN = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite"]

MAX_INTENTOS_POR_MODELO = 2
ESPERA_REINTENTO_S = 0.8
TIMEOUT_LLAMADA_MS = 45_000
TIMEOUT_DESCOMPOSICION_MS = 8_000
DEADLINE_TOTAL_S = 60

HEDGE_DELAY_S = float(os.getenv("HEDGE_DELAY_S", "3"))

CONFIG_LLM = types.GenerateContentConfig(
    http_options=types.HttpOptions(timeout=TIMEOUT_LLAMADA_MS),
)
CONFIG_DESCOMPOSICION = types.GenerateContentConfig(
    http_options=types.HttpOptions(timeout=TIMEOUT_DESCOMPOSICION_MS),
)

COOLDOWN_MODELO_S = 60
_modelos_saturados: dict = {}
_saturados_lock = threading.Lock()


def _marcar_saturado(modelo: str) -> None:
    with _saturados_lock:
        _modelos_saturados[modelo] = time.monotonic() + COOLDOWN_MODELO_S


def _modelos_en_orden() -> list:
    ahora = time.monotonic()
    with _saturados_lock:
        sanos = [m for m in MODELOS_CHAIN if _modelos_saturados.get(m, 0) <= ahora]
    saturados = [m for m in MODELOS_CHAIN if m not in sanos]
    return sanos + saturados


CACHE_TTL_S = int(os.getenv("CACHE_TTL_S", "21600"))
CACHE_MAX_ENTRADAS = 200
_cache: "OrderedDict[str, dict]" = OrderedDict()
_cache_lock = threading.Lock()


def _clave_cache(consulta) -> str:
    return " ".join(consulta.pregunta.lower().split())


def _cache_get(clave: str):
    with _cache_lock:
        item = _cache.get(clave)
        if item is None:
            return None
        if item["expira"] < time.monotonic():
            del _cache[clave]
            return None
        _cache.move_to_end(clave)
        return item["valor"]


def _cache_set(clave: str, valor: dict) -> None:
    with _cache_lock:
        _cache[clave] = {"expira": time.monotonic() + CACHE_TTL_S, "valor": valor}
        _cache.move_to_end(clave)
        while len(_cache) > CACHE_MAX_ENTRADAS:
            _cache.popitem(last=False)


def es_pregunta_compuesta(pregunta: str) -> bool:
    n_palabras = len(pregunta.split())
    n_signos = pregunta.count("?") + pregunta.count("¿")
    return n_palabras > PALABRAS_UMBRAL_COMPUESTA or n_signos > SIGNOS_INTERROGACION_UMBRAL_COMPUESTA


app = FastAPI(title="API Asistente Tributario SUNAT")

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)  # sigue usándose solo para generar texto

if TYPESAFE_API_KEY:
    typesafe_client = TypeSafeClient()
    print("[DEBUG] TYPESAFE_API_KEY presente: filtro de alcance con Jev activado.")
else:
    typesafe_client = None
    print("[DEBUG] TYPESAFE_API_KEY no configurada: filtro de alcance con Jev desactivado "
          "(todas las preguntas pasan por Supabase/Gemini como antes).")

UMBRAL_EN_ALCANCE = 0.5

TEMAS_EN_ALCANCE = (
    "comprobantes de pago peruanos (facturas, boletas, notas de crédito/débito, "
    "guías de remisión, recibos por honorarios electrónicos, normativa SUNAT de "
    "emisión y requisitos) o sobre impuesto a la renta peruano (categorías de "
    "renta, gastos deducibles, depreciación, pagos a cuenta, retenciones, TUO de "
    "la Ley del Impuesto a la Renta, Código Tributario)"
)

MENSAJE_FUERA_DE_ALCANCE = (
    "Por ahora solo puedo ayudarte con normativa de comprobantes de pago (SUNAT) "
    "e impuesto a la renta. Esa pregunta está fuera de lo que puedo responder todavía."
)


@app.get("/health")
def health():
    return {"status": "ok"}


def es_pregunta_fuera_de_alcance(pregunta: str) -> bool:
    if typesafe_client is None:
        return False
    try:
        respuesta = typesafe_client.system_one(
            state={"pregunta": pregunta},
            questions={
                "en_alcance": Noul(
                    instructions=(
                        f"¿Esta pregunta trata sobre {TEMAS_EN_ALCANCE}? "
                        "Responde que sí también para preguntas generales o "
                        "introductorias sobre esos dos temas, no solo para "
                        "preguntas muy específicas."
                    ),
                ),
            },
        )
        probabilidad_en_alcance = respuesta.nouls["en_alcance"].noul
        return probabilidad_en_alcance < UMBRAL_EN_ALCANCE
    except Exception as e:
        print(f"  [WARN] TypeSafe (Jev) falló, se deja pasar la pregunta sin filtrar: {e}")
        return False


def descomponer_pregunta(pregunta: str) -> list:
    if not es_pregunta_compuesta(pregunta):
        return [pregunta]

    prompt_descomposicion = f"""Divide la siguiente pregunta en sub-preguntas
independientes y autocontenidas, una por cada tema o dato distinto que se
pide. Si la pregunta ya trata un solo tema, devuélvela tal cual, sin dividir.
Responde SOLO con las sub-preguntas, una por línea, sin numerarlas ni
agregar texto adicional.

Pregunta: {pregunta}

Sub-preguntas:"""

    try:
        resp = ai_client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt_descomposicion,
            config=CONFIG_DESCOMPOSICION,
        )
        sub_preguntas = [
            linea.strip("-•* \t0123456789.) ")
            for linea in resp.text.strip().split("\n")
            if linea.strip("-•* \t0123456789.) ")
        ]
        return sub_preguntas if sub_preguntas else [pregunta]
    except Exception:
        return [pregunta]


class ConsultaRequest(BaseModel):
    pregunta: str
    razonamiento: bool = False


def obtener_embedding(texto: str):
    """CAMBIO: antes llamaba a Gemini (embed_content). Ahora llama a Voyage
    vía MongoDB Atlas, con input_type='query' (distinto de 'document', que es
    lo que usa upload_to_supabase_voyage.py al indexar) — Voyage optimiza el
    vector de forma distinta según el rol."""
    headers = {
        "Authorization": f"Bearer {VOYAGE_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "input": texto,
        "model": VOYAGE_MODEL,
        "input_type": "query",
        "output_dimension": EMBEDDING_DIM,
    }
    r = requests.post(VOYAGE_URL, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["data"][0]["embedding"]


def traer_seccion_completa_vigente(fuente_archivo: str, section_id: str):
    try:
        res = (
            supabase.table("documentos_tributarios")
            .select("id, contenido, metadata")
            .eq("metadata->>fuente_archivo", fuente_archivo)
            .eq("metadata->>section_id", section_id)
            .or_("metadata->>estado.eq.vigente,metadata->>estado.is.null")
            .execute()
        )
        return res.data
    except Exception:
        return []


def traer_vecinos_batch(fuente_archivo: str, chunk_ids: list, estado_doc: str):
    """CAMBIO: reemplaza el loop de una consulta HTTP por cada chunk_id
    vecino (chunk_id - 1, chunk_id + 1). Antes, por cada chunk relevante se
    hacían hasta 2 llamadas separadas a Supabase; con preguntas compuestas
    (varias sub-preguntas, MATCH_COUNT_COMPUESTA=14) esto se convertía en
    decenas de round-trips secuenciales dentro de una sola petición —
    un patrón N+1 clásico y la causa más probable del
    'canceling statement due to statement timeout' visto en producción.

    Ahora se agrupan TODOS los chunk_id vecinos que hacen falta para una
    misma fuente_archivo y se traen en una sola consulta con .in_()."""
    if not chunk_ids:
        return []
    try:
        res = (
            supabase.table("documentos_tributarios")
            .select("id, contenido, metadata")
            .eq("metadata->>fuente_archivo", fuente_archivo)
            .in_("metadata->>chunk_id", [str(c) for c in chunk_ids])
            .or_(f"metadata->>estado.eq.{estado_doc},metadata->>estado.is.null")
            .execute()
        )
        return res.data
    except Exception:
        return []


def _construir_contexto(consulta: ConsultaRequest):
    sub_preguntas = descomponer_pregunta(consulta.pregunta)

    response_data = []
    ids_vistos = set()

    for sub_pregunta in sub_preguntas:
        query_vector = obtener_embedding(sub_pregunta)

        resp_sub = supabase.rpc(
            "match_documentos",
            {
                "query_embedding": query_vector,
                "match_threshold": MATCH_THRESHOLD,
                "match_count": MATCH_COUNT,
            },
        ).execute()

        for d in (resp_sub.data or []):
            if d["id"] not in ids_vistos:
                ids_vistos.add(d["id"])
                response_data.append(d)

    if not response_data:
        return None

    chunks_por_id = {d["id"]: d for d in response_data}

    # CAMBIO: en vez de disparar una consulta por cada chunk_id vecino
    # dentro de este mismo loop, ahora solo AGRUPAMOS qué hace falta pedir
    # (por fuente_archivo), y recién después del loop se hacen las consultas
    # batch — como máximo una por fuente_archivo distinto, sin importar
    # cuántos vecinos tenga cada una.
    vecinos_a_pedir = {}   # fuente_archivo -> {"ids": set(), "estado": str}
    secciones_a_pedir = []  # lista de (fuente_archivo, section_id)

    for doc in response_data:
        metadata = doc.get("metadata") or {}
        chunk_id = metadata.get("chunk_id")
        fuente_archivo = metadata.get("fuente_archivo")
        section_id = metadata.get("section_id")
        estado_doc = metadata.get("estado", "vigente")
        if fuente_archivo is None:
            continue

        if section_id:
            secciones_a_pedir.append((fuente_archivo, section_id))
        elif chunk_id is not None:
            entrada = vecinos_a_pedir.setdefault(
                fuente_archivo, {"ids": set(), "estado": estado_doc}
            )
            entrada["ids"].update([chunk_id - 1, chunk_id + 1])

    # Secciones completas vigentes (sin cambios: ya era una consulta por
    # sección, no por chunk, así que no había N+1 aquí).
    for fuente_archivo, section_id in secciones_a_pedir:
        for v in traer_seccion_completa_vigente(fuente_archivo, section_id):
            if v["id"] not in chunks_por_id:
                chunks_por_id[v["id"]] = v

    # Vecinos: ahora en lote, una sola consulta por fuente_archivo.
    for fuente_archivo, info in vecinos_a_pedir.items():
        for v in traer_vecinos_batch(fuente_archivo, list(info["ids"]), info["estado"]):
            if v["id"] not in chunks_por_id:
                chunks_por_id[v["id"]] = v

    chunks_ordenados = sorted(
        chunks_por_id.values(),
        key=lambda d: (d.get("metadata") or {}).get("chunk_id", 0),
    )

    contexto = "\n\n".join([doc["contenido"] for doc in chunks_ordenados])
    confianza = max((doc.get("similarity", 0) for doc in response_data), default=0)

    fuentes_vistas = set()
    fuentes = []
    for doc in chunks_ordenados:
        m = doc.get("metadata") or {}
        clave = (m.get("fuente"), m.get("categoria"))
        if clave not in fuentes_vistas and m.get("fuente"):
            fuentes_vistas.add(clave)
            fuentes.append({"fuente": m.get("fuente"), "categoria": m.get("categoria")})

    prompt_final = f"""
Eres un asistente que ayuda a contadores peruanos a entender normativa de SUNAT de forma clara, cercana y directa — como una explicación bien hecha, no como un documento legal frío.
Responde a la pregunta del usuario utilizando únicamente la información proporcionada en el contexto.

Toma en cuenta que el texto extraído del PDF puede presentar pequeñas variaciones tipográficas o espaciados irregulares (por ejemplo, "Catálogo No. 14" o "Catálogo N° 14", "e ste", "s e").
Relaciona los códigos de catálogo (como 1001, 1002, 1003) con sus descripciones de montos (operaciones gravadas, exoneradas, inafectas).

REGLA CRÍTICA SOBRE VIGENCIA:
Si el contexto incluye bloques marcados con la frase "TEXTO ANTERIOR", ese contenido es
normativa DEROGADA (ya no aplica). NUNCA la presentes como vigente ni la mezcles con la
norma actual como si fuera una sola regla. Usa el texto derogado únicamente si el usuario
pide explícitamente conocer el historial de cambios o una versión anterior de la norma.
Si tienes dudas sobre si un fragmento es vigente o derogado, dilo explícitamente en tu
respuesta en vez de asumir.

REGLA CRÍTICA SOBRE PREGUNTAS COMPUESTAS:
Si la pregunta del usuario tiene varias partes, responde cada parte por separado y de
forma completa. Si el contexto no contiene información suficiente para responder alguna
de las partes, dilo explícitamente para esa parte en vez de omitirla en silencio.

Reglas de estilo para tu respuesta:
- Estructura la respuesta en secciones claras usando encabezados con ## (por ejemplo: "## ¿Cuándo aplica?", "## Requisitos obligatorios", "## ¿Dónde se tramita?").
- Usa **negrita** para resaltar términos clave, montos, plazos, nombres de normas y conceptos importantes.
- Cuando el contexto tenga una lista de ítems, preséntalos como lista numerada o con viñetas.
- Mantén el tono cercano y natural, sin sonar como un documento legal frío.
- No entrecomilles términos ni definiciones salvo que estés citando el nombre exacto de una norma.
- Si citas el nombre de una norma o resolución, menciónalo de forma natural dentro de la oración.
- Sé completo: no omitas ítems obligatorios del contexto por acortar la respuesta.

Al final de tu respuesta, en una línea nueva, escribe exactamente "{MARCADOR_SUGERENCIAS}" y debajo 3 preguntas cortas relacionadas, una por línea, sin numerarlas ni agregar texto extra.

--- CONTEXTO EXTRAÍDO ---
{contexto}
--- FIN CONTEXTO ---

Pregunta del usuario: {consulta.pregunta}
Respuesta:
"""

    return {
        "prompt_final": prompt_final,
        "confianza": confianza,
        "fuentes": fuentes,
        "chunks_ordenados": chunks_ordenados,
    }


def _sse(tipo: str, data) -> str:
    payload = json.dumps({"tipo": tipo, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


def _respuesta_degradada(chunks_ordenados) -> str:
    resumen_crudo = "\n\n".join(doc["contenido"] for doc in chunks_ordenados[:3])
    return (
        "El asistente de redacción está saturado en este momento, pero esto es "
        "justo lo que encontré en la normativa cargada sobre tu pregunta:\n\n"
        f"{resumen_crudo}\n\n"
        "Intenta de nuevo en un par de minutos para una respuesta mejor redactada."
    )


def _carrera_modelos(prompt_final: str, t0: float):
    q = queue.Queue()
    lock = threading.Lock()
    compartido = {"ganador": None}
    cancelar = threading.Event()
    orden = _modelos_en_orden()
    carrera = {"lanzados": 0, "ultimo_lanzamiento": 0.0}
    activos = set()
    ultimo_error = None

    def sigue_en_carrera(modelo):
        if cancelar.is_set():
            return False
        with lock:
            g = compartido["ganador"]
        return g is None or g == modelo

    def es_ganador(modelo):
        with lock:
            return compartido["ganador"] == modelo

    def cerrar(stream):
        try:
            fn = getattr(stream, "close", None)
            if fn:
                fn()
        except Exception:
            pass

    def worker(modelo):
        for intento in range(1, MAX_INTENTOS_POR_MODELO + 1):
            if not sigue_en_carrera(modelo):
                return
            stream = None
            try:
                stream = ai_client.models.generate_content_stream(
                    model=modelo,
                    contents=prompt_final,
                    config=CONFIG_LLM,
                )
                empezo = False
                for chunk in stream:
                    if not sigue_en_carrera(modelo):
                        cerrar(stream)
                        return
                    texto = getattr(chunk, "text", None) or ""
                    if not texto:
                        continue
                    with lock:
                        if compartido["ganador"] is None and not cancelar.is_set():
                            compartido["ganador"] = modelo
                        gana = compartido["ganador"] == modelo
                    if not gana:
                        cerrar(stream)
                        return
                    empezo = True
                    q.put(("chunk", modelo, texto))
                if empezo:
                    q.put(("fin", modelo, None))
                elif sigue_en_carrera(modelo):
                    print(f"  [WARN] {modelo} devolvió una respuesta vacía.")
                    q.put(("fallo", modelo, ValueError("respuesta vacía")))
                return

            except genai_errors.ClientError as e:
                if "401" in str(e) or "UNAUTHENTICATED" in str(e):
                    q.put(("auth", modelo, e))
                    return
                if es_ganador(modelo):
                    q.put(("error_mid", modelo, e))
                    return
                es_cuota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                es_no_disp = "404" in str(e) or "NOT_FOUND" in str(e) or "no longer available" in str(e)
                if es_cuota or es_no_disp:
                    motivo = "sin cuota (429)" if es_cuota else "ya no disponible (404)"
                    print(f"  [WARN] {modelo} {motivo}.")
                    _marcar_saturado(modelo)
                q.put(("fallo", modelo, e))
                return

            except (genai_errors.ServerError, httpx.HTTPError) as e:
                if es_ganador(modelo):
                    q.put(("error_mid", modelo, e))
                    return
                if intento < MAX_INTENTOS_POR_MODELO and sigue_en_carrera(modelo):
                    espera = ESPERA_REINTENTO_S + random.uniform(0, 0.5)
                    print(f"  [WARN] {modelo} falló ({type(e).__name__}). "
                          f"Reintento {intento}/{MAX_INTENTOS_POR_MODELO - 1} en {espera:.1f}s...")
                    time.sleep(espera)
                    continue
                print(f"  [WARN] {modelo} agotó reintentos.")
                _marcar_saturado(modelo)
                q.put(("fallo", modelo, e))
                return

            except Exception as e:
                if es_ganador(modelo):
                    q.put(("error_mid", modelo, e))
                else:
                    q.put(("fallo", modelo, e))
                return

    def lanzar():
        modelo = orden[carrera["lanzados"]]
        carrera["lanzados"] += 1
        carrera["ultimo_lanzamiento"] = time.monotonic()
        activos.add(modelo)
        threading.Thread(target=worker, args=(modelo,), daemon=True, name=f"llm-{modelo}").start()
        return modelo

    try:
        lanzar()
        if HEDGE_DELAY_S <= 0:
            while carrera["lanzados"] < len(orden):
                lanzar()
            yield ("estado", "Consultando varios modelos en paralelo...")

        ganador = None
        while True:
            if time.monotonic() - t0 > DEADLINE_TOTAL_S:
                print(f"  [WARN] Se agotó el tiempo total ({DEADLINE_TOTAL_S}s).")
                yield ("fallaron", ultimo_error)
                return

            try:
                ev = q.get(timeout=0.25)
            except queue.Empty:
                ev = None

            if ev is None:
                if (ganador is None
                        and carrera["lanzados"] < len(orden)
                        and time.monotonic() - carrera["ultimo_lanzamiento"] >= HEDGE_DELAY_S):
                    m = lanzar()
                    print(f"  [INFO] Hedging: se lanza {m} en paralelo.")
                    yield ("estado", "El modelo está lento, probando también una alternativa en paralelo...")
                continue

            tipo, modelo = ev[0], ev[1]

            if tipo == "chunk":
                if ganador is None:
                    ganador = modelo
                if modelo == ganador:
                    yield ("chunk", modelo, ev[2])
            elif tipo == "fin":
                if modelo == ganador:
                    yield ("fin", modelo)
                    return
            elif tipo == "error_mid":
                if modelo == ganador:
                    yield ("error_mid", modelo, ev[2])
                    return
            elif tipo == "auth":
                yield ("auth", modelo, ev[2])
                return
            elif tipo == "fallo":
                activos.discard(modelo)
                ultimo_error = ev[2]
                if ganador is None:
                    if carrera["lanzados"] < len(orden):
                        m = lanzar()
                        yield ("estado", "El modelo está saturado, probando una alternativa...")
                    elif not activos:
                        yield ("fallaron", ultimo_error)
                        return
    finally:
        cancelar.set()


def _generar_stream_respuesta(consulta: ConsultaRequest):
    t0 = time.monotonic()
    clave_cache = _clave_cache(consulta)

    en_cache = _cache_get(clave_cache)
    if en_cache is not None:
        print("  [INFO] Respuesta servida desde caché.")
        yield _sse("texto", en_cache["texto"])
        yield _sse("fin", {**en_cache["fin"], "desde_cache": True})
        return

    yield _sse("estado", "Analizando tu pregunta...")

    if es_pregunta_fuera_de_alcance(consulta.pregunta):
        yield _sse("texto", MENSAJE_FUERA_DE_ALCANCE)
        yield _sse("fin", {"confianza": 0, "fuentes": [], "sugerencias": [], "fuera_de_alcance": True})
        return

    yield _sse("estado", "Buscando en la normativa cargada...")
    try:
        contexto_data = _construir_contexto(consulta)
    except Exception as e:
        traceback.print_exc()
        yield _sse("error", {"mensaje": str(e)})
        return

    t_retrieval = time.monotonic() - t0

    if contexto_data is None:
        yield _sse("texto", "No tengo información cargada sobre esa norma o tema todavía. "
                             "Estoy ampliando la base de conocimiento continuamente.")
        yield _sse("fin", {"confianza": 0, "fuentes": [], "sugerencias": []})
        return

    prompt_final = contexto_data["prompt_final"]
    confianza = contexto_data["confianza"]
    fuentes = contexto_data["fuentes"]
    chunks_ordenados = contexto_data["chunks_ordenados"]

    yield _sse("estado", "Redactando la respuesta...")

    partes_texto = []
    buffer = ""
    sugerencias_buffer = ""
    in_sugerencias = False
    margen = len(MARCADOR_SUGERENCIAS) - 1
    empezo = False
    ultimo_error = None

    carrera = _carrera_modelos(prompt_final, t0)
    try:
        for ev in carrera:
            tipo = ev[0]

            if tipo == "estado":
                yield _sse("estado", ev[1])

            elif tipo == "chunk":
                _, modelo, texto = ev
                if not empezo:
                    empezo = True
                    print(f"  [TIMING] retrieval={t_retrieval:.1f}s "
                          f"primer_token={time.monotonic() - t0:.1f}s ganador={modelo}")

                if in_sugerencias:
                    sugerencias_buffer += texto
                    continue

                buffer += texto
                if MARCADOR_SUGERENCIAS in buffer:
                    idx = buffer.index(MARCADOR_SUGERENCIAS)
                    pre = buffer[:idx]
                    if pre:
                        partes_texto.append(pre)
                        yield _sse("texto", pre)
                    in_sugerencias = True
                    sugerencias_buffer = buffer[idx + len(MARCADOR_SUGERENCIAS):]
                    buffer = ""
                else:
                    safe_len = len(buffer) - margen
                    if safe_len > 0:
                        emitir = buffer[:safe_len]
                        partes_texto.append(emitir)
                        yield _sse("texto", emitir)
                        buffer = buffer[safe_len:]

            elif tipo == "fin":
                modelo = ev[1]
                if buffer and not in_sugerencias:
                    partes_texto.append(buffer)
                    yield _sse("texto", buffer)

                sugerencias = [
                    linea.strip("-•* \t")
                    for linea in sugerencias_buffer.strip().split("\n")
                    if linea.strip("-•* \t")
                ][:3]

                if modelo != MODELOS_CHAIN[0]:
                    print(f"  [INFO] Se usó el modelo de respaldo: {modelo}")
                print(f"  [TIMING] total={time.monotonic() - t0:.1f}s ganador={modelo}")

                fin = {
                    "confianza": round(confianza, 3),
                    "fuentes": fuentes,
                    "sugerencias": sugerencias,
                }
                texto_completo = "".join(partes_texto)
                if texto_completo:
                    _cache_set(clave_cache, {"texto": texto_completo, "fin": fin})

                yield _sse("fin", fin)
                return

            elif tipo == "error_mid":
                print(f"  [ERROR] {ev[1]} falló a mitad del streaming: {type(ev[2]).__name__}: {ev[2]}")
                yield _sse("error", {"mensaje": "Se interrumpió la generación de la respuesta."})
                return

            elif tipo == "auth":
                print(f"  [ERROR] {ev[1]}: fallo de autenticación (401). "
                      f"Revisa GEMINI_API_KEY en las variables de entorno.")
                yield _sse("error", {"mensaje": "Error de autenticación con Gemini."})
                return

            elif tipo == "fallaron":
                ultimo_error = ev[1]
                break
    finally:
        carrera.close()

    print(f"  [WARN] Todos los modelos fallaron. Devolviendo contexto crudo. Último error: {ultimo_error}")
    yield _sse("texto", _respuesta_degradada(chunks_ordenados))
    yield _sse("fin", {
        "confianza": round(confianza, 3),
        "degradado": True,
        "fuentes": fuentes,
        "sugerencias": [],
    })


@app.post("/api/chat/stream")
def responder_consulta_stream(consulta: ConsultaRequest):
    return StreamingResponse(
        _generar_stream_respuesta(consulta),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat")
def responder_consulta(consulta: ConsultaRequest):
    try:
        if es_pregunta_fuera_de_alcance(consulta.pregunta):
            return {"respuesta": MENSAJE_FUERA_DE_ALCANCE, "fuera_de_alcance": True}

        contexto_data = _construir_contexto(consulta)

        if contexto_data is None:
            return {
                "respuesta": "No tengo información cargada sobre esa norma o tema todavía. "
                             "Estoy ampliando la base de conocimiento continuamente."
            }

        prompt_final = contexto_data["prompt_final"]
        confianza = contexto_data["confianza"]
        fuentes = contexto_data["fuentes"]
        chunks_ordenados = contexto_data["chunks_ordenados"]

        t0 = time.monotonic()
        respuesta = None
        ultimo_error = None
        for modelo in _modelos_en_orden():
            if time.monotonic() - t0 > DEADLINE_TOTAL_S:
                print(f"  [WARN] Se agotó el tiempo total ({DEADLINE_TOTAL_S}s).")
                break
            exito = False
            for intento in range(1, MAX_INTENTOS_POR_MODELO + 1):
                try:
                    respuesta = ai_client.models.generate_content(
                        model=modelo,
                        contents=prompt_final,
                        config=CONFIG_LLM,
                    )
                    exito = True
                    break
                except (genai_errors.ServerError, httpx.HTTPError) as e:
                    ultimo_error = e
                    if intento < MAX_INTENTOS_POR_MODELO:
                        espera = ESPERA_REINTENTO_S + random.uniform(0, 0.5)
                        print(f"  [WARN] {modelo} falló ({type(e).__name__}). "
                              f"Reintento {intento}/{MAX_INTENTOS_POR_MODELO - 1} en {espera:.1f}s...")
                        time.sleep(espera)
                        continue
                    _marcar_saturado(modelo)
                    break
                except genai_errors.ClientError as e:
                    ultimo_error = e
                    es_cuota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
                    es_no_disponible = (
                        "404" in str(e)
                        or "NOT_FOUND" in str(e)
                        or "no longer available" in str(e)
                    )
                    es_auth = "401" in str(e) or "UNAUTHENTICATED" in str(e)
                    if es_auth:
                        print(f"  [ERROR] {modelo}: fallo de autenticación (401). "
                              f"Revisa GEMINI_API_KEY en las variables de entorno.")
                        raise
                    if es_cuota or es_no_disponible:
                        motivo = "sin cuota (429)" if es_cuota else "ya no disponible (404)"
                        print(f"  [WARN] {modelo} {motivo}. Probando el siguiente modelo...")
                        _marcar_saturado(modelo)
                        break
                    raise
            if exito:
                if modelo != MODELOS_CHAIN[0]:
                    print(f"  [INFO] Se usó el modelo de respaldo: {modelo}")
                break

        if respuesta is None:
            print(f"  [WARN] Todos los modelos fallaron. Devolviendo contexto crudo. "
                  f"Último error: {ultimo_error}")
            return {
                "respuesta": _respuesta_degradada(chunks_ordenados),
                "confianza": round(confianza, 3),
                "degradado": True,
                "fuentes": fuentes,
                "sugerencias": [],
            }

        texto_completo = respuesta.text
        sugerencias = []
        if MARCADOR_SUGERENCIAS in texto_completo:
            partes = texto_completo.split(MARCADOR_SUGERENCIAS)
            texto_completo = partes[0].strip()
            sugerencias = [
                linea.strip("-•* \t")
                for linea in partes[1].strip().split("\n")
                if linea.strip("-•* \t")
            ][:3]

        return {
            "respuesta": texto_completo,
            "confianza": round(confianza, 3),
            "fuentes": fuentes,
            "sugerencias": sugerencias,
        }

    except genai_errors.ClientError as e:
        if "401" in str(e) or "UNAUTHENTICATED" in str(e):
            print("\n=== FALLO DE AUTENTICACIÓN CON GEMINI (401) ===")
            traceback.print_exc()
            print("====================================\n")
            raise HTTPException(
                status_code=500,
                detail="Error de autenticación con Gemini. Verifica GEMINI_API_KEY en Northflank.",
            )
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))

    except genai_errors.ServerError as e:
        print("\n=== GEMINI SOBRECARGADO (503) TRAS REINTENTOS ===")
        traceback.print_exc()
        print("====================================\n")
        return {
            "respuesta": "En este momento el servicio de IA está saturado. "
                         "Por favor intenta de nuevo en unos segundos.",
            "confianza": 0,
        }

    except Exception as e:
        print("\n=== ERROR DETECTADO EN /api/chat ===")
        traceback.print_exc()
        print("====================================\n")
        raise HTTPException(status_code=500, detail=str(e))
