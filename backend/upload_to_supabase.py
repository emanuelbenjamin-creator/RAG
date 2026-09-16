import os
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# Credenciales de Supabase
SUPABASE_URL = "https://ilvssohttgguxdijhuyo.supabase.co"
SUPABASE_KEY = "sb_publishable_L9nLEcA3-9rknBAHlP0GOQ_hCqOH-24"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 1. Ruta del PDF
pdf_path = os.path.join(os.path.dirname(__file__), "documentos", "documento_prueba.pdf")

if not os.path.exists(pdf_path):
    print(f"[ERROR] No se encontró el archivo: {pdf_path}")
else:
    print("Step 1: Leyendo el documento PDF...")
    reader = PdfReader(pdf_path)
    texto_completo = ""
    for page in reader.pages:
        texto_completo += (page.extract_text() or "") + "\n"

    # 2. Fragmentación
    print("Step 2: Fragmentando texto...")
    chunk_size = 1200
    overlap = 200
    chunks = []
    inicio = 0

    while inicio < len(texto_completo):
        fin = inicio + chunk_size
        chunk_texto = texto_completo[inicio:fin].strip()
        if chunk_texto:
            chunks.append(chunk_texto)
        inicio += (chunk_size - overlap)

    # 3. Cargar modelo
    print("Step 3: Cargando modelo Qwen3-Embedding-0.6B...")
    model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

  # 4. Generar embeddings e insertar por lotes pequeños (mini-batches)
batch_size = 10
total_chunks = len(chunks)
print(f"Step 4: Procesando e insertando {total_chunks} chunks en lotes de {batch_size}...\n")

for i in range(0, total_chunks, batch_size):
    batch_chunks = chunks[i:i + batch_size]
    
    # Vectorizar el lote completo en un solo paso
    embeddings = model.encode(batch_chunks).tolist()
    
    # Preparar lista de datos para inserción masiva
    rows_to_insert = []
    for j, (chunk, emb) in enumerate(zip(batch_chunks, embeddings), start=i + 1):
        rows_to_insert.append({
            "contenido": chunk,
            "metadata": {"fuente": "Guia_XML_SUNAT", "chunk_id": j},
            "embedding": emb
        })
        
    # Insertar lote en Supabase
    supabase.table("documentos_tributarios").insert(rows_to_insert).execute()
    print(f"-> Lote cargado: {min(i + batch_size, total_chunks)}/{total_chunks} chunks insertados.")

print("\n--- ¡VECTORES PERSISTIDOS EN LA NUBE! ---")