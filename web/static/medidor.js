// Tela do medidor no estilo da "device diagram" do PME: abas Tensões/Correntes, Qualidade de energia,
// Energia e demanda, Limites e Configuração/Diagnóstico. Só mostra grandezas que existem no mapa do medidor;
// o que o aparelho não fornece aparece como "—" / "não disponível".
const MED = (() => {
  const NS = "http://www.w3.org/2000/svg";
  let timer = null, atualId = null, abaAtual = "va";

  const ABAS = [
    ["va", "Tensões/Correntes"], ["qe", "Qualidade de energia"], ["ed", "Energia e demanda"],
    ["li", "Limites"], ["cd", "Configuração/Diagnóstico"],
  ];
  const CASAS = { V: 1, A: 1, kW: 2, kvar: 2, kVA: 2, Hz: 2, "%": 1, kWh: 0, kvarh: 0, kVAh: 0 };

  function fmt(v, unidade, sufixo = "", casas) {
    if (!v) return { texto: "—", classe: "nd" };
    const c = casas ?? CASAS[v.unidade] ?? 3;
    const u = unidade ?? v.unidade;
    return { texto: `${SGE.num(v.valor, c)}${u ? " " + u : ""}${sufixo ? " " + sufixo : ""}`, classe: v.qualidade === "ok" ? "" : "ruim" };
  }

  // ------------------------------------------------------------ SVG helpers
  const s = (tag, a = {}, txt) => { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (txt !== undefined) e.textContent = txt; return e; };
  function caixa(svg, x, y, w, h, grandeza, sufixo = "", casas) {
    const g = s("g", { class: "pme-caixa", "data-g": grandeza, "data-sufixo": sufixo, ...(casas !== undefined ? { "data-casas": casas } : {}) });
    g.appendChild(s("rect", { x, y, width: w, height: h }));
    g.appendChild(s("text", { x: x + w / 2, y: y + h / 2 + 5, "text-anchor": "middle" }, "—"));
    svg.appendChild(g);
  }
  const rotulo = (svg, x, y, t, anchor = "middle") => svg.appendChild(s("text", { x, y, class: "pme-rotulo", "text-anchor": anchor }, t));
  const linha = (svg, x1, y1, x2, y2, tracejada) => svg.appendChild(s("line", { x1, y1, x2, y2, class: tracejada ? "pme-linha tracejada" : "pme-linha" }));
  const seta = (svg, x, y, dir) => svg.appendChild(s("path", { d: dir === "baixo" ? `M ${x - 7} ${y - 12} L ${x + 7} ${y - 12} L ${x} ${y} Z` : `M ${x - 7} ${y + 12} L ${x + 7} ${y + 12} L ${x} ${y} Z`, class: "pme-seta" }));
  const setaH = (svg, x, y, dir) => svg.appendChild(s("path", { d: dir === "dir" ? `M ${x - 10} ${y - 5} L ${x} ${y} L ${x - 10} ${y + 5}` : `M ${x + 10} ${y - 5} L ${x} ${y} L ${x + 10} ${y + 5}`, class: "pme-linha", fill: "none" }));

  // ------------------------------------------------------------ aba Tensões/Correntes (diagrama trifásico)
  function abaVA() {
    const svg = s("svg", { viewBox: "0 0 1220 560", class: "pme-svg" });
    rotulo(svg, 140, 60, "Tensões F-F"); rotulo(svg, 333, 60, "Corrente"); rotulo(svg, 495, 60, "Potência ativa");
    // fases c (topo), b, a e neutro
    linha(svg, 40, 95, 925, 95); linha(svg, 165, 200, 797, 200); linha(svg, 40, 307, 670, 307); linha(svg, 40, 520, 925, 520);
    rotulo(svg, 30, 99, "C", "end"); rotulo(svg, 155, 204, "B", "end"); rotulo(svg, 30, 311, "A", "end"); rotulo(svg, 30, 524, "N", "end");
    [["c", 77], ["b", 183], ["a", 290]].forEach(([f, y]) => {
      caixa(svg, 272, y, 124, 36, `corrente_${f}`, f);
      caixa(svg, 434, y, 124, 36, `potencia_ativa_${f}`, f);
    });
    // V bc (c -> b), V ab (b -> a)
    linha(svg, 199, 95, 199, 127); caixa(svg, 134, 127, 124, 36, "tensao_bc", "bc"); linha(svg, 199, 163, 199, 200); seta(svg, 199, 200, "baixo");
    linha(svg, 199, 200, 199, 233); caixa(svg, 134, 233, 124, 36, "tensao_ab", "ab"); linha(svg, 199, 269, 199, 307); seta(svg, 199, 307, "baixo");
    // V ca (a -> c)
    linha(svg, 70, 307, 70, 217, true); caixa(svg, 9, 181, 124, 36, "tensao_ca", "ca"); linha(svg, 70, 181, 70, 95, true); seta(svg, 70, 95, "cima");
    // tensões F-N (neutro -> fase)
    [["an", 670, 307], ["bn", 797, 200], ["cn", 925, 95]].forEach(([f, x, y]) => {
      linha(svg, x, 520, x, 436, true); caixa(svg, x - 62, 400, 124, 36, `tensao_${f}`, f); linha(svg, x, 400, x, y, true); seta(svg, x, y, "cima");
    });
    rotulo(svg, 795, 540, "Tensões F-N");
    // totais
    rotulo(svg, 496, 343, "Potência ativa total"); caixa(svg, 434, 353, 124, 36, "potencia_ativa_total");
    rotulo(svg, 496, 407, "Potência reativa total"); caixa(svg, 434, 417, 124, 36, "potencia_reativa_total");
    rotulo(svg, 496, 469, "Potência aparente total"); caixa(svg, 434, 479, 124, 36, "potencia_aparente_total");
    rotulo(svg, 159, 407, "% desequilíbrio V"); caixa(svg, 97, 417, 124, 36, "desequilibrio_tensao_ff_max");
    rotulo(svg, 159, 469, "Tensão F-F média"); caixa(svg, 97, 479, 124, 36, "tensao_ff_media");
    rotulo(svg, 333, 407, "Corrente média"); caixa(svg, 272, 417, 124, 36, "corrente_media");
    rotulo(svg, 333, 469, "Corrente de neutro"); caixa(svg, 272, 479, 124, 36, "corrente_n");
    rotulo(svg, 1098, 78, "Frequência"); caixa(svg, 1036, 88, 124, 36, "frequencia");
    rotulo(svg, 1098, 169, "Fator de potência"); caixa(svg, 1036, 180, 124, 36, "fp_total", "", 3);
    rotulo(svg, 1098, 260, "% desequilíbrio I"); caixa(svg, 1036, 271, 124, 36, "desequilibrio_corrente_max");
    rotulo(svg, 1098, 390, "Tensão F-N média"); caixa(svg, 1036, 400, 124, 36, "tensao_fn_media");
    const div = document.createElement("div"); div.className = "pme-painel"; div.appendChild(svg);
    return div;
  }

  // ------------------------------------------------------------ aba Qualidade de energia
  function abaQE() {
    const div = document.createElement("div"); div.className = "pme-grade";
    div.innerHTML = `
      <section class="pme-secao"><h3>Distorção harmônica total (THD)</h3>
        <div class="pme-thd">
          <span>Tensão A</span><b data-g="thd_tensao_a"></b><span>Corrente A</span><b data-g="thd_corrente_a"></b>
          <span>Tensão B</span><b data-g="thd_tensao_b"></b><span>Corrente B</span><b data-g="thd_corrente_b"></b>
          <span>Tensão C</span><b data-g="thd_tensao_c"></b><span>Corrente C</span><b data-g="thd_corrente_c"></b>
        </div>
        <p class="pme-nd-aviso" data-se-falta="thd_tensao_a">Este medidor não fornece THD.</p>
      </section>
      <section class="pme-secao"><h3>Desequilíbrio e carregamento</h3>
        <div class="pme-form">
          <span>Desequilíbrio de tensão F-F (máx.)</span><b data-g="desequilibrio_tensao_ff_max"></b>
          <span>Desequilíbrio de tensão F-N (máx.)</span><b data-g="desequilibrio_tensao_fn_max"></b>
          <span>Desequilíbrio de corrente (máx.)</span><b data-g="desequilibrio_corrente_max"></b>
          <span>Carregamento médio</span><b data-g="carregamento_medio"></b>
          <span>Fator de potência A / B / C</span><b data-g="fp_a"></b>
        </div>
      </section>
      <section class="pme-secao pme-links"><h3>Atalhos</h3>
        <a href="/tendencias">📈<br>Tendências</a><a href="/comunicacao">📡<br>Comunicação</a>
      </section>`;
    return div;
  }

  // ------------------------------------------------------------ aba Energia e demanda
  function abaED() {
    const div = document.createElement("div"); div.className = "pme-grade";
    const quad = document.createElement("section"); quad.className = "pme-secao";
    quad.innerHTML = "<h3>Potência instantânea</h3>";
    const svg = s("svg", { viewBox: "0 0 480 500", class: "pme-svg" });
    rotulo(svg, 240, 22, "+ kvar"); rotulo(svg, 240, 482, "− kvar"); rotulo(svg, 70, 174, "− kW"); rotulo(svg, 410, 174, "+ kW");
    [["Quadrante II", 95, 58], ["Quadrante I", 375, 58], ["Quadrante III", 95, 362], ["Quadrante IV", 375, 362]].forEach(([t, x, y]) => svg.appendChild(s("text", { x, y, class: "pme-rotulo forte", "text-anchor": "middle" }, t)));
    svg.appendChild(s("line", { x1: 240, y1: 30, x2: 240, y2: 470, class: "pme-eixo" }));
    svg.appendChild(s("line", { x1: 55, y1: 200, x2: 425, y2: 200, class: "pme-eixo" }));
    [[236, 92, 236, 308], [244, 92, 244, 308], [130, 196, 350, 196], [130, 204, 350, 204]].forEach(([x1, y1, x2, y2]) =>
      svg.appendChild(s("line", { x1, y1, x2, y2, class: "pme-fina" })));
    seta(svg, 240, 82, "cima"); seta(svg, 240, 318, "baixo"); setaH(svg, 362, 200, "dir"); setaH(svg, 118, 200, "esq");
    // caixas de cada quadrante (preenchidas conforme o sinal de P e Q)
    const q = (x, y, id) => { const g = s("g", { class: "pme-caixa", id }); g.appendChild(s("rect", { x, y, width: 100, height: 34 })); g.appendChild(s("text", { x: x + 50, y: y + 22, "text-anchor": "middle" }, "—")); svg.appendChild(g); };
    q(190, 44, "q-kvar-pos"); q(190, 322, "q-kvar-neg"); q(20, 183, "q-kw-neg"); q(360, 183, "q-kw-pos");
    q(35, 105, "q-kva-2"); q(345, 105, "q-kva-1"); q(35, 258, "q-kva-3"); q(345, 258, "q-kva-4");
    quad.appendChild(svg);
    quad.insertAdjacentHTML("beforeend", `<div class="pme-form"><span>Fator de potência</span><b data-g="fp_total" data-casas="3"></b></div>`);

    const en = document.createElement("section"); en.className = "pme-secao";
    en.innerHTML = `<h3>Energia e demanda</h3>
      <p class="pme-sub">Demanda informada pelo medidor</p>
      <table class="pme-tabela"><thead><tr><th></th><th>kW</th><th>kvar</th><th>kVA</th></tr></thead><tbody>
        <tr><th>Prevista</th><td data-g="demanda_ativa_prevista"></td><td data-g="demanda_reativa_prevista"></td><td data-g="demanda_aparente_prevista"></td></tr>
        <tr><th>Último intervalo</th><td data-g="demanda_ativa_ultima"></td><td data-g="demanda_reativa_ultima"></td><td data-g="demanda_aparente_ultima"></td></tr>
        <tr><th>Pico</th><td data-g="demanda_ativa_pico"></td><td data-g="demanda_reativa_pico"></td><td data-g="demanda_aparente_pico"></td></tr>
      </tbody></table>
      <p class="pme-sub">Demanda calculada pelo SGE (último intervalo de 15 min, pela energia do totalizador)</p>
      <table class="pme-tabela"><thead><tr><th></th><th>kW</th><th>kvar</th><th>Intervalo</th></tr></thead><tbody>
        <tr><th>Calculada</th><td id="dem-kw">—</td><td id="dem-kvar">—</td><td id="dem-ini">—</td></tr>
      </tbody></table>
      <p class="pme-sub">Energia (totalizadores)</p>
      <table class="pme-tabela"><thead><tr><th></th><th>kWh</th><th>kvarh</th><th>kVAh</th></tr></thead><tbody>
        <tr><th>Importada</th><td data-g="energia_ativa_importada" data-casas="0"></td><td data-g="energia_reativa_importada" data-casas="0"></td><td data-g="energia_aparente" data-casas="0"></td></tr>
        <tr><th>Exportada</th><td data-g="energia_ativa_exportada" data-casas="0"></td><td data-g="energia_reativa_exportada" data-casas="0"></td><td>—</td></tr>
        <tr><th>Líquida (imp − exp)</th><td data-g="energia_ativa_liquida" data-casas="0"></td><td data-g="energia_reativa_liquida" data-casas="0"></td><td>—</td></tr>
        <tr><th>Bruta (imp + exp)</th><td data-g="energia_ativa_bruta" data-casas="0"></td><td data-g="energia_reativa_bruta" data-casas="0"></td><td>—</td></tr>
      </tbody></table>`;
    const links = document.createElement("section"); links.className = "pme-secao pme-links";
    links.innerHTML = `<h3>Atalhos</h3><a href="/energia">📊<br>Energia 15 min</a><a href="/paineis/consumo-linha">⚙️<br>Consumo por linha</a><a href="/tendencias">📈<br>Tendências</a>`;
    div.append(quad, en, links);
    return div;
  }

  // ------------------------------------------------------------ aba Limites (faixas físicas da configuração)
  function abaLI() {
    const div = document.createElement("div"); div.className = "pme-grade";
    div.innerHTML = `<section class="pme-secao pme-largo"><h3>Limites (faixas físicas configuradas em coleta.faixas)</h3>
      <table class="pme-tabela pme-limites"><thead><tr><th>Grandeza</th><th>Situação</th><th>Valor atual</th><th>Faixa</th></tr></thead><tbody id="tab-limites"></tbody></table>
      <p class="pme-sub">Alarmes com limites próprios por medidor entram com o módulo de alarmes.</p></section>`;
    return div;
  }

  // ------------------------------------------------------------ aba Configuração/Diagnóstico
  function abaCD() {
    const div = document.createElement("div"); div.className = "pme-grade tres";
    div.innerHTML = `
      <section class="pme-secao"><h3>Medidor</h3><div class="pme-form" id="cd-medidor"></div></section>
      <section class="pme-secao"><h3>Comunicação</h3><div class="pme-form" id="cd-com"></div></section>
      <section class="pme-secao"><h3>Medição e relógio</h3><div class="pme-form" id="cd-relogio"></div></section>`;
    return div;
  }

  const CONSTRUTORES = { va: abaVA, qe: abaQE, ed: abaED, li: abaLI, cd: abaCD };

  // ------------------------------------------------------------ preenchimento
  function preencher(corpo, porNome, det) {
    corpo.querySelectorAll("[data-g]").forEach(el => {
      const v = porNome[el.dataset.g];
      const casas = el.dataset.casas !== undefined ? +el.dataset.casas : undefined;
      const f = fmt(v, el.tagName === "TD" ? "" : undefined, el.dataset.sufixo || "", casas);  // tabelas: unidade no cabeçalho
      const alvo = el.tagName.toLowerCase() === "g" ? el.querySelector("text") : el;
      alvo.textContent = f.texto;
      el.classList.toggle("ruim", f.classe === "ruim");
      el.classList.toggle("nd", f.classe === "nd");
      if (v) el.setAttribute("title", `${SGE.rotulo(el.dataset.g)} · qualidade: ${v.qualidade} · ${SGE.dataHora(v.ts)}`);
    });
    // FP por fase numa caixa só
    const fpf = corpo.querySelector('[data-g="fp_a"]');
    if (fpf) {
      const fps = ["a", "b", "c"].map(f => porNome[`fp_${f}`] || porNome[`fp_${f}_4q`]);
      fpf.textContent = fps.some(Boolean) ? fps.map(v => v ? SGE.num(v.valor, 3) : "—").join(" / ") : "—";
      fpf.classList.toggle("nd", !fps.some(Boolean));
      fpf.classList.toggle("ruim", fps.some(v => v && v.qualidade !== "ok"));
    }
    corpo.querySelectorAll("[data-se-falta]").forEach(el => el.hidden = !!porNome[el.dataset.seFalta]);

    // quadrantes
    const P = porNome.potencia_ativa_total, Q = porNome.potencia_reativa_total, S = porNome.potencia_aparente_total;
    const set = (id, t) => { const e = corpo.querySelector("#" + id + " text"); if (e) e.textContent = t; };
    if (corpo.querySelector("#q-kw-pos")) {
      const p = P ? P.valor : null, qv = Q ? Q.valor : null;
      set("q-kw-pos", p !== null && p >= 0 ? `${SGE.num(p, 2)} kW` : "0 kW");
      set("q-kw-neg", p !== null && p < 0 ? `${SGE.num(-p, 2)} kW` : "0 kW");
      set("q-kvar-pos", qv !== null && qv >= 0 ? `${SGE.num(qv, 2)} kvar` : "0 kvar");
      set("q-kvar-neg", qv !== null && qv < 0 ? `${SGE.num(-qv, 2)} kvar` : "0 kvar");
      const quadrante = p === null || qv === null ? 0 : (p >= 0 ? (qv >= 0 ? 1 : 4) : (qv >= 0 ? 2 : 3));
      [1, 2, 3, 4].forEach(n => set(`q-kva-${n}`, n === quadrante && S ? `${SGE.num(S.valor, 2)} kVA` : "0 kVA"));
    }
    if (!det) return;
    const dk = det.demanda_calculada.energia_ativa_importada, dq = det.demanda_calculada.energia_reativa_importada;
    const txt = (id, t) => { const e = corpo.querySelector("#" + id); if (e) e.textContent = t; };
    txt("dem-kw", dk ? `${SGE.num(dk.valor, 2)}` : "—");
    txt("dem-kvar", dq ? `${SGE.num(dq.valor, 2)}` : "—");
    txt("dem-ini", dk ? SGE.dataHora(dk.inicio) : "—");

    // limites
    const tl = corpo.querySelector("#tab-limites");
    if (tl) {
      const prefixos = Object.keys(det.faixas).sort((a, b) => b.length - a.length);
      const linhas = Object.values(porNome).sort((a, b) => a.grandeza.localeCompare(b.grandeza)).map(v => {
        const pfx = prefixos.find(p => v.grandeza.startsWith(p));
        if (!pfx) return null;
        const fx = det.faixas[pfx];
        const dentro = v.valor !== null && v.valor >= fx.minimo && v.valor <= fx.maximo;
        const sit = v.valor === null ? ["Sem leitura", "neutro"] : (dentro && v.qualidade !== "fora_faixa" ? ["Normal", "ok"] : ["Fora da faixa", "alarme"]);
        return `<tr><td>${SGE.rotulo(v.grandeza)}</td><td class="pme-sit ${sit[1]}">${sit[0]}</td>
          <td class="num">${SGE.num(v.valor, CASAS[v.unidade] ?? 3)} ${v.unidade}</td><td>${SGE.num(fx.minimo, 0)} a ${SGE.num(fx.maximo, 0)} ${v.unidade}</td></tr>`;
      }).filter(Boolean);
      tl.innerHTML = linhas.join("") || '<tr><td colspan="4" class="vazio">Nenhuma grandeza deste medidor tem faixa configurada.</td></tr>';
    }

    // configuração / diagnóstico
    const form = (id, pares) => { const e = corpo.querySelector("#" + id); if (e) e.innerHTML = pares.map(([k, v]) => `<span>${k}</span><b class="${v === null || v === undefined || v === "" ? "nd" : ""}">${v ?? "—"}</b>`).join(""); };
    const vv = g => porNome[g] ? SGE.num(porNome[g].valor, CASAS[porNome[g].unidade] ?? 0) + (porNome[g].unidade ? " " + porNome[g].unidade : "") : null;
    form("cd-medidor", [["Nome", det.nome], ["Modelo", det.modelo], ["Local", det.local], ["Nº de série", porNome.numero_serie ? String(porNome.numero_serie.valor) : null],
      ["Mapa de registradores", det.mapa], ["Grupos lidos", det.grupos.join(", ")], ["Ativo", det.ativo ? "sim" : "não"]]);
    const b = det.barramento || {};
    const ender = b.tipo === "serial" ? `${b.porta} · ${b.baudrate} 8${b.paridade}1` : (b.host ? `${b.host}:${b.porta_tcp}` : null);
    const e = det.estado || {};
    form("cd-com", [["Protocolo", det.origem], ["Barramento", b.nome ? `${b.nome} (${b.tipo})` : null], ["Endereço do gateway", ender], ["ID Modbus", det.endereco_modbus],
      ["Timeout / retentativas", b.nome ? `${SGE.num(b.timeout_s, 1)} s / ${b.retentativas}` : null],
      ["Situação", e.online === true ? "Online" : e.online === false ? "Sem comunicação" : null], ["Última leitura ok", e.ultima_ok ? SGE.dataHora(e.ultima_ok) : null],
      ["Pedidos ok / falhas", e.pedidos_ok !== undefined ? `${SGE.num(e.pedidos_ok, 0)} / ${SGE.num(e.pedidos_falha, 0)}` : null], ["Último erro", e.ultimo_erro]]);
    form("cd-relogio", [["TP primário / secundário", porNome.tp_primario ? `${vv("tp_primario")} / ${vv("tp_secundario")}` : null],
      ["TC primário / secundário", porNome.tc_primario ? `${vv("tc_primario")} / ${vv("tc_secundario")}` : null],
      ["Falhas de alimentação", porNome.falhas_alimentacao ? SGE.num(porNome.falhas_alimentacao.valor, 0) : null],
      ["Tempo de operação", porNome.tempo_operacao ? `${SGE.num(porNome.tempo_operacao.valor / 3600, 1)} h` : null],
      ["Hora do servidor", SGE.dataHora(det.hora_servidor)], ["Fuso de exibição", "America/Araguaina"]]);
  }

  async function atualizar(dlg) {
    try {
      const [r, det] = await Promise.all([SGE.get(`/api/dispositivos/${atualId}/atual`), SGE.get(`/api/dispositivos/${atualId}/detalhe`)]);
      const porNome = Object.fromEntries(r.valores.map(v => [v.grandeza, v]));
      dlg.querySelector(".pme-titulo").textContent = `${det.nome} · ${det.modelo}${det.local ? " · " + det.local : ""}`;
      const e = det.estado || {};
      dlg.querySelector(".pme-estado").innerHTML = `${SGE.selo(e.online)} <span>última leitura ok: ${SGE.dataHora(e.ultima_ok)}</span>`;
      dlg.querySelector(".pme-hora").textContent = `Hora do servidor: ${SGE.dataHora(det.hora_servidor)}`;
      dlg.classList.toggle("offline", e.online === false);
      preencher(dlg.querySelector(".pme-corpo"), porNome, det);
    } catch (err) { console.error(err); }
  }

  function mostrarAba(dlg, aba) {
    abaAtual = aba;
    dlg.querySelectorAll(".pme-abas button").forEach(b => b.classList.toggle("ativa", b.dataset.aba === aba));
    const corpo = dlg.querySelector(".pme-corpo");
    corpo.innerHTML = "";
    corpo.appendChild(CONSTRUTORES[aba]());
    atualizar(dlg);
  }

  function garantirDialogo() {
    let dlg = document.getElementById("pme-medidor");
    if (dlg) return dlg;
    dlg = document.createElement("dialog");
    dlg.id = "pme-medidor"; dlg.className = "pme";
    dlg.innerHTML = `<div class="pme-cabecalho"><h2 class="pme-titulo">—</h2><div class="pme-estado"></div>
        <button class="pme-fechar" aria-label="Fechar">✕</button></div>
      <nav class="pme-abas">${ABAS.map(([id, nome]) => `<button data-aba="${id}">${nome}</button>`).join("")}</nav>
      <div class="pme-corpo"></div><div class="pme-hora"></div>`;
    document.body.appendChild(dlg);
    dlg.querySelector(".pme-fechar").onclick = () => dlg.close();
    dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });
    dlg.addEventListener("close", () => clearInterval(timer));
    dlg.querySelectorAll(".pme-abas button").forEach(b => b.onclick = () => mostrarAba(dlg, b.dataset.aba));
    return dlg;
  }

  function abrir(dispositivoId, aba = "va") {
    const dlg = garantirDialogo();
    atualId = dispositivoId;
    clearInterval(timer);
    if (!dlg.open) dlg.showModal();
    mostrarAba(dlg, aba);
    timer = setInterval(() => dlg.open && atualizar(dlg), 2000);
  }

  return { abrir };
})();
