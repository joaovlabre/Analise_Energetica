from pathlib import Path

import pytest

from coletor.blocos import dividir_bloco, montar_blocos
from coletor.mapa import ErroMapa, carregar_mapa

RAIZ = Path(__file__).resolve().parents[2]
MAPA_WEG = RAIZ / "config" / "mapas" / "weg_mmw02.csv"
MAPA_SCH = RAIZ / "config" / "mapas" / "schneider_gologic_em3261.csv"

CABECALHO = "grandeza,descricao,funcao,endereco,base,tipo,word_order,escala,unidade,grupo,verificado,obs\n"


def test_mapas_reais_carregam():
    weg = carregar_mapa(MAPA_WEG)
    sch = carregar_mapa(MAPA_SCH)
    assert len(weg) > 50 and len(sch) > 40


def test_base1_convertida_para_protocolo():
    sch = {p.grandeza: p for p in carregar_mapa(MAPA_SCH)}
    p = sch["energia_ativa_importada"]
    assert p.endereco_manual == 3304 and p.endereco == 3303
    assert p.tipo == "INT64" and p.n_registros == 4
    assert p.escala == pytest.approx(0.001) and p.unidade == "kWh"


def test_base0_mantida():
    weg = {p.grandeza: p for p in carregar_mapa(MAPA_WEG)}
    assert weg["tensao_an"].endereco == 4
    assert weg["tensao_an"].funcao == 4


def test_a_verificar_nao_utilizavel():
    weg = {p.grandeza: p for p in carregar_mapa(MAPA_WEG)}
    assert not weg["energia_ativa_importada_64"].utilizavel
    assert weg["energia_ativa_importada"].utilizavel


def test_unidade_vazia_e_adimensional():
    weg = {p.grandeza: p for p in carregar_mapa(MAPA_WEG)}
    assert weg["fp_total"].unidade == "" and weg["fp_total"].utilizavel


def _mapa(tmp_path, linhas):
    arq = tmp_path / "m.csv"
    arq.write_text(CABECALHO + "\n".join(linhas) + "\n", encoding="utf-8")
    return arq


def test_funcao_de_escrita_recusada(tmp_path):
    arq = _mapa(tmp_path, ["x,X,06,10,0,UINT16,ABCD,1,,status,nao,"])
    with pytest.raises(ErroMapa, match="somente leitura"):
        carregar_mapa(arq)


def test_sobreposicao_detectada(tmp_path):
    arq = _mapa(tmp_path, ["a,A,03,10,0,FLOAT32,ABCD,1,V,instantaneo,nao,", "b,B,03,11,0,FLOAT32,ABCD,1,V,instantaneo,nao,"])
    with pytest.raises(ErroMapa, match="sobrepõem"):
        carregar_mapa(arq)


def test_blocos_contiguos_e_limites():
    weg = [p for p in carregar_mapa(MAPA_WEG) if p.grupo == "instantaneo"]
    blocos = montar_blocos(weg, max_registros=60, max_buraco=6)
    # todos os pontos aparecem exatamente uma vez
    assert sorted(p.grandeza for b in blocos for p in b.pontos) == sorted(p.grandeza for p in weg)
    for b in blocos:
        assert b.quantidade <= 60
        for p in b.pontos:
            assert b.inicio <= p.endereco and p.fim <= b.fim


def test_blocos_separam_por_buraco_grande():
    sch = [p for p in carregar_mapa(MAPA_SCH) if p.grupo == "energia"]
    blocos = montar_blocos(sch, max_registros=125, max_buraco=0)
    inicios = [b.inicio for b in blocos]
    assert 2699 in inicios and 3303 in inicios  # FLOAT32 2700 e INT64 3304 (base 1)


def test_dividir_bloco():
    weg = [p for p in carregar_mapa(MAPA_WEG) if p.grupo == "demanda"]
    (bloco,) = montar_blocos(weg, max_registros=60, max_buraco=0)
    partes = dividir_bloco(bloco)
    assert len(partes) == len(weg)
    assert all(b.quantidade == 2 for b in partes)
