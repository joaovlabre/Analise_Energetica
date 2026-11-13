// Utilitários comuns das telas do SGE
const SGE = {
  async get(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  },
  num(v, casas = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e12 || (a > 0 && a < 1e-4)) return Number(v).toExponential(3).replace(".", ",");
    return Number(v).toLocaleString("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });
  },
  casas(unidade, grandeza) {
    if (grandeza && grandeza.startsWith("energia")) return 1;
    if (!unidade) return 3; // FP
    if (unidade === "Hz") return 2;
    return unidade === "s" ? 0 : 2;
  },
  dataHora(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleString("pt-BR", { timeZone: "America/Araguaina" });
  },
  hora(iso) {
    return new Date(iso).toLocaleTimeString("pt-BR", { timeZone: "America/Araguaina", hour: "2-digit", minute: "2-digit" });
  },
  selo(online) {
    if (online === true) return '<span class="selo ok">Online</span>';
    if (online === false) return '<span class="selo falha">Sem comunicação</span>';
    return '<span class="selo neutro">Sem dados</span>';
  },
  cor(nome) {
    return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  },
  async preencherDispositivos(select) {
    const lista = await SGE.get("/api/dispositivos");
    select.innerHTML = lista.map(d => `<option value="${d.id}">${d.nome} (${d.modelo})</option>`).join("");
    return lista;
  },
  eixos(unidade) {
    const grid = SGE.cor("--grid"), txt = SGE.cor("--text-secondary");
    return {
      x: { ticks: { color: txt, maxRotation: 0, autoSkipPadding: 24 }, grid: { display: false } },
      y: { ticks: { color: txt }, grid: { color: grid }, title: { display: !!unidade, text: unidade, color: txt } },
    };
  },
};
