#!/usr/bin/env bash
# Regera o instantaneo estatico e publica no Cloudflare.
#
#   ./publicar.sh
#
# Precisa estar logado (npx wrangler login) na conta dona do Worker
# "liberados" (wrangler.jsonc). Outro endereco para conferir:
#   SITE_URL=https://liberados.<conta>.workers.dev ./publicar.sh
#
# Nada de pessoal vai junto, so dado de dominio.
set -euo pipefail
cd "$(dirname "$0")"

URL="${SITE_URL:-https://liberados.com.br}"

python3 exportar_site.py
# versao exata, a mesma do .github/workflows/garimpo.yml (um teste confere):
# 4.134.0, a mais nova em 18/09/2026. Subir a versao e mudar os dois.
npx --yes wrangler@4.134.0 deploy

# "deploy ok" do CLI nao quer dizer site no ar. Em 10/09/2026, ainda no
# Vercel, um deploy que falhou criou uma implantacao vazia que tomou o
# endereco de producao, e nada avisou. A pergunta que importa e o que o
# visitante recebe.
echo
echo "conferindo o que esta no ar..."
codigo=$(curl -sL -o /tmp/liberados-publicado.html -w "%{http_code}" \
         --max-time 30 "$URL/" || echo 000)
if [ "$codigo" != "200" ]; then
  echo "ERRO: $URL respondeu $codigo, nao 200." >&2
  echo "Confira 'npx wrangler deployments list'." >&2
  exit 1
fi
if ! grep -q 'href="/insights/"' /tmp/liberados-publicado.html; then
  echo "ERRO: $URL respondeu 200 mas sem o conteudo esperado." >&2
  exit 1
fi

echo "publicado em $URL"
