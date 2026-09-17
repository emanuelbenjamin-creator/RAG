import React, { useState } from 'react';

export default function ChatTributario() {
  const [pregunta, setPregunta] = useState('');
  const [chatLog, setChatLog] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modoRazonamiento, setModoRazonamiento] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!pregunta.trim()) return;

    const userMessage = pregunta;
    setPregunta('');
    setChatLog((prev) => [...prev, { remitente: 'usuario', texto: userMessage }]);
    setLoading(true);

    try {
      const response = await fetch('https://p01--asistente-ia-tributario--qw7xms7w9jfx.code.run/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          pregunta: userMessage,
          razonamiento: modoRazonamiento 
        }),
      });

      const data = await response.json();
      
      if (response.ok) {
        setChatLog((prev) => [...prev, { 
          remitente: 'ia', 
          texto: data.respuesta, 
          contexto: data.contexto_usado 
        }]);
      } else {
        setChatLog((prev) => [...prev, { remitente: 'ia', texto: 'Error al procesar la consulta.' }]);
      }
    } catch (error) {
      setChatLog((prev) => [...prev, { remitente: 'ia', texto: 'No se pudo conectar con el servidor FastAPI.' }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen bg-slate-900 text-slate-100 font-sans">
      {/* Header */}
      <header className="bg-slate-800 border-b border-slate-700 p-4 flex justify-between items-center">
        <h1 className="text-xl font-bold text-blue-400">Asistente IA Tributario SUNAT</h1>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-300 cursor-pointer flex items-center gap-1">
            <input 
              type="checkbox" 
              checked={modoRazonamiento} 
              onChange={(e) => setModoRazonamiento(e.target.checked)}
              className="rounded bg-slate-700 border-slate-600 text-blue-500 focus:ring-blue-400"
            />
            Razonamiento Profundo
          </label>
        </div>
      </header>

      {/* Cuerpo del Chat */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 max-w-4xl w-full mx-auto">
        {chatLog.length === 0 ? (
          <div className="text-center text-slate-500 mt-20">
            <p className="text-lg">¡Hola! Escribe una consulta sobre normativa tributaria peruana para comenzar.</p>
          </div>
        ) : (
          chatLog.map((msg, index) => (
            <div 
              key={index} 
              className={`flex ${msg.remitente === 'usuario' ? 'justify-end' : 'justify-start'}`}
            >
              <div className={`max-w-xl p-4 rounded-lg shadow-md ${
                msg.remitente === 'usuario' 
                  ? 'bg-blue-600 text-white rounded-br-none' 
                  : 'bg-slate-800 border border-slate-700 text-slate-200 rounded-bl-none'
              }`}>
                <p className="whitespace-pre-wrap">{msg.texto}</p>
                {msg.contexto && (
                  <span className="text-xs text-slate-400 mt-2 block">
                    Fuentes de Supabase usadas: {msg.contexto}
                  </span>
                )}
              </div>
            </div>
          ))
        )}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-slate-800 border border-slate-700 p-4 rounded-lg text-slate-400 animate-pulse">
              Consultando la normativa de la SUNAT...
            </div>
          </div>
        )}
      </div>

      {/* Input de Preguntas */}
      <footer className="bg-slate-800 border-t border-slate-700 p-4">
        <form onSubmit={handleSubmit} className="max-w-4xl mx-auto flex gap-2">
          <input 
            type="text" 
            value={pregunta}
            onChange={(e) => setPregunta(e.target.value)}
            placeholder="Ej. ¿Cuáles son los requisitos de una factura electrónica?"
            className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-4 py-3 text-slate-100 focus:outline-none focus:border-blue-500"
          />
          <button 
            type="submit"
            disabled={loading}
            className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-lg font-medium transition-colors disabled:opacity-50"
          >
            Enviar
          </button>
        </form>
      </footer>
    </div>
  );
}
