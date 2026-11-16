// Utilitários comuns das telas do SGE
const SGE = {
  ROTULOS: {
    potencia_ativa_total: "Potência ativa", potencia_reativa_total: "Potência reativa", potencia_aparente_total: "Potência aparente",
    fp_total: "Fator de potência", tensao_ff_media: "Tensão F-F média", tensao_fn_media: "Tensão F-N média",
    corrente_media: "Corrente média", frequencia: "Frequência", energia_ativa_importada: "Energia ativa (totalizador)",
    energia_reativa_importada: "Energia reativa (totalizador)",
  },
  // Nome legível de uma grandeza canônica (ex.: tensao_ab -> "Tensão AB", fp_a_4q -> "Fator de potência A (4Q)")
  rotulo(g) {
    if (SGE.ROTULOS[g]) return SGE.ROTULOS[g];
    const PALAVRAS = { tensao: "Tensão", corrente: "Corrente", potencia: "Potência", ativa: "ativa", reativa: "reativa", aparente: "aparente",
      fp: "Fator de potência", energia: "Energia", demanda: "Demanda", thd: "THD", desequilibrio: "Desequilíbrio", carregamento: "Carregamento",
      importada: "importada", exportada: "exportada", liquida: "líquida", bruta: "bruta", prevista: "prevista", ultima: "último intervalo",
      pico: "pico", media: "média", medio: "médio", total: "total", max: "máx.", ff: "F-F", fn: "F-N", zeravel: "(zerável)", float: "(float)",
      caracteristica: "característica", tp: "TP", tc: "TC", primario: "primário", secundario: "secundário", numero: "Número", serie: "de série",
      falhas: "Falhas", alimentacao: "de alimentação", tempo: "Tempo", operacao: "de operação", horas: "Horas", carga: "carga",
      permanente: "permanente", frequencia: "Frequência", timestamp: "Relógio", medidor: "do medidor", exp: "exp.", imp: "imp.",
      indutiva: "indutiva", capacitiva: "capacitiva", q1: "Q1", q2: "Q2", "4q": "(4Q)", "64": "(64 bits)" };
    const FASES = { a: "A", b: "B", c: "C", n: "N", ab: "AB", bc: "BC", ca: "CA", an: "AN", bn: "BN", cn: "CN" };
    return g.split("_").map((p, i) => {
      if (FASES[p]) return FASES[p];
      const w = PALAVRAS[p] || p;
      return i > 0 && /^[A-ZÀ-Ú][a-zà-ú]/.test(w) ? w[0].toLowerCase() + w.slice(1) : w;  // só a 1ª palavra maiúscula
    }).join(" ");
  },
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
