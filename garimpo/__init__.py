"""
Garimpo de dominios .br no processo de liberacao do Registro.br.

Camadas, de dentro para fora. A dependencia so aponta para dentro:

    dominio/       regras puras. Nao importa nada das outras camadas.
                   situacao (bitmask), relevancia (nota), marcas (risco).

    adaptadores/   o mundo externo. registrobr (HTTP), repositorio (SQLite),
                   dicionarios (cache). Importam dominio, nunca casos.

    casos/         orquestracao. pool, varredura, instantaneo.
                   Recebem adaptadores por parametro, para serem testaveis.

    web/           apresentacao. servidor HTTP e consultas da interface.

    contexto.py    ponto de composicao: liga tudo e sabe onde ficam os
                   arquivos. E o unico lugar com esse conhecimento.

Os scripts na raiz (app.py, varrer.py, ...) sao entradas finas que chamam
daqui, mantidas para nao quebrar quem ja usava a linha de comando.
"""

__all__ = ["contexto", "dominio", "adaptadores", "casos"]
