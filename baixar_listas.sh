#!/usr/bin/env bash
#
# Baixa as listas publicas do Registro.br e converte para UTF-8.
#
#   ./baixar_listas.sh [diretorio_de_saida]
#
# Gera dois arquivos:
#   liberacao.txt   - todos os nomes da rodada atual do processo de liberacao
#   competitivo.txt - nomes que estao em processo competitivo (leilao)
#
# Os arquivos vem em ISO-8859-1 e com linhas de cabecalho comecando com '#'.
# O cabecalho e mantido: ele traz as datas de inicio e fim da rodada, que e a
# informacao mais importante para saber ate quando da para se candidatar.

set -euo pipefail

DEST="${1:-.}"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

mkdir -p "$DEST"

baixar() {
    local url="$1" destino="$2"
    echo "baixando $url" >&2
    curl -fsS -A "$UA" "$url" | iconv -f ISO-8859-1 -t UTF-8 > "$destino"
    echo "  $(grep -vc '^#' "$destino") nomes -> $destino" >&2
}

baixar https://registro.br/dominio/lista-processo-liberacao.txt   "$DEST/liberacao.txt"
baixar https://registro.br/dominio/lista-processo-competitivo.txt "$DEST/competitivo.txt"

echo >&2
head -3 "$DEST/liberacao.txt" >&2
