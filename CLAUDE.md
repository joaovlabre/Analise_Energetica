# CLAUDE.md — Sistema de Gestão de Energia (SGE)

> Nome provisório. Este arquivo orienta o Claude Code neste projeto. Itens marcados com **[A DEFINIR]** ainda precisam de decisão.

## 1. Visão geral

Software de gestão de energia e utilidades para plantas industriais, inspirado no Schneider Power Monitoring Expert (PME) e no ABB Ability Energy Manager.

Ele cobre **todos os vetores energéticos** da planta: energia elétrica, gás (GN/GLP), vapor, biomassa (lenha/cavaco), ar comprimido e água.

Objetivos:
1. **Coletar** leituras de campo de multimedidores, medidores de vazão (gás, vapor, ar, água), relés de proteção, CLPs e balanças.
2. **Exibir** em tela: valores instantâneos, tendências, alarmes e diagrama simplificado da distribuição de cada vetor.
3. **Armazenar** histórico confiável (séries temporais).
4. **Converter** todos os vetores para uma base energética comum, para comparar e somar.
5. **Gerar relatórios e KPIs** para **ratear os custos de energia e utilidades** por linha de produção, setor e equipamento.

Usuários: engenharia elétrica/manutenção (técnico), utilidades/caldeira, produção e gestão (relatórios e custos).

## 2. Regras invioláveis

- **Nunca inventar endereço de registrador, escala, tipo de dado ou fator de conversão.** Use sempre os mapas em `config/mapas/` e os fatores em `config/fatores_conversao.yaml`. Se um dado não estiver lá, pergunte ou consulte o manual do fabricante em `docs/manuais/`.
- **Consumo vem de totalizadores acumulados** (kWh, m³, kg), nunca da integração de grandezas instantâneas (kW, m³/h, kg/h). Consumo de um período = diferença entre leituras do totalizador. Integrar vazão só é aceito como último recurso, com qualidade `estimado`.
- **Preferir totalizadores de 64 bits (inteiros).** FLOAT32 tem só cerca de 7 dígitos significativos: com acumulados altos, o incremento de 15 min some no arredondamento. Use FLOAT32 apenas se o equipamento não oferecer alternativa.
- **Guardar a grandeza na unidade nativa** (m³, kg, t, kWh). A conversão para energia é feita no cálculo, com fator versionado, nunca na coleta.
- **Não apagar nem sobrescrever dados históricos.** Correções são registradas como novos dados com marcação (flag) e motivo.
- Credenciais, IPs de produção e dados de tarifa ficam em `.env` ou `config/local/`, **fora do git**.

## 3. Vetores energéticos e fontes de dados

| Vetor | Grandeza medida (unidade nativa) | Fontes típicas | Conversão para energia |
|---|---|---|---|
| Eletricidade | kWh, kvarh, kW | Multimedidores Modbus | Direta (kWh) |
| Gás natural / GLP | Volume corrigido (Nm³ ou m³ ref.) ou kg | Computador de vazão / corretor PTZ (Modbus), medidor com saída de pulso | Volume × PCI do contrato/nota fiscal |
| Vapor | Massa (kg ou t) | Medidor vortex/placa de orifício com compensação P e T (Modbus ou 4–20 mA via CLP) | Massa × (h vapor − h água de alimentação), entalpias pela IAPWS-IF97 |
| Biomassa (lenha/cavaco) | t ou m³ st | Balança, apontamento manual, nota fiscal | Massa × PCI em função da umidade |
| Ar comprimido | Nm³ | Medidor de vazão térmico (Modbus), kWh dos compressores | Indicador: kWh/Nm³ |
| Água | m³ | Hidrômetro com pulso, medidor eletromagnético | Sem conversão energética (custo e consumo) |

### Tipos de origem (`dispositivos.yaml`, campo `origem`)
- `modbus_rtu` / `modbus_tcp`: leitura direta pelo coletor.
- `pulso_clp`: contador de pulsos no CLP ou módulo de I/O remoto, lido via Modbus. Peso do pulso (ex.: 0,1 m³/pulso) fica na configuração do ponto.
- `analogico_clp`: 4–20 mA escalonado no CLP. **Exigir totalizador no CLP ou no instrumento**; não confiar em totalização no coletor.
- `manual`: lançamento pela interface (lenha recebida, leitura de hidrômetro), com usuário, data e justificativa.
- `importacao`: faturas e notas fiscais (Energisa, distribuidora de gás, fornecedor de lenha) em CSV/planilha.

### Regras específicas por vetor
- **Gás:** usar o volume **corrigido** do corretor ou computador de vazão. Volume não corrigido só com flag `estimado`. Registrar a condição de referência (20 °C e 1 atm ou outra do contrato). O PCI vem do contrato ou da nota da distribuidora e tem data de vigência.
- **Vapor:** medir massa com compensação de pressão e temperatura. Para energia, usar a biblioteca `iapws` (IF97). Precisa de pressão e temperatura do vapor e temperatura da água de alimentação: se não houver medição, usar valores de projeto configurados e marcar `estimado`. Diferenciar vapor saturado e superaquecido. Considerar retorno de condensado quando medido.
- **Biomassa:** o PCI depende fortemente da umidade. Guardar a umidade (medida ou de referência) junto com a massa. Converter m³ st para t com densidade configurável.
- **Ar comprimido:** a energia dele é a eletricidade dos compressores. O vetor serve para o indicador kWh/Nm³ e para ratear o custo do ar.

## 4. Equipamentos iniciais

| Equipamento | Fabricante | Interface | Mapa | Observações |
|---|---|---|---|---|
| MMW02 | WEG | RS-485 Modbus RTU | `config/mapas/weg_mmw02.csv` | Input registers (FC 04), base 0. Configurar o parâmetro "Formato" como **Short (16 bits)** ou adaptar o coletor (o padrão de fábrica é Long). Byte/word swap configuráveis, padrão "nenhum". Tabela de energia de 64 bits sem unidade no manual público: validar em campo. Tabela completa: pedir ao suporte WEG. |
| GoLogic EM3261 (GLEM3261) | Schneider | RS-485 Modbus RTU **[A CONFIRMAR]** | `config/mapas/schneider_gologic_em3261.csv` | Holding registers (FC 03). Lista da Schneider em numeração base 1: endereço no protocolo = registrador − 1. Big-endian (ABCD). **Não tem demanda nem THD**: a demanda é calculada pelo sistema a partir da energia. Usar o acumulador **permanente** (3304), que não é zerado pelo IHM. |

### Arquitetura de comunicação (decidida)
```
[medidores em série na rede RS-485] -> [gateway RS485/TCP] -> [switch] -> [servidor (coletor)]
```
- O servidor fala **Modbus TCP** com o gateway: barramento `tcp` (gateway convertendo TCP <-> RTU) ou `rtu_over_tcp` (gateway transparente). Um barramento por gateway; o `endereco_modbus` de cada medidor é o ID dele na rede RS-485 (Unit ID).
- Baud, paridade e bits do lado serial são configurados **no gateway** e iguais em todos os medidores da rede.
- O coletor mantém **uma conexão TCP por gateway** e faz um pedido por vez (a rede RS-485 é half-duplex). Ferramentas como `validar_campo` abrem outra conexão: confirmar quantas conexões simultâneas o gateway aceita.
- Exceções **0A/0B** (gateway sem caminho / medidor não respondeu) e **05/06** (ocupado) contam como **falha de comunicação** do medidor, nunca como ponto inválido. Gateway inteiro fora = todos os medidores dele sem comunicação.
- O conversor USB-RS485 (barramento `serial`) fica só como alternativa de bancada.

Futuros: medidores de gás e vapor, relés de proteção, CLPs (dado de produção e pulsos), balanças/totalizadores.

### Formato padrão do mapa de registradores (CSV)

```
grandeza,descricao,funcao,endereco,base,tipo,word_order,escala,unidade,grupo,verificado,obs
```
- `grandeza`: nome canônico (seção 8). O mesmo nome em todos os fabricantes, para que telas e cálculos não dependam do modelo.
- `funcao`: 01, 02, 03 ou 04.
- `endereco` + `base`: endereço como aparece no manual e se o manual numera a partir de 0 ou de 1. O coletor converte para o endereço do protocolo.
- `tipo`: INT16, UINT16, INT32, UINT32, INT64, UINT64, FLOAT32, FLOAT64, ou tipos especiais de fabricante (ex.: `FLOAT32_4Q_PF` da Schneider), cada um com decodificador próprio e teste.
- `word_order`: ABCD, CDAB, BADC, DCBA.
- `escala`: multiplicador para chegar à `unidade` canônica (ex.: W → kW = 0,001). `A_VERIFICAR` impede o uso do ponto até ser validado.
- `grupo`: instantaneo | energia | demanda | qualidade | status | config (define a taxa de coleta).
- `verificado`: `sim` só depois de conferir a leitura contra o display do equipamento em campo.

## 5. Arquitetura

```
[Equipamentos / CLPs] --Modbus--> [Coletor] --> [Banco de séries temporais] --> [API] --> [Interface web]
[Lançamentos manuais / faturas] ---------------------^          |
                                                                +--> [Motor de cálculo: conversão / rateio / KPIs] --> [Relatórios PDF/Excel]
```

Módulos:
- **coletor/**: polling por dispositivo, filas por barramento serial (um mestre por porta RS-485), reconexão, timeout, retentativas, marcação de qualidade. Agrupar leituras de registradores contíguos num único pedido.
- **entrada_manual/**: lançamentos manuais e importação de faturas e notas.
- **armazenamento/**: gravação das leituras e agregados (15 min, hora, dia, mês).
- **calculo/**: consumo por período, medidores virtuais, conversões energéticas (gás, vapor, biomassa), custo das utilidades produzidas na planta, rateio e KPIs.
- **api/**: endpoints para a interface e para relatórios.
- **web/**: telas (painel geral, por vetor, por dispositivo, tendências, alarmes, relatórios).
- **relatorios/**: geração agendada e sob demanda.

## 6. Stack

- Linguagem: Python 3.12+
- Modbus: `pymodbus` (RTU e TCP, assíncrono)
- Propriedades do vapor: `iapws`
- Banco: **SQLite** no protótipo (`dados/*.db`), migração prevista para **MS SQL Server**. Acesso só via SQLAlchemy 2 Core (`armazenamento/esquema.py`), sem SQL ou tipos exclusivos do SQLite. Datas em UTC ingênuo.
- API: **FastAPI** (`api/app.py`)
- Interface: **web própria** (Jinja2 + JS puro + Chart.js local em `web/static`, sem CDN: a planta pode ficar sem internet)
- Relatórios: **[A DEFINIR]** PDF; Excel com openpyxl (já usado na validação de campo)
- Simulador: servidor Modbus próprio em asyncio (`tests/simulador/servidor.py`), não o servidor do pymodbus (API em transição para a v4)
- Testes: `pytest` + simulador Modbus (`pymodbus` server) com dados sintéticos

## 7. Estrutura de pastas

```
/coletor
/entrada_manual
/armazenamento
/calculo
/api
/web
/relatorios
/config
    dispositivos.yaml        # equipamentos: origem, porta, ID, mapa, taxas, peso de pulso
    hierarquia.yaml          # árvore de distribuição por vetor + centros de custo
    tarifas.yaml             # tarifas de energia elétrica, preços de gás, lenha, água
    fatores_conversao.yaml   # PCI, densidades, condições de referência, com vigência
    /mapas                   # mapas de registradores por modelo
/tests
    /simulador               # escravos Modbus simulados
/docs
    /manuais                 # manuais dos fabricantes (PDF/XLS)
```

## 8. Regras de domínio

### Nomes canônicos de grandezas
Padrão: `<grandeza>[_<fase ou qualificador>]`, sem unidade no nome (a unidade fica no mapa e no banco). Exemplos:
- Elétricas: `tensao_an`, `tensao_ab`, `tensao_fn_media`, `corrente_a`, `corrente_n`, `potencia_ativa_total`, `fp_total`, `frequencia`, `energia_ativa_importada`, `energia_ativa_exportada`, `energia_reativa_importada`, `demanda_ativa_pico`, `thd_tensao_a`
- Fluidos: `vazao_volumetrica`, `vazao_volumetrica_corrigida`, `vazao_massica`, `volume_corrigido_acumulado`, `massa_acumulada`, `pressao`, `temperatura`
- Unidades canônicas: V, A, kW, kvar, kVA, kWh, kvarh, Hz, %, m³, Nm³, kg, t, bar(g), °C

### Coleta
- Taxas de coleta (configuráveis em `coleta.taxas`): instantâneos lidos a cada 2 s (tela, tabela `valor_atual`) e gravados no histórico 1×/min; totalizadores, demanda e qualidade 1 min; status 5 min; config 1 h.
- Todo valor gravado leva: timestamp (UTC), dispositivo, grandeza, valor, unidade e qualidade (`ok`, `timeout`, `fora_faixa`, `estimado`, `manual`).
- Fuso de exibição: America/Araguaina (Tocantins). Gravação sempre em UTC.
- Tratar **reset/rollover do totalizador** e **troca de medidor**: nunca gerar consumo negativo nem picos falsos.
- Lacunas de comunicação: o consumo do período é recuperado pela diferença do totalizador quando a comunicação volta. Registrar a lacuna.
- Validar faixas físicas (tensão, vazão, pressão) e marcar `fora_faixa` em vez de descartar.

### Intervalos e tarifação
- Intervalo de integração padrão: **15 min**, alinhado ao relógio (:00, :15, :30, :45), compatível com a medição da concessionária (Energisa TO).
- Postos tarifários (ponta / fora de ponta), feriados e bandeiras em `config/tarifas.yaml`. **[A DEFINIR]** horários e valores conforme o contrato.
- Custo elétrico = energia por posto × tarifa + rateio de demanda contratada/medida + encargos. **[A DEFINIR]** método de rateio da demanda.
- Gás, biomassa e água: preço unitário com vigência (R$/m³, R$/t). Conferir mensalmente contra as faturas e notas.

### Base energética comum
- Consolidação em **kWh** (ou GJ) e, para relatórios institucionais, em **tep** usando os fatores do Balanço Energético Nacional (BEN). **[A DEFINIR]** unidade principal.
- Todo fator de conversão em `fatores_conversao.yaml` tem fonte e data de vigência. Recalcular o histórico só por pedido explícito, gerando nova versão.
- **[OPCIONAL]** emissões de CO₂e por vetor, com fatores configuráveis.

### Utilidades produzidas na planta (rateio em cascata)
- Vapor e ar comprimido são **energia secundária**: o custo deles vem dos insumos.
  - Custo do vapor (R$/t) = (combustível + eletricidade dos auxiliares da caldeira + água/tratamento) ÷ vapor produzido.
  - Custo do ar (R$/Nm³) = eletricidade dos compressores ÷ ar produzido.
- Esse custo unitário é repassado aos consumidores pelo consumo medido de vapor ou ar. Sem medição por consumidor, usar critério configurável e deixar explícito no relatório.
- Indicadores de eficiência: rendimento da caldeira (energia no vapor ÷ energia do combustível), kg vapor/kg combustível, kWh/Nm³ dos compressores.

### Hierarquia e rateio
- `hierarquia.yaml` monta uma árvore **por vetor** e liga cada medidor a setor, linha ou equipamento e a um centro de custo.
- **Medidores virtuais**: soma ou diferença de medidores reais (ex.: geral − soma dos setores = perdas + não medido).
- O consumo **não medido** é exibido explicitamente e rateado por critério configurável (proporcional ao medido, por área, fixo). Nunca escondê-lo.
- Validação: a soma dos filhos deve fechar com o pai dentro de uma tolerância configurável. Gerar alerta quando não fechar.

### KPIs iniciais
- Consumo e custo (R$) por vetor, centro de custo, período e posto tarifário
- **Consumo específico**: kWh/t, kg vapor/t, m³ gás/t, energia total (kWh eq.)/t e R$/t por linha e por produto (requer dado de produção)
- Custo unitário das utilidades (R$/t vapor, R$/Nm³ ar) e eficiência da caldeira e dos compressores
- Demanda máxima, fator de carga e fator de potência por setor
- Consumo fora de produção (base load) e consumo em horário de ponta
- Ranking dos maiores consumidores

## 9. Convenções de código

- Interface, relatórios, mensagens ao usuário, código e nomes de variáveis em **português do Brasil** (nomes de identificadores sem acento).
- Unidades sempre explícitas: no mapa, no banco e nas variáveis de cálculo (`energia_kwh`, `vapor_t`).
- Configuração em YAML/CSV. Nada de endereço, IP, ID, fator ou preço fixo no código.
- Toda nova grandeza ou dispositivo entra primeiro no mapa/configuração, depois no código.
- Funções de cálculo (conversão, rateio, custo, KPI) são puras e cobertas por testes com casos conhecidos, incluindo conferência das entalpias do vapor contra tabela de referência.

## 10. Comandos

Ambiente: `python -m venv .venv` e `.venv\Scripts\pip install -r requirements.txt` (Python 3.12).

**Fluxo principal (campo):**
```
python -m coletor --config config/local/dispositivos.yaml     # coleta (Ctrl+C para parar)
python -m api --config config/local/dispositivos.yaml         # telas em http://127.0.0.1:8000
```
**Fluxo de testes / depuração:**
```
pytest                                                         # unitários + integração (sem hardware)
python -m tests.simulador [--acelerar 60] [--queda 120:45] [--reset 300] [--estrito]
python -m coletor --config config/dispositivos.simulador.yaml --debug   # TX/RX em hex + valores decodificados
python -m api --config config/dispositivos.simulador.yaml
python -m ferramentas.varrer_serial --listar | --porta COM3 --mapa config/mapas/weg_mmw02.csv
python -m ferramentas.validar_campo --config <yaml> --dispositivo <nome>   # Excel para conferir com o display
```
`config/local/` (fora do git) guarda a configuração real; o modelo é `config/dispositivos.exemplo.yaml`.

## 11. Fluxo de trabalho com o Claude

- Para funcionalidades grandes, apresentar o plano antes de implementar.
- Ao adicionar um equipamento: ler o manual em `docs/manuais/`, gerar o mapa CSV com `verificado = nao`, mostrar o mapa ao usuário para conferência e só então escrever o código.
- Testar contra o simulador antes de qualquer teste em campo.
- Antes de rodar algo que acesse a rede industrial ou a porta serial real, avisar o usuário.
- No primeiro teste em campo de cada modelo, gerar um relatório com as leituras ao lado de colunas vazias para o usuário anotar os valores do display. Ao conferir, marcar `verificado = sim` e corrigir escala/word order no mapa.

## 12. Roadmap

1. Coletor lendo MMW02 e EM3261 e gravando no banco (protótipo); validação dos mapas em campo
2. Tela de tempo real e tendências
3. Hierarquia, medidores virtuais e energia por intervalo de 15 min
4. Tarifas, custos e rateio elétrico
5. Integração do dado de produção (CLP/balança/ERP) e KPIs de consumo específico
6. Vapor, gás e biomassa: medidores, lançamento manual, conversões e custo do vapor em cascata
7. Ar comprimido e água
8. Relatórios agendados (diário, mensal) e alarmes
9. Novos equipamentos (relés, outros medidores)
