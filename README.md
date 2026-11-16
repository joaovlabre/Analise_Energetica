# SGE Agronorte: Sistema de Gestão de Energia

Gestão de energia da planta de nutrição animal da Agronorte, no estilo Schneider PME, ABB Ability e Elipse.
Fase atual: **coleta Modbus de multimedidores, banco de dados e telas de tempo real**, com validação dos mapas em campo.
Os KPIs de consumo específico (kWh/t de ração) entram depois que os dados de campo forem validados. A tabela `producao` já está criada para eles.

As regras do projeto ficam em [CLAUDE.md](CLAUDE.md).

## Arquitetura

```
medidores em série (RS-485) ─> gateway RS485/TCP ─> switch ─> servidor: coletor ─> SQLite (futuro: SQL Server) ─> API ─> telas web
                                                                          └── agregação 15 min (consumo pela diferença do totalizador)
```
O servidor fala Modbus TCP com o gateway; cada medidor é endereçado pelo seu ID na rede RS-485.

| Pasta | Conteúdo |
|---|---|
| `coletor/` | mapa CSV → pontos, decodificador (4 word orders, INT64, FP 4Q), blocos, transporte **somente leitura**, serviço de coleta |
| `armazenamento/` | esquema SQLAlchemy, gravação (histórico só com INSERT), agregação de 15 min |
| `calculo/` | consumo por totalizador: reset, rollover, lacuna; KPIs de consumo específico (funções puras) |
| `api/`, `web/` | API FastAPI e telas: Painéis (Visão geral, Consumo por linha), Tendências, Relatórios (Energia 15 min), Comunicação |
| `ferramentas/` | `varrer_serial` (descobrir quais IDs respondem, via gateway TCP ou porta COM) e `validar_campo` (Excel para conferir com o display) |
| `tests/` | `unit/`, `integracao/` e `simulador/` (escravos Modbus TCP com injeção de falhas) |
| `config/` | `mapas/*.csv`, `dispositivos.simulador.yaml`, `dispositivos.exemplo.yaml`; `local/` fica fora do git |

## Instalação (Windows)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## Fluxo de testes (sem hardware)

```powershell
.venv\Scripts\python -m pytest                                    # todos os testes
# terminal 1: simula um gateway em 127.0.0.1:5020 com ID 1 = WEG MMW02 e ID 2 = Schneider EM3261 atrás dele
.venv\Scripts\python -m tests.simulador --queda 120:45 --reset 600
# terminal 2: coletor (use --debug para ver os bytes TX/RX e os registradores decodificados)
.venv\Scripts\python -m coletor --config config\dispositivos.simulador.yaml
# terminal 3: telas em http://127.0.0.1:8000
.venv\Scripts\python -m api --config config\dispositivos.simulador.yaml
```

Opções do simulador: `--acelerar N` (totalizadores N vezes mais rápidos), `--queda INICIO:DURACAO` (gateway inteiro sem responder),
`--queda-medidor ID:INICIO:DURACAO` (só um medidor fora; o gateway responde exceção 0B), `--sem-gateway`,
`--reset T` (zera os totalizadores no instante T), `--estrito` (exceção 02 em endereço não mapeado), `--quadro rtu_over_tcp`.

### Consumo específico por linha (dados simulados)

A relação linha → medidores fica em `config/hierarquia.simulador.yaml` (indicada em `hierarquia:` no YAML de dispositivos).
Para gerar um mês simulado (3 turnos todos os dias, demanda reduzida na ponta das 18h às 21h):
```powershell
.venv\Scripts\python -m ferramentas.simular_producao --config config\dispositivos.simulador.yaml --linha "Linha 1" --toneladas 3780 --mes 2026-10
```
A ferramenta só aceita bancos com `simulador` no nome. Ela grava leituras do totalizador a cada minuto e calcula
`energia_intervalo` a partir delas (flag `simulado`), além da produção diária em `producao` (origem `simulado`).
Para ver o resultado, abra **Painéis › Consumo por linha** (http://127.0.0.1:8000/paineis/consumo-linha). A tela mostra
energia, ração produzida, kWh/t, demanda máxima, a série diária e o perfil médio de demanda por horário.

## Fluxo principal (campo)

1. Configure o gateway (IP fixo, modo Modbus TCP ou transparente, baud e paridade iguais aos dos medidores).
2. Copie `config/dispositivos.exemplo.yaml` para `config/local/dispositivos.yaml` e preencha o IP do gateway e o ID e o mapa de cada medidor.
3. Teste a rede e descubra quais IDs respondem através do gateway:
   ```powershell
   ping 192.168.0.50
   .venv\Scripts\python -m ferramentas.varrer_serial --host 192.168.0.50 --ids 1-20 --mapa config\mapas\weg_mmw02.csv --verboso
   ```
4. Valide o mapa: gere a planilha, anote os valores do display e corrija escala ou word order no CSV. Marque `verificado = sim`.
   ```powershell
   .venv\Scripts\python -m ferramentas.validar_campo --config config\local\dispositivos.yaml --dispositivo MED_01
   ```
5. Inicie a coleta e as telas:
   ```powershell
   .venv\Scripts\python -m coletor --config config\local\dispositivos.yaml
   .venv\Scripts\python -m api --config config\local\dispositivos.yaml
   ```

O coletor e as ferramentas de campo usam só funções Modbus de leitura (FC 01–04). A escrita existe apenas na ponte de teste do Elipse (`tests/simulador/ponte_elipse.py`), que escreve no simulador.

## Pendências de campo

- **Gateway:** modelo, IP, modo (Modbus TCP ou transparente) e número máximo de conexões TCP simultâneas.
- **WEG MMW02:** conferir o parâmetro "Formato" (Short/Long). Os totalizadores de 64 bits (reg 12008…) têm escala `A_VERIFICAR` e ficam fora da coleta até serem comparados com o reg 304.
- **Schneider EM3261:** confirmar a interface RS-485. Conferir a decodificação do FP de 4 quadrantes (`FLOAT32_4Q_PF`) contra a aba "Data Types" da Schneider.
- Baud rate e paridade da rede RS-485 (configurados no gateway e nos medidores) e o ID Modbus de cada medidor.
