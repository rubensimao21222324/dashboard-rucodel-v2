"""Proteção LEITURA / ESCRITA da instância DEV (Dashboard Rucodel 2.0).

A instância DEV liga-se aos MESMOS serviços reais da Rucodel que a produção, para se ver tudo com dados verdadeiros.
Para não se mexer neles sem querer, todos os pedidos ao dashboard da produção (api.rucodel.pt) passam por aqui:

  - LEITURA (sempre o modo ao arrancar): só passam os pedidos que LEEM (login, lista de departamentos,
    serviços de um setor, fotografias). Tudo o resto é recusado ANTES de sair do PC: + / −, Iniciar, Terminar
    e qualquer caminho desconhecido.
  - ESCRITA: tudo passa, como na produção. Só fica ativo quando alguém o liga no painel, e volta a LEITURA
    sempre que a Central é reiniciada.

O site de gestão (gestao.rucodel.pt) já é só de leitura por construção (lista ALLOWED_GET em gestao_rucodel.py).
"""
from __future__ import annotations
from datetime import datetime
import re
import threading

LEITURA, ESCRITA = 'leitura', 'escrita'

# Pedidos ao api.rucodel.pt que só leem. Em LEITURA, só estes saem do PC (lista fechada: o que não está aqui é recusado).
_LEITURAS = [
    ('GET', re.compile(r'^/auth/departamentos-lista$')),
    ('GET', re.compile(r'^/auth/departamento/\d+$')),
    ('POST', re.compile(r'^/auth/servico-imagens-batch$')),  # POST, mas só devolve fotografias
]

_lock = threading.Lock()
_estado = {'modo': LEITURA, 'desde': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'bloqueados': 0}


class ModoLeitura(ValueError):
    """Pedido de escrita recusado porque o painel está em LEITURA (ValueError: a mensagem chega ao ecrã)."""


def estado() -> dict:
    with _lock:
        return dict(_estado)


def modo() -> str:
    with _lock:
        return _estado['modo']


def escrita_ligada() -> bool:
    return modo() == ESCRITA


def definir(novo: str) -> dict:
    novo = str(novo or '').strip().lower()
    if novo not in (LEITURA, ESCRITA):
        raise ValueError('Modo desconhecido (usa «leitura» ou «escrita»).')
    with _lock:
        if _estado['modo'] != novo:
            _estado.update(modo=novo, desde=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return dict(_estado)


def e_leitura(metodo: str, caminho: str) -> bool:
    metodo = (metodo or 'GET').upper()
    return any(metodo == m and padrao.match(caminho or '') for m, padrao in _LEITURAS)


MENSAGEM = ('Modo LEITURA: esta ação mexia no software de produção e foi bloqueada. '
            'Para a fazer, muda para ESCRITA no topo do painel.')


def verificar(metodo: str, caminho: str) -> None:
    """Chamar antes de cada pedido ao api.rucodel.pt. Em LEITURA, recusa tudo o que não seja uma leitura conhecida."""
    if escrita_ligada() or e_leitura(metodo, caminho):
        return
    with _lock:
        _estado['bloqueados'] += 1
    raise ModoLeitura(MENSAGEM)


def exigir_escrita() -> None:
    """Para recusar logo à entrada uma ação de escrita (antes de ler o setor ou validar seja o que for)."""
    if not escrita_ligada():
        with _lock:
            _estado['bloqueados'] += 1
        raise ModoLeitura(MENSAGEM)
