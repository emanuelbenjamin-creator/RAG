import os
from pypdf import PdfReader

# 1. Definimos la ruta exacta de nuestro documento
ruta_pdf = os.path.join("documentos", "documento_prueba.pdf")

# 2. Validación de seguridad: Comprobamos que el archivo realmente existe
if not os.path.exists(ruta_pdf):
    print(f"[ERROR] No se encontró el archivo en: {ruta_pdf}")
    print("Por favor, asegúrate de colocar un PDF en la carpeta 'documentos' con el nombre 'documento_prueba.pdf'")
else:
    print(f"Cargando y leyendo el archivo: {ruta_pdf}...\n")
    lector = PdfReader(ruta_pdf)
    
    total_paginas = len(lector.pages)
    print(f"Total de páginas detectadas: {total_paginas}")
    
    # 3. Extracción de texto
    texto_completo = ""
    for i, pagina in enumerate(lector.pages):
        # Usamos 'or ""' para evitar errores si una página es solo una imagen o está en blanco
        contenido_pagina = pagina.extract_text() or ""
        print(f" - Página {i + 1}: {len(contenido_pagina)} caracteres extraídos.")
        texto_completo += contenido_pagina + "\n"

    # 4. Lógica de Chunking (Fragmentación)
    tamaño_chunk = 500  # Cuántos caracteres tendrá cada bloque
    solapamiento = 50   # Cuántos caracteres retrocedemos para no cortar ideas
    
    chunks = []
    inicio = 0
    
    while inicio < len(texto_completo):
        fin = inicio + tamaño_chunk
        chunk_texto = texto_completo[inicio:fin]
        chunks.append(chunk_texto)
        # Avanzamos, pero retrocedemos un poco según el solapamiento
        inicio += (tamaño_chunk - solapamiento)

    # 5. Reporte final
    print("\n--- RESULTADO DEL PROCESAMIENTO ---")
    print(f"Caracteres totales en el PDF: {len(texto_completo)}")
    print(f"Total de chunks (bloques) creados: {len(chunks)}")
    
    if chunks:
        print("\nMUESTRA DEL PRIMER CHUNK (Bloque 1):")
        print("=" * 60)
        print(chunks[0].strip())
        print("=" * 60)