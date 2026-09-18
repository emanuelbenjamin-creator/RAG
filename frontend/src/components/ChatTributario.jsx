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
        <strong key={i} className="font-semibold text-[#0F2A1D]">
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
        <Tag key={idx} className="font-semibold text-[#0F2A1D] mt-5 mb-2 text-lg">
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
      <p key={idx} className="leading-relaxed mb-3 last:mb-0 text-[#374151]">
        {conNegritas(trimmed)}
      </p>
    );
  });
  cerrarLista();

  return bloques.map((b, i) => {
    if (b && b.type === 'ol') {
      return (
        <ol key={`l-${i}`} className="list-decimal list-inside space-y-1.5 mb-3 pl-1 text-[#374151]">
          {b.items.map((it, j) => (
            <li key={j}>{conNegritas(it)}</li>
          ))}
        </ol>
      );
    }
    if (b && b.type === 'ul') {
      return (
        <ul key={`l-${i}`} className="list-disc list-inside space-y-1.5 mb-3 pl-1 text-[#374151]">
          {b.items.map((it, j) => (
            <li key={j}>{conNegritas(it)}</li>
          ))}
        </ul>
      );
    }
    return b;
  });
}

/* -------------------- Pantalla de carga inicial -------------------- */
function PantallaCarga() {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#EEFBF5]">
      <style>{`
        @keyframes mordisco {
          0%, 100% { transform: translateY(0) rotate(0deg); }
          50% { transform: translateY(3px) rotate(-4deg); }
        }
        @keyframes nuezMenguante {
          0%, 60% { transform: scale(1); opacity: 1; }
          80% { transform: scale(0.75); opacity: 0.9; }
          95%, 100% { transform: scale(0.55); opacity: 0.85; }
        }
        @keyframes colaMovimiento {
          0%, 100% { transform: rotate(0deg); }
          50% { transform: rotate(6deg); }
        }
        .ardilla-cabeza { animation: mordisco 0.9s ease-in-out infinite; transform-origin: 50% 70%; }
        .ardilla-nuez { animation: nuezMenguante 2.4s ease-in-out infinite; transform-origin: center; }
        .ardilla-cola { animation: colaMovimiento 1.8s ease-in-out infinite; transform-origin: 20% 90%; }
      `}</style>

      <svg width="120" height="120" viewBox="0 0 120 120" className="mb-4">
        {/* Cola */}
        <path
          className="ardilla-cola"
          d="M20 95 C -5 85, -5 40, 30 30 C 50 24, 55 45, 40 55 C 28 63, 30 78, 45 82"
          fill="none"
          stroke="#C97B3F"
          strokeWidth="14"
          strokeLinecap="round"
        />
        {/* Cuerpo */}
        <ellipse cx="60" cy="82" rx="26" ry="22" fill="#E0925A" />
        <ellipse cx="60" cy="88" rx="16" ry="12" fill="#F5DCC0" />

        {/* Cabeza + brazos sosteniendo la nuez */}
        <g className="ardilla-cabeza">
          <circle cx="62" cy="52" r="24" fill="#E0925A" />
          <ellipse cx="62" cy="58" rx="13" ry="10" fill="#F5DCC0" />
          {/* orejas */}
          <circle cx="46" cy="34" r="7" fill="#E0925A" />
          <circle cx="78" cy="34" r="7" fill="#E0925A" />
          {/* ojo */}
          <circle cx="70" cy="48" r="3" fill="#3A2A1E" />
          {/* mejilla */}
          <circle cx="74" cy="58" r="6" fill="#F0C79E" opacity="0.8" />
          {/* patitas sosteniendo la nuez */}
          <ellipse cx="58" cy="66" rx="6" ry="5" fill="#E0925A" />
          <ellipse cx="70" cy="66" rx="6" ry="5" fill="#E0925A" />
        </g>

        {/* Nuez */}
        <g className="ardilla-nuez" style={{ transformBox: 'fill-box' }}>
          <ellipse cx="64" cy="66" rx="9" ry="10" fill="#8C6239" />
          <path d="M64 57 Q60 66 64 75 Q68 66 64 57" fill="#6B4A2B" opacity="0.6" />
        </g>
      </svg>

      <p className="text-[#0F2A1D] font-medium mb-3">Cargando asistente...</p>
      <div className="flex gap-1.5">
        <span className="w-2 h-2 rounded-full bg-[#2EB37C] animate-bounce [animation-delay:-0.3s]" />
        <span className="w-2 h-2 rounded-full bg-[#2EB37C] animate-bounce [animation-delay:-0.15s]" />
        <span className="w-2 h-2 rounded-full bg-[#2EB37C] animate-bounce" />
      </div>
    </div>
  );
}

/* -------------------- Barra lateral -------------------- */
function Sidebar({ abierta, onCerrar, historial }) {
  return (
    <>
      {abierta && (
        <div className="fixed inset-0 bg-black/20 z-20 md:hidden" onClick={onCerrar} />
      )}
      <aside
        className={`fixed md:static z-30 h-full w-64 bg-white border-r border-[#E5EFE9]
        flex flex-col transition-transform duration-200
        ${abierta ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0`}
      >
        <div className="p-4 flex items-center gap-2 border-b border-[#E5EFE9]">
          <div className="w-9 h-9 rounded-xl bg-[#2EB37C] flex items-center justify-center text-white font-bold text-sm">
            AT
          </div>
          <span className="font-semibold text-[#0F2A1D]">Asistente Tributario</span>
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <button className="w-full text-left px-3 py-2.5 rounded-xl bg-[#EAFBF3] text-[#0F2A1D] font-medium text-sm">
            Asistente
          </button>

          <div className="text-xs uppercase tracking-wide text-[#9CA8A1] mt-4 mb-1 px-3">
            Historial de esta sesión
          </div>
          {historial.length === 0 ? (
            <p className="px-3 text-sm text-[#9CA8A1]">Tus preguntas van a aparecer aquí.</p>
          ) : (
            historial.map((h, i) => (
              <button
                key={i}
                className="w-full text-left px-3 py-2 rounded-xl text-sm text-[#5B6B62] hover:bg-[#F3FAF6] truncate"
              >
                {h}
              </button>
            ))
          )}

          <div className="text-xs uppercase tracking-wide text-[#9CA8A1] mt-6 mb-1 px-3">
            Próximamente
          </div>
          <div className="px-3 py-2 rounded-xl text-sm text-[#C3CCC7] cursor-not-allowed flex items-center justify-between">
            Buscador normativo
            <LockIcon />
          </div>
          <div className="px-3 py-2 rounded-xl text-sm text-[#C3CCC7] cursor-not-allowed flex items-center justify-between">
            Casos guardados
            <LockIcon />
          </div>
        </nav>

        <div className="p-3 border-t border-[#E5EFE9] text-xs text-[#9CA8A1]">
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
    <div className="mt-4 pt-3 border-t border-[#E5EFE9] flex flex-wrap gap-2">
      {fuentes.map((f, i) => (
        <span
          key={i}
          className="text-xs bg-[#EAFBF3] text-[#2E8F63] px-2.5 py-1 rounded-full border border-[#D3F0E1]"
        >
          {f.fuente}
          {f.categoria && f.categoria !== 'por_definir' ? ` · ${f.categoria.replace(/_/g, ' ')}` : ''}
        </span>
      ))}
    </div>
  );
}

/* -------------------- Preguntas relacionadas -------------------- */
function SugerenciasRelacionadas({ sugerencias, esUltima, onElegir }) {
  if (!esUltima || !sugerencias || sugerencias.length === 0) return null;
  return (
    <div className="mt-4 pt-4 border-t border-[#E5EFE9]">
      <p className="text-xs font-medium text-[#9CA8A1] mb-2">También te puede interesar</p>
      <div className="flex flex-col gap-2">
        {sugerencias.map((s, i) => (
          <button
            key={i}
            onClick={() => onElegir(s)}
            className="text-left text-sm px-3 py-2 rounded-xl border border-[#E5EFE9] text-[#374151] hover:border-[#2EB37C]/50 hover:bg-[#F3FAF6] transition-colors"
          >
            {s}
          </button>
        ))}
      </div>
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
    <div className="flex items-center gap-3 text-[#6B7280] text-sm bg-white rounded-2xl px-4 py-3 w-fit shadow-sm">
      <div className="flex gap-1">
        <span className="w-2 h-2 rounded-full bg-[#2EB37C] animate-bounce [animation-delay:-0.3s]" />
        <span className="w-2 h-2 rounded-full bg-[#2EB37C] animate-bounce [animation-delay:-0.15s]" />
        <span className="w-2 h-2 rounded-full bg-[#2EB37C] animate-bounce" />
      </div>
      <span>{MENSAJES_CARGA[mensajeIdx]}</span>
    </div>
  );
}

/* -------------------- Componente principal -------------------- */
export default function ChatTributario() {
  const [cargandoApp, setCargandoApp] = useState(true);
  const [pregunta, setPregunta] = useState('');
  const [chatLog, setChatLog] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sidebarAbierta, setSidebarAbierta] = useState(false);
  const finRef = useRef(null);

  useEffect(() => {
    const t = setTimeout(() => setCargandoApp(false), 1600);
    return () => clearTimeout(t);
  }, []);

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
          { remitente: 'ia', texto: data.respuesta, fuentes: data.fuentes, degradado: data.degradado, sugerencias: data.sugerencias },
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

  const preguntasUsuario = chatLog.filter((m) => m.remitente === 'usuario').map((m) => m.texto);

  if (cargandoApp) return <PantallaCarga />;

  return (
    <div className="flex h-screen bg-[#EEFBF5] text-[#0F2A1D] font-sans overflow-hidden">
      <Sidebar abierta={sidebarAbierta} onCerrar={() => setSidebarAbierta(false)} historial={preguntasUsuario} />

      <div className="flex-1 flex flex-col min-w-0">
        <header className="md:hidden flex items-center gap-3 p-4 bg-white border-b border-[#E5EFE9]">
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
                <h1 className="text-2xl md:text-3xl font-semibold text-[#0F2A1D] mb-2">
                  Hola, ¿en qué te ayudo hoy?
                </h1>
                <p className="text-[#6B7280] mb-8">
                  Pregunta lo que necesites sobre normativa tributaria peruana, o elige un acceso rápido.
                </p>
                <div className="grid gap-3 sm:grid-cols-1">
                  {ACCESOS_RAPIDOS.map((a, i) => (
                    <button
                      key={i}
                      onClick={() => enviarPregunta(a.titulo)}
                      className="text-left p-4 rounded-2xl bg-white border border-[#E5EFE9] hover:border-[#2EB37C]/50 hover:shadow-md transition-all shadow-sm"
                    >
                      <p className="text-[#0F2A1D] font-medium mb-1">{a.titulo}</p>
                      <p className="text-sm text-[#6B7280]">{a.detalle}</p>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {chatLog.map((msg, index) =>
                  msg.remitente === 'usuario' ? (
                    <div key={index} className="flex justify-end">
                      <div className="max-w-lg bg-[#2EB37C] text-white px-4 py-2.5 rounded-3xl rounded-br-md shadow-sm">
                        {msg.texto}
                      </div>
                    </div>
                  ) : (
                    <div
                      key={index}
                      className={`rounded-3xl p-5 bg-white shadow-sm ${msg.error ? 'text-[#C0523F]' : ''}`}
                    >
                      {msg.degradado && (
                        <span className="inline-block mb-2 text-xs font-medium text-[#B8860B] bg-[#FDF3D9] px-2 py-0.5 rounded-full">
                          Respuesta sin pulir — alta demanda
                        </span>
                      )}
                      <div>{renderTextoFormateado(msg.texto)}</div>
                      <Referencias fuentes={msg.fuentes} />
                      <SugerenciasRelacionadas
                        sugerencias={msg.sugerencias}
                        esUltima={index === chatLog.length - 1}
                        onElegir={enviarPregunta}
                      />
                    </div>
                  )
                )}
                {loading && <IndicadorEscribiendo />}
              </div>
            )}
            <div ref={finRef} />
          </div>
        </div>

        <div className="bg-[#EEFBF5] pb-4 pt-2">
          <form onSubmit={handleSubmit} className="max-w-3xl mx-auto px-4 md:px-6">
            <div className="flex items-end gap-2 bg-white border border-[#E5EFE9] rounded-3xl px-4 py-2 shadow-sm focus-within:border-[#2EB37C]/60">
              <textarea
                value={pregunta}
                onChange={(e) => setPregunta(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                placeholder="Escribe tu consulta sobre normativa tributaria..."
                className="flex-1 bg-transparent resize-none outline-none text-[#0F2A1D] placeholder-[#9CA8A1] py-2 max-h-32"
              />
              <button
                type="submit"
                disabled={loading || !pregunta.trim()}
                className="shrink-0 bg-[#2EB37C] hover:bg-[#29A06F] disabled:opacity-40 disabled:hover:bg-[#2EB37C] text-white font-medium px-5 py-2 rounded-full transition-colors flex items-center gap-1.5"
              >
                Enviar
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </button>
            </div>
            <p className="text-xs text-[#9CA8A1] mt-2 text-center">
              El asistente puede cometer errores. Verifica la normativa citada antes de aplicarla.
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
