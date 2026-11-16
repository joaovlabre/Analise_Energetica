// Diagrama unifilar em SVG (montado a partir da configuração do diagrama) com valores ao vivo.
const NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, filhos = []) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) e.setAttribute(k, v);
  for (const f of [].concat(filhos)) if (f) e.appendChild(typeof f === "string" ? document.createTextNode(f) : f);
  return e;
}
const texto = (x, y, t, attrs = {}) => el("text", { x, y, ...attrs }, [t]);
const kv = v => (v === null || v === undefined) ? null : Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 3 });

// Conversão só para exibição (o banco guarda a unidade nativa do mapa)
const FATOR_EXIBICAO = { "kW>W": 1000, "W>kW": 0.001, "kWh>Wh": 1000, "kvar>var": 1000, "kVA>VA": 1000 };
function converter(valor, de, para) {
  if (!para || de === para) return { valor, unidade: de };
  const f = FATOR_EXIBICAO[`${de}>${para}`];
  return f ? { valor: valor === null ? null : valor * f, unidade: para } : { valor, unidade: de };
}

// ---------------------------------------------------------------- ícones dos medidores
// Desenhos próprios, inspirados no formato dos aparelhos (sem logotipos de fabricante).
const ICONES = {
  // Schneider GoLogic EM3261: caixa quadrada cinza-clara, 3 LEDs (L1 L2 L3), visor LCD largo e 4 botões redondos.
  schneider_em3261(g) {
    g.appendChild(el("rect", { x: 0, y: 0, width: 110, height: 104, rx: 8, fill: "#e6e8ea", stroke: "#a9b0b5", "stroke-width": 1.5 }));
    g.appendChild(el("rect", { x: 4, y: 4, width: 102, height: 96, rx: 6, fill: "none", stroke: "#f7f8f9", "stroke-width": 1 }));
    g.appendChild(texto(9, 15, "EM3261", { "font-size": 7, fill: "#5f676d", "font-weight": 600 }));
    [30, 55, 80].forEach((x, i) => {
      g.appendChild(el("circle", { cx: x, cy: 25, r: 2.6, fill: "#3dbb5c", class: "led" }));
      g.appendChild(texto(x + 5, 27.5, `L${i + 1}`, { "font-size": 5.5, fill: "#7a8288" }));
    });
    g.appendChild(el("rect", { x: 10, y: 34, width: 90, height: 34, rx: 2, fill: "#c4d6e2", stroke: "#7d8f99", "stroke-width": 1.2 }));
    [41, 50, 59].forEach((y, i) => g.appendChild(el("rect", { x: 16, y, width: [60, 70, 48][i], height: 3, fill: "#5d7180", opacity: 0.75 })));
    [32, 48, 64, 80].forEach(x => g.appendChild(el("circle", { cx: x, cy: 84, r: 5.5, fill: "#f3f4f5", stroke: "#8e979d", "stroke-width": 1 })));
    return { largura: 110, altura: 104 };
  },
  // WEG MMW02: caixa preta, frente cinza-azulada, visor LCD azul, teclado em losango e teclas PROG / CLEAR.
  weg_mmw02(g) {
    g.appendChild(el("rect", { x: 0, y: 0, width: 104, height: 104, rx: 5, fill: "#1e2124", stroke: "#000", "stroke-width": 1 }));
    g.appendChild(el("rect", { x: 7, y: 7, width: 90, height: 90, rx: 3, fill: "#c9ced6", stroke: "#8f98a3", "stroke-width": 1 }));
    g.appendChild(texto(91, 18, "MMW02", { "font-size": 7.5, "font-style": "italic", "text-anchor": "end", fill: "#2b3440" }));
    g.appendChild(el("rect", { x: 15, y: 23, width: 74, height: 32, rx: 2, fill: "#1f62c6", stroke: "#123f86", "stroke-width": 1.2 }));
    [30, 38, 46].forEach((y, i) => g.appendChild(el("rect", { x: 20, y, width: [44, 52, 36][i], height: 2.4, fill: "#dfe9fb", opacity: 0.85 })));
    g.appendChild(texto(52, 61, "ELECTRICAL POWER METER", { "font-size": 3.6, "text-anchor": "middle", fill: "#3b4552" }));
    const cx = 32, cy = 78;
    g.appendChild(el("rect", { x: cx - 11, y: cy - 11, width: 22, height: 22, transform: `rotate(45 ${cx} ${cy})`, fill: "#2b6fd6", stroke: "#164a99" }));
    g.appendChild(el("circle", { cx, cy, r: 3, fill: "#dfe9fb" }));
    g.appendChild(el("rect", { x: 54, y: 72, width: 14, height: 11, rx: 1.5, fill: "#2b6fd6" }));
    g.appendChild(el("rect", { x: 71, y: 72, width: 14, height: 11, rx: 1.5, fill: "#2b6fd6" }));
    g.appendChild(texto(61, 79, "PROG", { "font-size": 3.6, "text-anchor": "middle", fill: "#fff" }));
    g.appendChild(texto(78, 79, "CLEAR", { "font-size": 3.6, "text-anchor": "middle", fill: "#fff" }));
    return { largura: 104, altura: 104 };
  },
  generico(g) {
    g.appendChild(el("rect", { x: 0, y: 0, width: 90, height: 90, rx: 6, fill: "#eceff1", stroke: "#90a4ae" }));
    g.appendChild(el("rect", { x: 10, y: 14, width: 70, height: 30, rx: 2, fill: "#cfd8dc" }));
    [22, 30].forEach(y => g.appendChild(el("rect", { x: 16, y, width: 50, height: 3, fill: "#78909c" })));
    return { largura: 90, altura: 90 };
  },
};

// ---------------------------------------------------------------- desenho do unifilar
function desenharUnifilar(svg, d) {
  const n = d.transformadores.length;
  const passo = 260, x0 = 210, yBarra = 120;
  const largura = x0 + passo * Math.max(n - 1, 0) + 230;
  const altura = 500;
  svg.setAttribute("viewBox", `0 0 ${largura} ${altura}`);
  svg.innerHTML = "";
  const medidores = [];

  // entrada e barra
  const xIni = 70, xFim = x0 + passo * (n - 1) + 90;
  if (d.entrada) {
    svg.appendChild(el("line", { x1: xIni + 30, y1: 30, x2: xIni + 30, y2: yBarra, class: "linha-mt" }));
    svg.appendChild(el("path", { d: `M ${xIni + 24} 44 L ${xIni + 30} 56 L ${xIni + 36} 44`, class: "linha-mt", fill: "none" }));
    svg.appendChild(texto(xIni + 40, 42, d.entrada, { class: "rotulo" }));
  }
  svg.appendChild(el("line", { x1: xIni, y1: yBarra, x2: xFim, y2: yBarra, class: "barra-mt" }));
  svg.appendChild(texto(d.entrada ? xIni + 44 : xIni, yBarra - 14, d.barra.nome, { class: "rotulo forte" }));

  d.transformadores.forEach((t, i) => {
    const cx = x0 + passo * i;
    const g = el("g", { class: "trafo" });
    // ligação à barra (com ponto de conexão)
    g.appendChild(el("circle", { cx, cy: yBarra, r: 4, class: "no" }));
    g.appendChild(el("line", { x1: cx, y1: yBarra, x2: cx, y2: 180, class: "linha-mt" }));
    // símbolo do transformador: dois enrolamentos
    g.appendChild(el("circle", { cx, cy: 206, r: 26, class: "enrolamento" }));
    g.appendChild(el("circle", { cx, cy: 244, r: 26, class: "enrolamento" }));
    g.appendChild(el("line", { x1: cx, y1: 270, x2: cx, y2: 330, class: "linha-bt" }));
    g.appendChild(el("path", { d: `M ${cx - 6} 322 L ${cx} 334 L ${cx + 6} 322`, class: "linha-bt", fill: "none" }));
    // rótulos
    const xr = cx + 34;
    const volts = v => v === null || v === undefined ? null : (v < 1 ? `${Math.round(v * 1000)}` : kv(v));
    const tp = kv(t.tensao_primaria_kv);
    const sec = t.tensao_secundaria_kv ? `${volts(t.tensao_secundaria_kv)}${t.tensao_secundaria_fn_kv ? "/" + volts(t.tensao_secundaria_fn_kv) : ""} ${t.tensao_secundaria_kv < 1 ? "V" : "kV"}` : null;
    const linhas = [
      [t.nome, "rotulo forte"],
      [t.potencia_kva ? `${kv(t.potencia_kva)} kVA` : "potência a definir", t.potencia_kva ? "rotulo" : "rotulo indefinido"],
      [`${tp ? tp + " kV" : "?"} / ${sec ?? "?"}`, sec ? "rotulo" : "rotulo indefinido"],
      [[t.ligacao, t.impedancia_pct ? `Z ${kv(t.impedancia_pct)}%` : null].filter(Boolean).join(" · "), "rotulo pequeno"],
      [t.corrente_nominal_primaria_a ? `In ${kv(t.corrente_nominal_primaria_a)} A (13,8 kV)` : "", "rotulo pequeno"],
    ];
    linhas.forEach(([txt, cls], i) => txt && g.appendChild(texto(xr, 196 + i * 15, txt, { class: cls })));
    if (sec) g.appendChild(texto(cx + 10, 318, sec, { class: "rotulo pequeno" }));

    if (t.medidor) {
      const m = t.medidor;
      // TC no secundário e ligação tracejada até o medidor
      g.appendChild(el("circle", { cx, cy: 292, r: 7, class: "tc" }));
      g.appendChild(el("line", { x1: cx - 7, y1: 292, x2: cx - 30, y2: 292, class: "ligacao-medicao" }));
      g.appendChild(el("line", { x1: cx - 30, y1: 292, x2: cx - 30, y2: 360, class: "ligacao-medicao" }));
      const gm = el("g", { class: "medidor sem-dados" });
      const corpo = el("g");
      const tam = (ICONES[m.icone] || ICONES.generico)(corpo);
      const xm = cx - 30 - tam.largura / 2, ym = 360;
      gm.setAttribute("transform", `translate(${xm} ${ym})`);
      gm.appendChild(el("rect", { x: -5, y: -5, width: tam.largura + 10, height: tam.altura + 10, rx: 10, class: "moldura" }));
      gm.appendChild(corpo);
      gm.appendChild(texto(tam.largura / 2, tam.altura + 20, m.dispositivo, { class: "rotulo pequeno", "text-anchor": "middle" }));
      gm.appendChild(el("text", { x: tam.largura / 2, y: tam.altura + 34, class: "estado", "text-anchor": "middle" }, [""]));
      const dica = el("title", {}, [m.dispositivo]);
      gm.appendChild(dica);
      const lateral = el("g", { transform: `translate(${tam.largura + 12} ${tam.altura / 2 - 26})` });
      lateral.appendChild(el("rect", { x: 0, y: 0, width: 126, height: 52, rx: 6, class: "caixa-valor" }));
      lateral.appendChild(texto(10, 16, SGE.rotulo(m.grandeza), { class: "rotulo pequeno" }));
      lateral.appendChild(el("text", { x: 10, y: 40, class: "valor-lateral" }, ["—"]));
      gm.appendChild(lateral);
      gm.setAttribute("tabindex", "0");
      gm.setAttribute("role", "button");
      gm.addEventListener("click", () => abrirDetalhe(m));
      gm.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrirDetalhe(m); } });
      g.appendChild(gm);
      medidores.push({ m, gm, lateral, dica });
    }
    svg.appendChild(g);
  });
  return medidores;
}

function atualizarMedidores(medidores, vivo) {
  for (const { m, gm, lateral, dica } of medidores) {
    const est = vivo[String(m.dispositivo_id)];
    const lido = est && est.valores[m.grandeza];
    const online = est ? est.online : null;
    gm.classList.toggle("online", online === true);
    gm.classList.toggle("offline", online === false);
    gm.classList.toggle("sem-dados", online === null || online === undefined);
    const ruim = lido && lido.qualidade !== "ok";
    gm.classList.toggle("qualidade-ruim", !!ruim);
    let txt = "—", unid = "";
    if (lido && online !== false) {
      const c = converter(lido.valor, lido.unidade, m.unidade_exibicao);
      txt = SGE.num(c.valor, c.unidade === "W" ? 0 : 2);
      unid = c.unidade;
    }
    const estado = online === false ? "sem comunicação" : (ruim ? `qualidade: ${lido.qualidade}` : (lido ? SGE.dataHora(lido.ts).split(" ")[1] || "" : "sem leitura"));
    gm.querySelector(".estado").textContent = estado;
    lateral.querySelector(".valor-lateral").textContent = `${txt} ${unid}`.trim();
    dica.textContent = `${m.dispositivo} · ${SGE.rotulo(m.grandeza)}: ${txt} ${unid}` + (lido ? ` · lido em ${SGE.dataHora(lido.ts)}` : "") + "\nClique para ver todas as medições";
  }
}

// ---------------------------------------------------------------- tela do medidor (web/static/medidor.js)
function abrirDetalhe(m) {
  if (m.dispositivo_id) MED.abrir(m.dispositivo_id);
}

async function iniciarDiagrama(svg, slug) {
  const d = await SGE.get(`/api/diagramas/${slug}`);
  const medidores = desenharUnifilar(svg, d);
  const itens = medidores.filter(x => x.m.dispositivo_id).map(x => ({ dispositivo_id: x.m.dispositivo_id, grandezas: [x.m.grandeza] }));
  async function ciclo() {
    try {
      const r = await fetch("/api/ao_vivo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ itens }) });
      atualizarMedidores(medidores, r.ok ? await r.json() : {});
    } catch (e) { console.error(e); }
  }
  await ciclo();
  setInterval(ciclo, 2000);
}
