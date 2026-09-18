import React, { useState, useRef, useEffect } from 'react';

const API_URL = 'https://p01--asistente-ia-tributario--qw7xms7w9jfx.code.run/api/chat';

const ACCESOS_RAPIDOS = [
  {
    titulo: '¿Cuáles son los requisitos de una factura electrónica?',
    detalle: 'Datos obligatorios y condicionales del comprobante',
  },
  {
    titulo: '¿Qué es la afectación al IGV por ítem?',
    detalle: 'Cómo se declara en el detalle del comprobante',
  },
  {
    titulo: 'Explícame el catálogo de comprobantes de pago',
    detalle: 'Boleta, factura, nota de crédito y sus códigos',
  },
];

/* -------------------- Render de texto con formato liviano -------------------- */
/* Soporta **negrita**, ## encabezados, listas "1. " y "- ", sin dependencias externas */
function renderTextoFormateado(texto) {
  const lineas = texto.split('\n');
  const bloques = [];
  let listaActual = null;

  const cerrarLista = () => {
    if (listaActual) {
      bloques.push(listaActual);
      listaActual = null;
    }
  };

  const conNegritas = (linea) => {
    const partes = linea.split(/(\*\*[^*]+\*\*)/g);
    return partes.map((parte, i) =>
      parte.startsWith('**') && parte.endsWith('**') ? (
        <strong key={i} className="font-semibold text-[#F3E9D2]">
          {parte.slice(2, -2)}
        </strong>
      ) : (
        <React.Fragment key={i}>{parte}</React.Fragment>
      )
    );
  };

  lineas.forEach((linea, idx) => {
    const trimmed = linea.trim();

    if (!trimmed) {
      cerrarLista();
      return;
    }

    const matchHeader = trimmed.match(/^(#{1,3})\s+(.*)/);
    if (matchHeader) {
      cerrarLista();
      const nivel = matchHeader[1].length;
      const Tag = nivel === 1 ? 'h2' : nivel === 2 ? 'h3' : 'h4';
      bloques.push(
        <Tag key={idx} className="font-semibold text-[#EAF1EE] mt-4 mb-2">
          {conNegritas(matchHeader[2])}
        </Tag>
      );
      return;
    }

    const matchNumerado = trimmed.match(/^(\d{1,2})[.)]\s+(.*)/);
    const matchViñeta = trimmed.match(/^[-•]\s+(.*)/);

    if (matchNumerado || matchViñeta) {
      const tipo = matchNumerado ? 'ol' : 'ul';
      const contenido = matchNumerado ? matchNumerado[2] : matchViñeta[1];
      if (!listaActual || listaActual.type !== tipo) {
        cerrarLista();
        listaActual = { type: tipo, items: [] };
      }
      listaActual.items.push(contenido);
      return;
    }

    cerrarLista();
    bloques.push(
      <p key={idx} className="leading-relaxed mb-3 last:mb-0">
        {conNegritas(trimmed)}
      </p>
    );
  });
  cerrarLista();

  return bloques.map((b, i) => {
    if (b && b.type === 'ol') {
      return (
        <ol key={`l-${i}`} className="list-decimal list-inside space-y-1 mb-3 pl-1">
          {b.items.map((it, j) => (
            <li key={j}>{conNegritas(it)}</li>
          ))}
        </ol>
      );
    }
    if (b && b.type === 'ul') {
      return (
        <ul key={`l-${i}`} className="list-disc list-inside space-y-1 mb-3 pl-1">
          {b.items.map((it, j) => (
            <li key={j}>{conNegritas(it)}</li>
          ))}
        </ul>
      );
    }
    return b;
  });
}

/* -------------------- Barra lateral -------------------- */
function Sidebar({ abierta, onCerrar, historial, onSeleccionarHistorial }) {
  return (
    <>
      {abierta && (
        <div
          className="fixed inset-0 bg-black/50 z-20 md:hidden"
          onClick={onCerrar}
        />
      )}
      <aside
        className={`fixed md:static z-30 h-full w-64 bg-[#0E1B17] border-r border-[#1F332C]
        flex flex-col transition-transform duration-200
        ${abierta ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}
      >
        <div className="p-4 flex items-center gap-2 border-b border-[#1F332C]">
          <div className="w-8 h-8 rounded-md bg-[#D4A24C] flex items-center justify-center text-[#0E1B17] font-bold text-sm">
            AT
          </div>
          <span className="font-semibold text-[#EAF1EE]">Asistente Tributario</span>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <button className="w-full text-left px-3 py-2 rounded-lg bg-[#1B2E28] text-[#EAF1EE] font-medium text-sm flex items-center gap-2">
            Asistente
          </button>

          <div className="text-xs uppercase tracking-wide text-[#5E7267] mt-4 mb-1 px-3">
            Historial de esta sesión
          </div>
          {historial.length === 0 ? (
            <p className="px-3 text-sm text-[#5E7267]">
              Tus preguntas van a aparecer aquí.
            </p>
          ) : (
            historial.map((h, i) => (
              <button
                key={i}
                onClick={() => onSeleccionarHistorial(i)}
                className="w-full text-left px-3 py-2 rounded-lg text-sm text-[#8FA39C] hover:bg-[#1B2E28] hover:text-[#EAF1EE] truncate"
              >
                {h}
              </button>
            ))
          )}

          <div className="text-xs uppercase tracking-wide text-[#5E7267] mt-6 mb-1 px-3">
            Próximamente
          </div>
          <div className="px-3 py-2 rounded-lg text-sm text-[#4A5A52] cursor-not-allowed flex items-center justify-between">
            Buscador normativo
            <LockIcon />
          </div>
          <div className="px-3 py-2 rounded-lg text-sm text-[#4A5A52] cursor-not-allowed flex items-center justify-between">
            Casos guardados
            <LockIcon />
          </div>
        </nav>

        <div className="p-3 border-t border-[#1F332C] text-xs text-[#5E7267]">
          Las respuestas se basan en la normativa cargada. Verifica siempre la fuente.
        </div>
      </aside>
    </>
  );
}

function LockIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="4" y="11" width="16" height="9" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

/* -------------------- Referencias -------------------- */
function Referencias({ fuentes }) {
  if (!fuentes || fuentes.length === 0) return null;
  return (
    <div className="mt-4 pt-3 border-t border-[#1F332C] flex flex-wrap gap-2">
      {fuentes.map((f, i) => (
        <span
          key={i}
          className="text-xs bg-[#1B2E28] text-[#8FA39C] px-2.5 py-1 rounded-full border border-[#2A3F37]"
        >
          {f.fuente}
          {f.categoria && f.categoria !== 'por_definir' ? ` · ${f.categoria.replace(/_/g, ' ')}` : ''}
        </span>
      ))}
    </div>
  );
}

/* -------------------- Indicador de "escribiendo" -------------------- */
const MENSAJES_CARGA = [
  'Buscando en la normativa cargada...',
  'Revisando fuentes relevantes...',
  'Redactando la respuesta...',
];

function IndicadorEscribiendo() {
  const [mensajeIdx, setMensajeIdx] = useState(0);

  useEffect(() => {
    const intervalo = setInterval(() => {
      setMensajeIdx((i) => (i + 1) % MENSAJES_CARGA.length);
    }, 2200);
    return () => clearInterval(intervalo);
  }, []);

  return (
    <div className="flex items-center gap-3 text-[#8FA39C] text-sm">
      <div className="flex gap-1">
        <span className="w-2 h-2 rounded-full bg-[#D4A24C] animate-bounce [animation-delay:-0.3s]" />
        <span className="w-2 h-2 rounded-full bg-[#D4A24C] animate-bounce [animation-delay:-0.15s]" />
        <span className="w-2 h-2 rounded-full bg-[#D4A24C] animate-bounce" />
      </div>
      <span>{MENSAJES_CARGA[mensajeIdx]}</span>
    </div>
  );
}

/* -------------------- Componente principal -------------------- */
export default function ChatTributario() {
  const [pregunta, setPregunta] = useState('');
  const [chatLog, setChatLog] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sidebarAbierta, setSidebarAbierta] = useState(false);
  const finRef = useRef(null);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatLog, loading]);

  const enviarPregunta = async (texto) => {
    const userMessage = texto.trim();
    if (!userMessage) return;

    setPregunta('');
    setChatLog((prev) => [...prev, { remitente: 'usuario', texto: userMessage }]);
    setLoading(true);

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pregunta: userMessage }),
      });

      const data = await response.json();

      if (response.ok) {
        setChatLog((prev) => [
          ...prev,
          {
            remitente: 'ia',
            texto: data.respuesta,
            fuentes: data.fuentes,
            degradado: data.degradado,
          },
        ]);
      } else {
        setChatLog((prev) => [
          ...prev,
          { remitente: 'ia', texto: 'No pude procesar tu consulta. Intenta de nuevo en unos segundos.', error: true },
        ]);
      }
    } catch (error) {
      setChatLog((prev) => [
        ...prev,
        { remitente: 'ia', texto: 'No se pudo conectar con el servidor. Revisa tu conexión e intenta de nuevo.', error: true },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    enviarPregunta(pregunta);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      enviarPregunta(pregunta);
    }
  };

  const preguntasUsuario = chatLog
    .filter((m) => m.remitente === 'usuario')
    .map((m) => m.texto);

  return (
    <div className="flex h-screen bg-[#12211D] text-[#EAF1EE] font-sans overflow-hidden">
      <Sidebar
        abierta={sidebarAbierta}
        onCerrar={() => setSidebarAbierta(false)}
        historial={preguntasUsuario}
        onSeleccionarHistorial={() => {}}
      />

      <div className="flex-1 flex flex-col min-w-0">
        {/* Header móvil */}
        <header className="md:hidden flex items-center gap-3 p-4 border-b border-[#1F332C]">
          <button onClick={() => setSidebarAbierta(true)} aria-label="Abrir menú">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 6h18M3 12h18M3 18h18" />
            </svg>
          </button>
          <span className="font-semibold">Asistente Tributario</span>
        </header>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 md:px-6 py-8">
            {chatLog.length === 0 ? (
              <div className="mt-8 md:mt-16">
                <h1 className="text-2xl md:text-3xl font-semibold text-[#EAF1EE] mb-2">
                  Hola, ¿en qué te ayudo hoy?
                </h1>
                <p className="text-[#8FA39C] mb-8">
                  Pregunta lo que necesites sobre normativa tributaria peruana, o elige un acceso rápido.
                </p>
                <div className="grid gap-3 sm:grid-cols-1">
                  {ACCESOS_RAPIDOS.map((a, i) => (
                    <button
                      key={i}
                      onClick={() => enviarPregunta(a.titulo)}
                      className="text-left p-4 rounded-xl bg-[#1B2E28] border border-[#2A3F37] hover:border-[#D4A24C]/60 transition-colors"
                    >
                      <p className="text-[#EAF1EE] font-medium mb-1">{a.titulo}</p>
                      <p className="text-sm text-[#8FA39C]">{a.detalle}</p>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {chatLog.map((msg, index) =>
                  msg.remitente === 'usuario' ? (
                    <div key={index} className="flex justify-end">
                      <div className="max-w-lg bg-[#2F6F5E] text-white px-4 py-2.5 rounded-2xl rounded-br-sm">
                        {msg.texto}
                      </div>
                    </div>
                  ) : (
                    <div key={index} className={msg.error ? 'text-[#D98B7A]' : 'text-[#D7E4DE]'}>
                      {msg.degradado && (
                        <span className="inline-block mb-2 text-xs font-medium text-[#D4A24C] bg-[#2A2418] px-2 py-0.5 rounded-full">
                          Respuesta sin pulir — alta demanda
                        </span>
                      )}
                      <div>{renderTextoFormateado(msg.texto)}</div>
                      <Referencias fuentes={msg.fuentes} />
                    </div>
                  )
                )}
                {loading && <IndicadorEscribiendo />}
              </div>
            )}
            <div ref={finRef} />
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-[#1F332C] bg-[#12211D]">
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto px-4 md:px-6 py-4">
            <div className="flex items-end gap-2 bg-[#1B2E28] border border-[#2A3F37] rounded-2xl px-4 py-2 focus-within:border-[#D4A24C]/60">
              <textarea
                value={pregunta}
                onChange={(e) => setPregunta(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                placeholder="Escribe tu consulta sobre normativa tributaria..."
                className="flex-1 bg-transparent resize-none outline-none text-[#EAF1EE] placeholder-[#5E7267] py-2 max-h-32"
              />
              <button
                type="submit"
                disabled={loading || !pregunta.trim()}
                className="shrink-0 bg-[#D4A24C] hover:bg-[#E0B366] disabled:opacity-40 disabled:hover:bg-[#D4A24C] text-[#12211D] font-medium px-4 py-2 rounded-xl transition-colors"
              >
                Enviar
              </button>
            </div>
            <p className="text-xs text-[#5E7267] mt-2 text-center">
              El asistente puede cometer errores. Verifica la normativa citada antes de aplicarla.
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
