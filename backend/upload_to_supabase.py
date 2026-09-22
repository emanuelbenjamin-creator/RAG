import os
import re
import time
from pypdf import PdfReader
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from supabase import create_client, Client

# --- Credenciales: SIEMPRE desde variables de entorno, nunca hardcodeadas ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY]):
    raise SystemExit(
        "[ERROR] Faltan variables de entorno: SUPABASE_URL, SUPABASE_KEY o GEMINI_API_KEY. "
        "Expórtalas antes de correr el script."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# --- Mismo modelo/dimensión que usa api.py para la consulta del usuario ---
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 1024

PAUSA_ENTRE_REQUESTS = 5.0  # segundos
MAX_REINTENTOS = 6
ESPERA_BASE_REINTENTO = 15  # segundos, se duplica en cada reintento

# Un chunk normal de prosa
CHUNK_SIZE = 1200
OVERLAP = 200

# Una sección/tabla detectada no se corta salvo que sea gigante; si supera esto,
# se parte en sub-chunks que igual comparten el mismo section_id (para que la
# expansión en api.py los junte a todos de nuevo).
MAX_CHARS_POR_SECCION_CHUNK = 6000

# Mínimo de ítems numerados/con letra seguidos para considerarlo "una tabla/lista larga"
MIN_ITEMS_PARA_SECCION = 6
# Máxima distancia (en caracteres) entre un ítem y el siguiente para
# considerarlos parte de la misma lista
MAX_SEPARACION_ENTRE_ITEMS = 500

# NUEVO --------------------------------------------------------------------
# Distancia mínima (en caracteres) que debe haber entre un marcador
# "TEXTO ANTERIOR" y el siguiente encabezado de Artículo/Capítulo para que
# ese encabezado se considere un verdadero regreso al texto vigente, y no
# la reproducción del propio encabezado del artículo dentro de su versión
# derogada (patrón muy común: "TEXTO ANTERIOR\nArtículo 4°.- Se presumirá...").
DISTANCIA_MINIMA_RESUME_VIGENTE = 120

MARCADOR_DEROGADO = re.compile(r'TEXTO\s+ANTERIOR', re.IGNORECASE)
PATRON_RESUME_VIGENTE = re.compile(
    r'(?m)^\s*(Artículo\s+\d+|CAPÍTULO\s+[IVXLCDM]+)', re.IGNORECASE
)
# ----------------------------------------------------------------------------

# Nombre de archivo -> categoría/metadata
FUENTES = {
    "documento_prueba.pdf": {
        "fuente": "Guia_XML_SUNAT",
        "categoria": "facturacion_electronica",
    },
    "imp(1).pdf": {
        "fuente": "Imp_1",
        "categoria": "por_definir",
    },
    "imp(2).pdf": {
        "fuente": "Imp_2",
        "categoria": "por_definir",
    },
    "imp(3).pdf": {
        "fuente": "Imp_3",
        "categoria": "por_definir",
    },
    "imp(4).pdf": {
        "fuente": "Imp_4",
        "categoria": "por_definir",
    },
    "imp(5).pdf": {
            "fuente": "Imp_5",
            "categoria": "por_definir",
        },
    "imp(6).pdf": {
            "fuente": "Imp_6",
            "categoria": "por_definir",
        },
    "imp(7).pdf": {
            "fuente": "Imp_7",
            "categoria": "por_definir",
        },

    


    }


def obtener_embedding(texto: str):
    """Genera el embedding con reintentos y espera progresiva ante 429."""
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            res = ai_client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=texto,
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
            )
            if hasattr(res, "embeddings") and res.embeddings:
                return list(res.embeddings[0].values)
            elif hasattr(res, "embedding") and res.embedding:
                return list(res.embedding.values)
            raise ValueError("Respuesta sin embedding.")
        except genai_errors.ClientError as e:
            es_429 = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
            if es_429 and intento < MAX_REINTENTOS:
                espera = ESPERA_BASE_REINTENTO * (2 ** (intento - 1))
                print(f"  [WARN] Límite de cuota (429). Reintento {intento}/{MAX_REINTENTOS} "
                      f"en {espera}s...")
                time.sleep(espera)
                continue
            raise
    raise ValueError("No se pudo generar el embedding tras varios reintentos.")


def contar_chunks_existentes(nombre_archivo: str) -> int:
    try:
        res = (
            supabase.table("documentos_tributarios")
            .select("id", count="exact")
            .eq("metadata->>fuente_archivo", nombre_archivo)
            .execute()
        )
        return res.count or 0
    except Exception:
        return 0


def detectar_secciones_regex(texto_completo: str):
    """
    Detecta tramos con listas/tablas largas SIN usar IA (gratis e instantáneo):
    busca ítems que se repiten muchas veces seguidas, típico de las tablas de
    requisitos/campos en normativa SUNAT.

    MODIFICADO: antes solo detectaba ítems numerados ("1. ", "2. "...). La
    normativa peruana usa MUCHO más las listas con letras ("a) ", "b) ",
    incisos romanos en minúscula "i) ", "ii) "...) -- por ejemplo el Art. 14°
    (a-k), el Art. 9° (a-j) o el Art. 12° inciso 2.1 (a-n) del Reglamento de
    Comprobantes de Pago. Esas listas NUNCA activaban la expansión de sección
    completa en api.py, lo que producía respuestas con listas incompletas.
    Devuelve [(inicio_char, fin_char, section_id), ...]
    """
    patron_item = re.compile(r'(?m)^\s{0,4}(?:\d{1,2}|[a-z]{1,3})[.\)]\s+\S')
    matches = list(patron_item.finditer(texto_completo))

    rangos = []
    grupo_actual = []

    def cerrar_grupo(grupo, contador):
        if len(grupo) < MIN_ITEMS_PARA_SECCION:
            return None
        inicio = grupo[0].start()
        fin_ultimo_item = grupo[-1].end()
        # el final de la sección: hasta el próximo salto de párrafo doble,
        # o 300 caracteres después del último ítem si no hay salto claro
        fin = texto_completo.find("\n\n", fin_ultimo_item)
        fin = fin if fin != -1 else min(fin_ultimo_item + 300, len(texto_completo))
        return (inicio, fin, f"seccion_{contador}")

    for m in matches:
        corte_por_distancia = (
            grupo_actual
            and (m.start() - grupo_actual[-1].start()) > MAX_SEPARACION_ENTRE_ITEMS
        )
        # NUEVO: si entre el último ítem del grupo y este nuevo ítem aparece
        # un marcador "TEXTO ANTERIOR", cortamos el grupo aquí sí o sí, sin
        # importar la distancia en caracteres. Esto evita que una sección
        # "salte por encima" de un bloque derogado y termine agrupando
        # ítems vigentes con ítems de una versión histórica de la norma.
        corte_por_texto_derogado = (
            grupo_actual
            and MARCADOR_DEROGADO.search(
                texto_completo[grupo_actual[-1].start():m.start()]
            )
        )
        if corte_por_distancia or corte_por_texto_derogado:
            rango = cerrar_grupo(grupo_actual, len(rangos) + 1)
            if rango:
                rangos.append(rango)
                motivo = "TEXTO ANTERIOR detectado" if corte_por_texto_derogado else "distancia"
                print(f"  -> Sección detectada: chars {rango[0]}-{rango[1]} "
                      f"({rango[1] - rango[0]} caracteres, {len(grupo_actual)} ítems) "
                      f"[corte por: {motivo}]")
            grupo_actual = []
        grupo_actual.append(m)

    rango = cerrar_grupo(grupo_actual, len(rangos) + 1)
    if rango:
        rangos.append(rango)
        print(f"  -> Sección detectada: chars {rango[0]}-{rango[1]} "
              f"({rango[1] - rango[0]} caracteres, {len(grupo_actual)} ítems)")

    if not rangos:
        print("  -> No se detectaron tablas/listas largas en este documento.")

    return rangos


# NUEVO ------------------------------------------------------------------
def calcular_tramos_derogados(texto_completo: str):
    """
    Heurística para marcar qué tramos del documento son texto DEROGADO
    ('TEXTO ANTERIOR'). Cada marcador abre un tramo que se cierra en la
    primera aparición posterior de un encabezado de Artículo/Capítulo que
    esté a más de DISTANCIA_MINIMA_RESUME_VIGENTE caracteres del marcador.

    Por qué la distancia mínima: muchos bloques derogados reproducen su
    propio encabezado justo después de "TEXTO ANTERIOR" (ej. "TEXTO ANTERIOR
    \\nArtículo 4°.- Se presumirá..."). Sin este resguardo, el script
    confundiría ese encabezado reproducido con el regreso al texto vigente
    y cerraría el tramo derogado casi de inmediato, dejando casi todo el
    texto histórico marcado como "vigente" por error.

    Es una heurística basada en patrones observados en el corpus SUNAT/Ley
    del IR. Revisa los prints de este script contra una muestra de PDFs
    nuevos antes de confiar en ella a ciegas para otro tipo de documentos.
    """
    tramos = []
    marcadores = list(MARCADOR_DEROGADO.finditer(texto_completo))

    for m in marcadores:
        inicio_tramo = m.end()
        busqueda_desde = inicio_tramo
        fin_tramo = len(texto_completo)

        while True:
            candidato = PATRON_RESUME_VIGENTE.search(texto_completo, busqueda_desde)
            if not candidato:
                break
            if candidato.start() - inicio_tramo >= DISTANCIA_MINIMA_RESUME_VIGENTE:
                fin_tramo = candidato.start()
                break
            # Demasiado cerca del marcador: es el encabezado del propio
            # artículo reproducido dentro de su versión derogada.
            # Seguimos buscando el verdadero regreso más adelante.
            busqueda_desde = candidato.end()

        tramos.append((inicio_tramo, fin_tramo))

    return tramos


def estado_de_posicion(pos: int, tramos_derogados) -> str:
    """Devuelve 'derogado' si la posición cae dentro de algún tramo derogado."""
    for ini, fin in tramos_derogados:
        if ini <= pos < fin:
            return "derogado"
    return "vigente"
# --------------------------------------------------------------------------


def construir_chunks(texto_completo: str, rangos_seccion):
    """
    Combina: dentro de una sección detectada, chunks grandes que comparten
    section_id (no se cortan salvo que excedan MAX_CHARS_POR_SECCION_CHUNK).
    Fuera de las secciones, chunking normal por tamaño fijo con overlap.

    MODIFICADO: cada chunk ahora incluye "inicio_char" (su posición de
    inicio en texto_completo), necesario para poder calcular después su
    "estado" (vigente/derogado) con estado_de_posicion().
    """
    chunks = []
    pos = 0
    rangos_ordenados = sorted(rangos_seccion, key=lambda r: r[0])

    for inicio_s, fin_s, section_id in rangos_ordenados:
        # 1. Texto normal ANTES de esta sección
        if pos < inicio_s:
            texto_prosa = texto_completo[pos:inicio_s]
            sub = 0
            while sub < len(texto_prosa):
                fin_sub = sub + CHUNK_SIZE
                trozo = texto_prosa[sub:fin_sub].strip()
                if trozo:
                    chunks.append({
                        "texto": trozo,
                        "section_id": None,
                        "inicio_char": pos + sub,  # NUEVO
                    })
                sub += (CHUNK_SIZE - OVERLAP)

        # 2. La sección misma, como chunk(s) grande(s) con el mismo section_id
        texto_seccion = texto_completo[inicio_s:fin_s]
        if len(texto_seccion) <= MAX_CHARS_POR_SECCION_CHUNK:
            chunks.append({
                "texto": texto_seccion.strip(),
                "section_id": section_id,
                "inicio_char": inicio_s,  # NUEVO
            })
        else:
            sub = 0
            while sub < len(texto_seccion):
                trozo = texto_seccion[sub:sub + MAX_CHARS_POR_SECCION_CHUNK].strip()
                if trozo:
                    chunks.append({
                        "texto": trozo,
                        "section_id": section_id,
                        "inicio_char": inicio_s + sub,  # NUEVO
                    })
                sub += MAX_CHARS_POR_SECCION_CHUNK

        pos = fin_s

    # 3. Texto normal DESPUÉS de la última sección
    if pos < len(texto_completo):
        texto_prosa = texto_completo[pos:]
        sub = 0
        while sub < len(texto_prosa):
            fin_sub = sub + CHUNK_SIZE
            trozo = texto_prosa[sub:fin_sub].strip()
            if trozo:
                chunks.append({
                    "texto": trozo,
                    "section_id": None,
                    "inicio_char": pos + sub,  # NUEVO
                })
            sub += (CHUNK_SIZE - OVERLAP)

    return chunks


def procesar_pdf(nombre_archivo: str, meta_extra: dict):
    pdf_path = os.path.join(os.path.dirname(__file__), "documentos", nombre_archivo)
    if not os.path.exists(pdf_path):
        print(f"[ERROR] No se encontró el archivo: {pdf_path}")
        return

    print(f"\n=== Procesando {nombre_archivo} ===")
    print("Step 1: Leyendo el PDF...")
    reader = PdfReader(pdf_path)
    texto_completo = ""
    for page in reader.pages:
        texto_completo += (page.extract_text() or "") + "\n"

    print("Step 2: Detectando tablas/listas largas (regex, sin usar IA)...")
    rangos_seccion = detectar_secciones_regex(texto_completo)

    # NUEVO
    print("Step 2b: Detectando tramos de texto DEROGADO ('TEXTO ANTERIOR')...")
    tramos_derogados = calcular_tramos_derogados(texto_completo)
    total_chars_derogados = sum(fin - ini for ini, fin in tramos_derogados)
    print(f" -> {len(tramos_derogados)} tramo(s) derogado(s) detectado(s) "
          f"({total_chars_derogados} caracteres en total)")

    print("Step 3: Fragmentando texto...")
    chunks = construir_chunks(texto_completo, rangos_seccion)

    # NUEVO: calcular estado (vigente/derogado) de cada chunk
    for c in chunks:
        c["estado"] = estado_de_posicion(c["inicio_char"], tramos_derogados)

    total_chunks = len(chunks)
    con_seccion = sum(1 for c in chunks if c["section_id"])
    con_derogado = sum(1 for c in chunks if c["estado"] == "derogado")
    print(f" -> {total_chunks} chunks totales ({con_seccion} agrupados en secciones, "
          f"{con_derogado} marcados como DEROGADOS)")

    ya_guardados = contar_chunks_existentes(nombre_archivo)
    if ya_guardados > 0:
        print(f" -> Ya hay {ya_guardados} chunks guardados de una corrida anterior. "
              f"Continuando desde ahí...")

    print(f" -> Generando embeddings uno por uno (pausa de {PAUSA_ENTRE_REQUESTS}s entre cada uno)...")

    lote_actual = []
    guardados_en_total = ya_guardados

    for idx, chunk in enumerate(chunks, start=1):
        if idx <= ya_guardados:
            continue

        emb = obtener_embedding(chunk["texto"])

        lote_actual.append({
            "contenido": chunk["texto"],
            "metadata": {
                **meta_extra,
                "chunk_id": idx,
                "fuente_archivo": nombre_archivo,
                "section_id": chunk["section_id"],
                "estado": chunk["estado"],  # NUEVO
            },
            "embedding": emb,
        })

        if idx % 10 == 0 or idx == total_chunks:
            print(f"  -> {idx}/{total_chunks} embeddings generados")

        if len(lote_actual) >= 10 or idx == total_chunks:
            supabase.table("documentos_tributarios").insert(lote_actual).execute()
            guardados_en_total += len(lote_actual)
            print(f"  -> Guardado en Supabase: {guardados_en_total}/{total_chunks}")
            lote_actual = []

        time.sleep(PAUSA_ENTRE_REQUESTS)

    print(f"--- {nombre_archivo}: {total_chunks} chunks persistidos con embeddings {EMBEDDING_MODEL}. ---")


if __name__ == "__main__":
    nombres = list(FUENTES.items())
    for i, (nombre_archivo, meta_extra) in enumerate(nombres):
        procesar_pdf(nombre_archivo, meta_extra)
        if i < len(nombres) - 1:
            print("Pausa de 10s antes del siguiente documento...")
            time.sleep(10)
    print("\n--- ¡TODOS LOS DOCUMENTOS PROCESADOS! ---")
