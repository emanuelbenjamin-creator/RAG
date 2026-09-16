import os
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

# 1. Definir la ruta del documento PDF
pdf_path = os.path.join("documentos", "documento_prueba.pdf")

if not os.path.exists(pdf_path):
    print(f"[ERROR] No se encontró el archivo: {pdf_path}")
else:
    # 2. Extracción de texto
    print("Step 1: Leyendo el documento PDF...")
    reader = PdfReader(pdf_path)
    texto_completo = ""
    for page in reader.pages:
        texto_completo += (page.extract_text() or "") + "\n"

    print(f" -> Total de caracteres leídos: {len(texto_completo)}")

    # 3. Fragmentación (Chunking)
    print("\nStep 2: Fragmentando el texto en chunks...")
    chunk_size = 1200
    overlap = 200
    chunks = []
    inicio = 0

    while inicio < len(texto_completo):
        fin = inicio + chunk_size
        chunk_texto = texto_completo[inicio:fin].strip()
        if chunk_texto:  # Evitamos guardar bloques vacíos
            chunks.append(chunk_texto)
        inicio += (chunk_size - overlap)

    print(f" -> Total de chunks generados: {len(chunks)}")

    # 4. Carga del Modelo de Embeddings
    print("\nStep 3: Cargando modelo Qwen3-Embedding-0.6B...")
    model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

    # 5. Generación de Embeddings para los primeros 5 chunks (Prueba de rendimiento)
    print("\nStep 4: Generando vectores para los primeros 5 chunks de prueba...")
    chunks_prueba = chunks[:5]
    embeddings = model.encode(chunks_prueba)

    print("\n--- ¡PROCESO COMPLETADO CON ÉXITO! ---")
    for idx, (chunk, emb) in enumerate(zip(chunks_prueba, embeddings), start=1):
        print(f"\n[Chunk {idx}]")
        print(f"Texto (primeros 80 caracteres): {chunk[:80]}...")
        print(f"Dimensión del Vector: {len(emb)}")
        print(f"Primeros 3 números: {emb[:3]}")