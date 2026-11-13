# SGE Agronorte: Sistema de Gestão de Energia

Gestão de energia da planta de nutrição animal da Agronorte, no estilo Schneider PME, ABB Ability e Elipse.
Fase atual: **coleta Modbus de multimedidores, banco de dados e telas de tempo real**, com validação dos mapas em campo.
Os KPIs de consumo específico (kWh/t de ração) entram depois que os dados de campo forem validados. A tabela `producao` já está criada para eles.

As regras do projeto ficam em [CLAUDE.md](CLAUDE.md).

## Arquitetura

```
Medidores (RS-485) ── USB-RS485 / gateway TCP ──> coletor ──> SQLite (futuro: SQL Server) ──> API FastAPI ──> telas web
                                                    └── agregação 15 min (consumo pela diferença do totalizador)
```

| Pasta | Conteúdo |
|---|---|
| `coletor/` | mapa CSV → pontos, decodificador (4 word orders, INT64, FP 4Q), blocos, transporte **somente leitura**, serviço de coleta |
| `armazenamento/` | esquema SQLAlchemy, gravação (histórico só com INSERT), agregação de 15 min |
| `calculo/` | consumo por totalizador: reset, rollover, lacuna (funções puras) |
| `api/`, `web/` | API FastAPI e telas: Painel, Tendências, Energia 15 min, Comunicação |
| `ferramentas/` | `varrer_serial` (descobrir porta, baud e ID) e `validar_campo` (Excel para conferir com o display) |
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
# terminal 1: escravos simulados (ID 1 = WEG MMW02, ID 2 = Schneider EM3261) em 127.0.0.1:5020
.venv\Scripts\python -m tests.simulador --queda 120:45 --reset 600
# terminal 2: coletor (use --debug para ver os bytes TX/RX e os registradores decodificados)
.venv\Scripts\python -m coletor --config config\dispositivos.simulador.yaml
# terminal 3: telas em http://127.0.0.1:8000
.venv\Scripts\python -m api --config config\dispositivos.simulador.yaml
```

Opções do simulador: `--acelerar N` (totalizadores N vezes mais rápidos), `--queda INICIO:DURACAO` (fica sem responder),
`--reset T` (zera os totalizadores no instante T), `--estrito` (exceção 02 em endereço não mapeado), `--quadro rtu_over_tcp`.

## Fluxo principal (campo)

1. Copie `config/dispositivos.exemplo.yaml` para `config/local/dispositivos.yaml` e preencha porta COM, baud, paridade, ID e mapa.
2. Descubra a porta e confira a comunicação:
   ```powershell
   .venv\Scripts\python -m ferramentas.varrer_serial --listar
   .venv\Scripts\python -m ferramentas.varrer_serial --porta COM3 --mapa config\mapas\weg_mmw02.csv
   ```
3. Valide o mapa: gere a planilha, anote os valores do display e corrija escala ou word order no CSV. Marque `verificado = sim`.
   ```powershell
   .venv\Scripts\python -m ferramentas.validar_campo --config config\local\dispositivos.yaml --dispositivo MED_01
   ```
4. Inicie a coleta e as telas:
   ```powershell
   .venv\Scripts\python -m coletor --config config\local\dispositivos.yaml
   .venv\Scripts\python -m api --config config\local\dispositivos.yaml
   ```

Todas as ferramentas usam só funções Modbus de leitura (FC 01–04).

## Pendências de campo

- **WEG MMW02:** conferir o parâmetro "Formato" (Short/Long). Os totalizadores de 64 bits (reg 12008…) têm escala `A_VERIFICAR` e ficam fora da coleta até serem comparados com o reg 304.
- **Schneider EM3261:** confirmar a interface RS-485. Conferir a decodificação do FP de 4 quadrantes (`FLOAT32_4Q_PF`) contra a aba "Data Types" da Schneider.
- Baud rate, paridade e ID Modbus reais.
