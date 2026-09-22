import os
from dotenv import load_dotenv
load_dotenv()
from supabase import create_client

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

archivos = ["documento_prueba.pdf", "imp (1).pdf", "imp (2).pdf", "imp (3).pdf"]
for archivo in archivos:
    supabase.table("documentos_tributarios").delete().eq(
        "metadata->>fuente_archivo", archivo
    ).execute()
    print(f"Chunks borrados para: {archivo}")
