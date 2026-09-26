/*
 * A ficha "quando esse dominio volta?" (/quando-volta/), 14/09/2026.
 *
 * Serve o ano todo, nao so na rodada: quem tem um dominio congelado quer
 * saber quanto tempo tem, e quem quer um nome que ja tem dono quer saber
 * quando ele pode voltar. As duas buscas aparecem no autocompletar do Google
 * (docs/perguntas-do-publico.md, secao de 13/09/2026).
 *
 * De onde vem cada coisa:
 *   - a situacao: RDAP do Registro.br, consultado DAQUI, do navegador de
 *     quem olha (Disputa.consultar, em disputa.js). Nada passa pelo servidor
 *     do site, e a consulta conta na cota do proprio IP (limitacoes A6, R4).
 *   - as datas: a lista de aberturas gravada no build (p-calendario). A
 *     regra mora em garimpo/dominio/calendario.py; aqui so se escolhe.
 *   - a previsao de volta: vencimento + 5 meses, e a rodada seguinte como
 *     segunda chance (limitacao S14). Sempre janela, nunca data.
 *   - as passagens: o indice das listas guardadas, uma fatia por hash do
 *     nome (garimpo/dominio/passagens.py; o teste confere o mesmo hash).
 *   - nome travado (15/09/2026): volta na rodada seguinte, e as rodadas
 *     seguidas no indice dizem se ela e normal ou leilao (sequencia(), tres
 *     travas, limitacao S13). Mes sem lista guardada vira "incerto", nunca
 *     palpite.
 *   - quantos disputaram antes: /dados/historico/disputas.json, contagem
 *     propria desde set/2026 (garimpo/casos/arquivo_das_rodadas.py). So
 *     numero: quem disputou continua sendo o botao "Ver quem disputa", ao
 *     vivo, e so enquanto o RDAP mostrar os tickets.
 *
 * Da entidade do RDAP sai so o nome do titular, que a busca do Registro.br
 * mostra a qualquer um. Documento, endereco, e-mail e legalRepresentative
 * nunca (AGENTS.md).
 */
(function () {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const FUSO = 'America/Sao_Paulo';
  const PASSAGENS = '/dados/historico/passagens/';
  // "este dominio ja teve site?" (18/09/2026): montado na maquina local por
  // arquivar_wayback.py, no mesmo esquema de fatias das passagens
  const ARQUIVO = '/dados/historico/arquivo/';
  const DISPUTAS = '/dados/historico/disputas.json';
  const BUSCA = 'https://registro.br/busca-dominio?fqdn=';
  const PAINEL_LEILAO = 'https://registro.br/painel/dominios/processo-competitivo/';
  const PAUSA = 2500;              // entre consultas, como o "quem disputa"
  const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho',
    'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (n) => String(n).padStart(2, '0');

  let cal = {};
  try { cal = JSON.parse(($('#p-calendario') || {}).textContent || '{}'); } catch (e) { cal = {}; }
  const aberturas = cal.aberturas || [];
  const eventos = new Map();       // id do botao -> evento da agenda
  let ultimaConsulta = 0;
  let ocupado = false;

  // ------------------------------------------------------------ datas

  function isoBrasilia(d) {
    // en-CA formata como AAAA-MM-DD
    return new Intl.DateTimeFormat('en-CA', { timeZone: FUSO, year: 'numeric',
      month: '2-digit', day: '2-digit' }).format(d);
  }

  const dia = (d) => d.toLocaleDateString('pt-BR', { timeZone: FUSO,
    day: '2-digit', month: '2-digit', year: 'numeric' });
  const diaHora = (d) => d.toLocaleString('pt-BR', { timeZone: FUSO, day: '2-digit',
    month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  const mesDe = (d) => { const [a, m] = isoBrasilia(d).split('-'); return `${MESES[+m - 1]} de ${a}`; };
  const abreEm = (iso) => new Date(`${iso}T${pad(cal.hora_abertura || 15)}:00:00-03:00`);
  const listaDe = (abre) => new Date(abre.getTime() - (cal.dias_lista_antes || 2) * 86400000);
  // o mes (AAAA-MM) de uma rodada pelo fim dela: abre na segunda quarta e dura 7 dias
  const mesDaRodada = (fim) => isoBrasilia(fim ? new Date(fim.getTime() - 7 * 86400000) : new Date()).slice(0, 7);

  function somarMeses(ano, mes, n) {
    const total = ano * 12 + (mes - 1) + n;
    return [Math.floor(total / 12), (total % 12) + 1];
  }

  function aberturaDoMes(ano, mes) {
    const iso = aberturas.find((a) => a.startsWith(`${ano}-${pad(mes)}-`));
    return iso ? abreEm(iso) : null;
  }

  function proximaAbertura(depois) {
    const iso = aberturas.find((a) => abreEm(a) > depois);
    return iso ? abreEm(iso) : null;
  }

  /** As duas rodadas em que o nome deve aparecer se nao for renovado. */
  function previsao(vence) {
    const [ano, mes] = isoBrasilia(vence).split('-').map(Number);
    const n = cal.meses_ate_a_lista || 5;
    return {
      provavel: aberturaDoMes(...somarMeses(ano, mes, n)),
      seguinte: aberturaDoMes(...somarMeses(ano, mes, n + 1)),
    };
  }

  // ------------------------------------------------------------ nome

  function normalizar(bruto) {
    let s = String(bruto || '').trim().toLowerCase();
    if (!s) return { erro: '' };
    s = s.replace(/^[a-z][a-z0-9+.-]*:\/\//, '').replace(/^[^@/]*@/, '');
    s = s.split(/[/?#\s]/)[0].replace(/^www\./, '').replace(/\.+$/, '');
    if (!s) return { erro: '' };
    if (!s.includes('.')) s += '.com.br';
    const exibe = s;
    try {
      s = new URL('http://' + s).hostname;      // acento vira xn--, como no registro
    } catch (e) {
      return { erro: 'Esse nome tem um caractere que não vale em domínio.' };
    }
    if (!s.endsWith('.br')) {
      return { erro: 'A ficha consulta só domínios .br. Para .com e outros, use o registrador deles.' };
    }
    if (!/^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+br$/.test(s)) {
      return { erro: 'Esse não parece um domínio .br válido.' };
    }
    // com acento, a tela mostra o que a pessoa digitou; a consulta usa o xn--
    return { nome: s, exibe: exibe !== s && /[^\x00-\x7f]/.test(exibe) ? exibe : s };
  }

  /**
   * Nome que a regra do .br nao aceita: de 2 a 26 caracteres, nao so
   * numeros (Resolucao CGI.br 008/2008, art. 3o). O RDAP responde 404 para
   * a.com.br como para um nome livre, mas o Registro.br chama de "Dominio
   * invalido" e ninguem registra (limitacao R11). Os cinco .com.br de uma
   * letra que existem respondem 200 e nem chegam aqui.
   */
  function foraDaRegra(exibe) {
    const rotulo = [...String(exibe || '').split('.')[0]];
    return rotulo.length < 2 || rotulo.length > 26 || /^[0-9]+$/.test(rotulo.join(''));
  }

  // ------------------------------------------------------------ leitura

  function classificar(res, exibe) {
    if (res.status === 404) return { tipo: foraDaRegra(exibe) ? 'invalido' : 'livre' };
    const j = res.json || {};
    const status = (j.status || []).map((s) => String(s).toLowerCase());
    const ev = {};
    for (const e of j.events || []) ev[e.eventAction] = e.eventDate;
    const tickets = (j.publicIds || []).filter((p) => p.type === 'ticket').length;
    // Nome que travou e espera a proxima rodada (status 5 do ISAVAIL): 200
    // com objeto vazio, sem status nem tickets (16/09/2026, limitacao S12).
    if (/^release-process-waiting/.test(res.recurso || '')) return { tipo: 'travado' };
    // Leilao: `-running` durante a rodada, `-closed` depois que ela fecha e
    // as ofertas seguem ate o dia seguinte. Nos dois, `date=` e o fim da rodada.
    const processo = /^(competitive-)?release-process-(running|closed)(?:;date=([^;]+))?/.exec(res.recurso || '');
    if (processo && (processo[1] || processo[2] === 'running')) {
      const fim = processo[3] ? new Date(processo[3]) : null;
      return { tipo: processo[1] ? 'leilao' : 'rodada', fim: fim && !isNaN(fim) ? fim : null, tickets };
    }
    if (status.some((s) => s.includes('court order') || s.includes('inactive cg'))) {
      return { tipo: 'decisao' };
    }
    const entidade = (j.entities || []).find((e) => (e.roles || []).includes('registrant'));
    const campos = ((entidade || {}).vcardArray || [])[1] || [];
    const fn = campos.find((c) => Array.isArray(c) && c[0] === 'fn');
    const data = (s) => { const d = s ? new Date(s) : null; return d && !isNaN(d) ? d : null; };
    const base = {
      titular: fn ? String(fn[3] || '') : '',
      registro: data(ev.registration),
      vence: data(ev.expiration),
      alterado: data(ev['last changed']),
      recurso: res.recurso || '',
    };
    if (!base.vence && status.includes('pending create')) return { tipo: 'pendente', ...base };
    if (status.includes('inactive')) return { tipo: 'congelado', ...base };
    if (base.vence && base.vence < new Date()) return { tipo: 'vencido', ...base };
    return { tipo: 'registrado', ...base };
  }

  // ------------------------------------------------------------ desenho

  let contador = 0;
  function botaoAgenda(rotulo, evento, primario = true) {
    const id = `agenda-${++contador}`;
    eventos.set(id, evento);
    return `<button type="button"${primario ? ' class="primario"' : ''} data-agenda="${id}">${esc(rotulo)}</button>`;
  }

  const link = (href, rotulo, primario) =>
    `<a class="botao-link${primario ? ' primario' : ''}" href="${esc(href)}" target="_blank" rel="noopener">${esc(rotulo)}</a>`;

  /**
   * O evento do dia em que sai a lista. `travou`: o nome travou numa rodada
   * e volta na seguinte com certeza (a regra oficial: "fica aguardando o
   * proximo processo"); sem ele, a data e previsao pelo vencimento.
   */
  function lembreteDeVolta(nome, abre, seguinte, travou = false) {
    const lista = listaDe(abre);
    const inicio = new Date(`${isoBrasilia(lista)}T09:00:00-03:00`);
    // .ics servido existe para as proximas 24 rodadas (lembretes.escrever_rodadas)
    const limite = new Date(Date.now() + 23 * 30 * 86400000);
    const ficha = `${location.origin}/quando-volta/?d=${encodeURIComponent(nome)}`;
    return {
      cabecalho: `Lembrar de conferir ${nome}`,
      texto: `No dia em que sai a lista da rodada de ${mesDe(abre)}, ${dia(lista)}, às 9h.`,
      nota: 'No iPhone, o arquivo traz a data da rodada; o nome do domínio vai no evento do Google e do Outlook. '
          + (travou ? 'A data da lista segue a regra do calendário; o Registro.br pode mudá-la por feriado.'
            : 'A data é estimativa pelo histórico, não aviso do Registro.br.'),
      titulo: travou ? `${nome} volta hoje na lista da rodada` : `Ver se ${nome} voltou ao mercado`,
      detalhes: travou
        ? `${nome} travou e volta na rodada de liberação de ${mesDe(abre)}: a lista sai hoje e a rodada `
          + `abre em ${dia(abre)} às 15h. Os pedidos da rodada anterior foram cancelados, então quem quiser `
          + `o nome precisa se candidatar de novo. Veja se ele vai como rodada normal ou leilão: ${ficha}`
        : `Pela previsão do Liberados, ${nome} pode estar hoje na lista da rodada de liberação `
          + `de ${mesDe(abre)} (a rodada abre em ${dia(abre)} às 15h).`
          + (seguinte ? ` Se não estiver, a próxima chance é a de ${mesDe(seguinte)}.` : ''),
      inicio,
      fim: new Date(inicio.getTime() + 30 * 60000),
      url: ficha,
      uid: `volta-${nome}-${isoBrasilia(abre)}`,
      servido: abre < limite ? `/lembretes/rodadas/${isoBrasilia(abre)}.ics` : null,
      arquivo: `volta-${nome}.ics`,
    };
  }

  function textoDaPrevisao(nome, vence, jaTemDono) {
    const { provavel, seguinte } = previsao(vence);
    const agora = new Date();
    if (!provavel) {
      return { html: `<p>Vence só em ${esc(isoBrasilia(vence).slice(0, 4))}, longe demais para prever a rodada.</p>` };
    }
    const condicao = jaTemDono ? 'Se não for renovado' : 'Se não for pago';
    if (provavel > agora) {
      return {
        html: `<p class="ficha-previsao">${condicao}, deve voltar ao mercado na <strong>rodada de `
            + `${esc(mesDe(provavel))}</strong>: a lista sai em ${esc(dia(listaDe(provavel)))} e a rodada `
            + `abre em ${esc(dia(provavel))}, às 15h.`
            + (seguinte ? ` Se atrasar, na de ${esc(mesDe(seguinte))}.` : '') + '</p>',
        evento: lembreteDeVolta(nome, provavel, seguinte),
      };
    }
    if (seguinte && seguinte > agora) {
      return {
        html: `<p class="ficha-previsao">Pelo histórico, a volta mais provável era a rodada de `
            + `${esc(mesDe(provavel))}, que já passou. A próxima chance é a <strong>rodada de `
            + `${esc(mesDe(seguinte))}</strong>, com a lista em ${esc(dia(listaDe(seguinte)))}.</p>`,
        evento: lembreteDeVolta(nome, seguinte, null),
      };
    }
    return {
      html: `<p class="ficha-previsao">Pelo histórico, ele já deveria ter voltado (rodadas de `
          + `${esc(mesDe(provavel))} e ${esc(seguinte ? mesDe(seguinte) : 'depois')}). Pode ter sido `
          + 'pago no meio do caminho, reservado pelo Registro.br, ou o prazo foi outro.</p>',
    };
  }

  function desenhar(nome, f, exibe, alvo) {
    const agora = new Date();
    const busca = BUSCA + encodeURIComponent(nome);
    const nomeHtml = `<code>${esc(exibe || nome)}</code>`;
    const nota = '<p class="ficha-nota">Estimativa pelo histórico das listas, não data do Registro.br. '
      + '<a href="/quando-volta/#quanto-tempo">Como calculamos</a>.</p>';
    let titulo = '', corpo = '', acoes = '';
    // o que o bloco do historico precisa saber: o mes da rodada em que o nome
    // esta (ou travou), se ele volta na proxima e quando, e se a contagem da
    // rodada de agora ja aparece ao vivo no cartao
    const ctx = { mes: null, travou: false, proxima: null, aoVivo: false, invalido: false };

    if (f.tipo === 'invalido') {
      // nome fora da regra nao tem historico de rodadas a contar
      ctx.invalido = true;
      const umaLetra = [...String(exibe || nome).split('.')[0]].length === 1;
      titulo = `${nomeHtml} não pode ser registrado`;
      corpo = '<p>O nome de um domínio .br tem de 2 a 26 caracteres e não pode ser só de números. '
        + 'Para esse, o Registro.br responde "Domínio inválido": não é livre, e ninguém consegue registrar.</p>'
        + (umaLetra ? '<p>Os únicos .com.br de uma letra são de antes da regra: '
          + '<a href="/insights/dominios-de-uma-letra/">o que aconteceu com as 26 letras</a>.</p>' : '');
    } else if (f.tipo === 'livre') {
      titulo = `${nomeHtml} está livre agora`;
      corpo = '<p>Ninguém tem esse nome registrado. Quem registrar primeiro leva, pela anuidade '
        + 'normal (R$ 40 por ano no Registro.br).</p>'
        + '<p class="ficha-nota">Alguns nomes são reservados (palavras proibidas, marcas conhecidas) '
        + 'e o Registro.br recusa na hora; a busca de lá confirma.</p>';
      acoes = link(busca, 'Registrar no Registro.br', true);
    } else if (f.tipo === 'rodada') {
      const proxima = proximaAbertura(f.fim || agora);
      Object.assign(ctx, { mes: mesDaRodada(f.fim), proxima, aoVivo: true });
      titulo = `${nomeHtml} está na rodada de liberação`;
      corpo = `<p>Candidaturas de graça${f.fim ? ` até <strong>${esc(diaHora(f.fim))}</strong>, horário de Brasília` : ' até o fim da rodada'}. `
        + 'Se só uma pessoa pedir, ela leva pela anuidade.</p>';
      if (f.tickets >= 2) {
        // Dois visiveis e a trava e certa: candidatura nao se cancela (S3), e
        // os pedidos de nome travado sao cancelados, nao carregados (S12).
        ctx.travou = true;
        titulo = `${nomeHtml} travou nesta rodada`;
        corpo = `<p class="ficha-trava">A rodada fica aberta${f.fim ? ` até ${esc(diaHora(f.fim))}, horário de Brasília` : ''}, mas `
          + `já tem <strong>${f.tickets} candidatos visíveis</strong>. Com dois ou mais, ninguém leva, e `
          + 'nenhum deles consegue desistir: o Registro.br não tem como cancelar candidatura. Pedir agora '
          + 'não adianta: ocupa uma das suas vagas até a rodada fechar, e todos os pedidos são cancelados '
          + 'quando o nome trava.</p>'
          + (proxima ? `<p class="ficha-previsao ficha-volta">O nome volta na <strong>rodada de ${esc(mesDe(proxima))}</strong>: `
            + `a lista sai em ${esc(dia(listaDe(proxima)))} e a rodada abre em ${esc(dia(proxima))}, às 15h. `
            + 'Quem quiser o nome se candidata de novo lá.</p>' : '');
        if (proxima) acoes += botaoAgenda('Lembrar quando voltar', lembreteDeVolta(nome, proxima, null, true));
        acoes += `<button type="button" data-disputa="${esc(nome)}">Ver quem disputa</button>`
          + link(busca, 'Ver no Registro.br', false);
      } else {
        corpo += '<p>Nenhum candidato visível. Pode haver um: o Registro.br esconde o candidato '
          + 'único (<a href="/insights/o-candidato-que-nao-aparece/">por quê</a>).</p>';
        acoes = link(busca, 'Candidatar-se no Registro.br', true);
      }
      if (!ctx.travou && f.fim && f.fim > agora) {
        acoes += botaoAgenda('Lembrar do fim da rodada', {
          cabecalho: `Lembrar do fim da rodada para ${nome}`,
          texto: `A rodada fecha em ${diaHora(f.fim)}, horário de Brasília. O evento ocupa a última meia hora.`,
          titulo: `Último dia para pedir ${nome}`,
          detalhes: `A rodada de liberação fecha às ${diaHora(f.fim)} (horário de Brasília). `
                  + 'Se só você pedir, o nome é seu pela anuidade.',
          inicio: new Date(f.fim.getTime() - 30 * 60000), fim: f.fim,
          url: busca, uid: `rodada-${nome}`, arquivo: `rodada-${nome}.ics`,
        }, false);
      }
    } else if (f.tipo === 'leilao') {
      // O FIM DE UM LEILAO NAO E PUBLICO. O `date=` do cabecalho e o fim da
      // RODADA, e a regra so garante "pelo menos 24 h" de ofertas depois do
      // fechamento dos tickets: e um PISO, nunca uma previsao. Medido em
      // 17/09/2026: vacina.com.br foi ate 16h (piso 15h) e groupon.com.br
      // seguia em leilao com o piso vencido havia horas (L5). Ate 17/09 esta
      // ficha dizia "o leilao terminou" para um leilao aberto — quem confiasse
      // nela perderia o nome. Enquanto o RDAP ao vivo responde
      // `competitive-release-process-*`, o leilao esta acontecendo AGORA.
      const naoAntesDe = f.fim ? new Date(f.fim.getTime() + 24 * 3600000) : null;
      const pisoPassou = naoAntesDe && naoAntesDe <= agora;
      Object.assign(ctx, { mes: mesDaRodada(f.fim), aoVivo: true });
      titulo = `${nomeHtml} está em leilão`;
      corpo = `<p>Ofertas ${naoAntesDe && !pisoPassou
        ? `não acabam antes de <strong>${esc(diaHora(naoAntesDe))}</strong>, horário de Brasília`
        : 'em andamento'}; lance nos 10 minutos finais prorroga por mais 10. `
        + 'O Registro.br não publica a hora de fim de cada leilão. Só dá lance quem se candidatou '
        + `até o fim da rodada${f.tickets ? `, e ${f.tickets} se candidataram` : ''}.</p>`;
      if (pisoPassou) {
        corpo += '<p>O leilão já passou das 24 h mínimas de ofertas e <strong>continua '
          + 'aberto</strong>: leilão não acaba junto com a rodada. Acompanhe no painel.</p>';
      }
      acoes = link(PAINEL_LEILAO, 'Abrir o painel de leilões', true);
      if (naoAntesDe && !pisoPassou) {
        // O evento marca o piso, a primeira hora em que o leilao PODE fechar,
        // e nao promete que fecha ali. Passado o piso nao ha data honesta
        // para oferecer, e o botao some.
        acoes += botaoAgenda('Lembrar do fim do leilão', {
          cabecalho: `Lembrar do fim do leilão de ${nome}`,
          texto: `Não termina antes de ${diaHora(naoAntesDe)}, horário de Brasília.`,
          nota: 'O Registro.br não avisa quando cobrem o seu lance, e não publica a hora do fim.',
          titulo: `Leilão de ${nome}: pode fechar a partir daqui`,
          detalhes: `Não termina antes de ${diaHora(naoAntesDe)} (horário de Brasília); pode ir `
                  + 'muito além. Lance nos 10 minutos finais prorroga por mais 10. Oferta é vinculante.',
          inicio: new Date(naoAntesDe.getTime() - 30 * 60000), fim: naoAntesDe,
          url: PAINEL_LEILAO, uid: `leilao-${nome}`,
          servido: `/lembretes/${encodeURIComponent(nome)}.ics`, arquivo: `leilao-${nome}.ics`,
        }, false);
      }
    } else if (f.tipo === 'decisao') {
      titulo = `${nomeHtml} está fora do ar por decisão`;
      corpo = '<p>O Registro.br marca o nome como fora do ar por ordem judicial ou por decisão do '
        + 'CGI.br. Não há previsão de volta ao mercado.</p>';
    } else if (f.tipo === 'travado') {
      const proxima = proximaAbertura(agora);
      const ultima = [...aberturas].reverse().find((a) => abreEm(a) <= agora);
      Object.assign(ctx, { mes: ultima ? ultima.slice(0, 7) : null, travou: true, proxima });
      titulo = `${nomeHtml} travou e espera a próxima rodada`;
      corpo = '<p>Duas ou mais pessoas pediram o nome na última rodada, então ninguém levou: o '
        + 'Registro.br cancelou todos os pedidos. Quem quiser o nome se candidata de novo.</p>'
        + (proxima ? `<p class="ficha-previsao ficha-volta">O nome volta na <strong>rodada de ${esc(mesDe(proxima))}</strong>: `
          + `a lista sai em ${esc(dia(listaDe(proxima)))} e a rodada abre em ${esc(dia(proxima))}, às 15h.</p>` : '');
      if (proxima) acoes = botaoAgenda('Lembrar quando voltar', lembreteDeVolta(nome, proxima, null, true));
      acoes += link(busca, 'Ver no Registro.br', false);
    } else if (f.tipo === 'pendente') {
      const proxima = proximaAbertura(agora);
      const ultima = [...aberturas].reverse().find((a) => abreEm(a) <= agora);
      Object.assign(ctx, { mes: ultima ? ultima.slice(0, 7) : null, travou: true, proxima });
      titulo = `${nomeHtml} tem um pedido em andamento`;
      corpo = '<p>Não está numa rodada aberta, mas o Registro.br mostra um pedido de registro '
        + 'pendente. Pode ser o pedido único de uma rodada que acabou de fechar, à espera de ser '
        + 'concluído; se não virar registro, o nome volta numa próxima rodada'
        + (proxima ? `, e a próxima abre em ${esc(dia(proxima))}` : '') + '.</p>';
      if (proxima) acoes = botaoAgenda('Lembrar da próxima rodada', lembreteDeVolta(nome, proxima, null, true));
    } else {
      const titular = f.titular ? ` por <strong>${esc(f.titular)}</strong>` : '';
      if (f.tipo === 'registrado') {
        titulo = `${nomeHtml} tem dono`;
        corpo = `<p>Registrado${f.registro ? ` em ${esc(dia(f.registro))}` : ''}${titular}.`
          + (f.vence ? ` Pago até <strong>${esc(dia(f.vence))}</strong>.` : '') + '</p>';
      } else if (f.tipo === 'vencido') {
        titulo = `${nomeHtml} venceu e ainda está no ar`;
        corpo = `<p>Registrado${titular}. Venceu em <strong>${esc(dia(f.vence))}</strong> e ainda não `
          + 'foi pago. O dono ainda pode renovar; se não renovar, o Registro.br tira o nome do ar.</p>';
      } else {
        titulo = `${nomeHtml} está congelado`;
        corpo = `<p>Registrado${titular}. Venceu${f.vence ? ` em <strong>${esc(dia(f.vence))}</strong>` : ''} `
          + `e saiu do ar${f.alterado ? ` (última alteração em ${esc(dia(f.alterado))})` : ''}. `
          + 'O dono ainda pode pagar e reativar.</p>';
      }
      if (f.vence) {
        const p = textoDaPrevisao(nome, f.vence, f.tipo === 'registrado');
        corpo += p.html + nota;
        if (p.evento) acoes = botaoAgenda('Me lembrar nessa data', p.evento);
      }
      acoes += link(busca, 'Ver no Registro.br', false);
    }

    // o alvo guarda o nome em tela: resposta atrasada de outra consulta, no
    // mesmo alvo, nao escreve por cima (/seu-nome/ tem tres alvos na pagina)
    alvo.dataset.nome = nome;
    alvo.innerHTML = `<div class="ficha-cartao ficha-${esc(f.tipo)}">`
      + `<h2 class="ficha-titulo">${titulo}</h2>${corpo}`
      + (acoes ? `<div class="ficha-acoes">${acoes}</div>` : '')
      + '<div class="ficha-passagens"></div><div class="ficha-arquivo"></div></div>';
    return ctx;
  }

  // ------------------------------------------------------------ passagens

  function fnv1a32(texto) {
    let h = 0x811c9dc5;
    for (const byte of new TextEncoder().encode(texto)) {
      h ^= byte;
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h >>> 0;
  }

  /**
   * Quantas rodadas seguidas o nome esta na lista ate o mes `mes` (AAAA-MM),
   * e o que isso diz da proxima: tres travas seguidas e ele entra elegivel ao
   * leilao (limitacao S13, 99,4% dos elegiveis de 2019 a 2025). Pura, sem
   * DOM nem rede: o teste roda no node.
   *
   *   rodadas: datas AAAA-MM-DD do indice (rodadas.json)
   *   linha:   "0,85,86e" do indice, ou null se o nome nao esta nele
   *   mes:     a rodada de agora, ou a ultima, se o nome travou nela
   *   naLista: o RDAP diz que o nome esta (ou travou) na rodada de `mes`
   *
   * Mes sem lista guardada nao prova ausencia: a contagem vira piso e a
   * previsao, "incerta". Nome fora do indice so prova ausencia se a rodada
   * de agora ja foi indexada (senao pode ter uma passagem em qualquer mes).
   * Nome elegivel numa rodada estava nas tres anteriores, com copia ou nao.
   */
  function sequencia(rodadas, linha, mes, naLista) {
    const chave = (m) => { const [a, b] = m.split('-').map(Number); return a * 12 + b - 1; };
    const volta = (k) => `${Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, '0')}`;
    const cobertos = new Set(rodadas.map((d) => chave(d.slice(0, 7))));
    const ultimo = rodadas.length ? chave(rodadas[rodadas.length - 1].slice(0, 7)) : -1;
    const doNome = new Map();
    for (const t of String(linha || '').split(',')) {
      const d = rodadas[parseInt(t, 10)];
      if (d) doNome.set(chave(d.slice(0, 7)), t.endsWith('e'));
    }
    const atual = chave(mes);
    if (!naLista && !doNome.has(atual)) return { seguidas: 0, proxima: 'nenhuma' };
    const provaAusencia = linha != null || cobertos.has(atual);
    let k = atual, seguidas = 0, elegivel = false, falta = null;
    while (k === atual || doNome.has(k)) {
      seguidas += 1;
      if (doNome.get(k)) {
        // elegivel nessa rodada: as tres anteriores estao provadas pela lista
        // de elegiveis, com copia da de liberacao ou nao
        elegivel = true;
        seguidas += 3;
        break;
      }
      k -= 1;
    }
    if (!elegivel && (k > ultimo || !cobertos.has(k) || !provaAusencia)) {
      // a rodada de agora fora do indice: o que falta e ela, nao o mes de antes
      const semIndice = !provaAusencia ? atual : k > ultimo ? k : null;
      falta = semIndice != null ? { mes: volta(semIndice), motivo: 'indice' }
        : { mes: volta(k), motivo: 'sem-copia' };
    }
    if (seguidas >= 3) return { seguidas, piso: Boolean(falta) || elegivel, proxima: 'leilao' };
    if (falta) {
      // se nem os meses sem prova completam tres, a proxima e rodada normal de todo jeito
      const ausente = (j) => j <= ultimo && cobertos.has(j) && provaAusencia && !doNome.has(j);
      let possiveis = 0;
      for (let j = k; possiveis < 3 - seguidas && !ausente(j); j -= 1) possiveis += 1;
      if (seguidas + possiveis >= 3) return { seguidas, piso: true, proxima: 'incerta', falta };
      return { seguidas, piso: true, proxima: 'rodada', faltam: 3 - seguidas };
    }
    return { seguidas, piso: false, proxima: 'rodada', faltam: 3 - seguidas };
  }

  const mesCurto = (m) => { const [a, b] = m.split('-').map(Number); return `${MESES[b - 1].slice(0, 3)}/${a}`; };

  function textoDaSequencia(s, proxima) {
    const quando = proxima ? `na rodada de ${esc(mesDe(proxima))}` : 'na próxima rodada';
    const lista = proxima ? `, que sai em ${esc(dia(listaDe(proxima)))},` : '';
    const vez = s.seguidas === 1 && !s.piso ? 'a primeira vez que ele trava'
      : `${s.piso ? 'pelo menos a ' : 'a '}${s.seguidas}ª rodada seguida em que ele trava`;
    const regra = '<a href="/insights/tres-travas-e-leilao/">três travas seguidas</a>';
    if (s.proxima === 'leilao') {
      return `<p class="ficha-previsao">É ${vez}. Pela regra das ${regra}, ${quando} ele entra `
        + '<strong>elegível ao leilão</strong>: com dois candidatos abre o processo competitivo, com ofertas '
        + 'a partir de R$ 50, e só dá lance quem se candidatar.</p>';
    }
    if (s.proxima === 'rodada') {
      return `<p class="ficha-previsao">É ${vez}. ${quando.charAt(0).toUpperCase() + quando.slice(1)} ele volta `
        + '<strong>como rodada normal</strong>, com candidatura de graça. Se travar '
        + `${s.piso ? 'de novo nas rodadas seguintes' : s.faltam === 1 ? 'mais uma vez' : 'mais duas vezes seguidas'}, `
        + `vai a leilão (${regra}).</p>`;
    }
    const semLista = s.falta.motivo === 'indice'
      ? `a lista de ${esc(mesCurto(s.falta.mes))} ainda não entrou no nosso índice`
      : `não existe cópia guardada da lista de ${esc(mesCurto(s.falta.mes))}`;
    return `<p class="ficha-previsao">É ${vez}, mas ${semLista}. Se ele travou também nas rodadas `
      + `que não conseguimos ver, ${quando} vai a leilão; se não, volta como rodada normal. `
      + `A lista oficial de elegíveis${lista} tira a dúvida.</p>`;
  }

  async function json(url) {
    const r = await fetch(url);
    return r.ok ? r.json() : null;
  }

  let indice = null;
  let disputas = null;
  async function historico(nome, ctx, alvo) {
    const partes = [];
    let titulo = '';
    try {
      indice = indice || await json(PASSAGENS + 'rodadas.json');
      if (indice) {
        const fatia = (fnv1a32(nome) % (indice.fatias || 256)).toString(16).padStart(2, '0');
        const r = await fetch(`${PASSAGENS}${fatia}.txt`);
        const achada = r.ok ? (await r.text()).split('\n').find((l) => l.startsWith(nome + '\t')) : null;
        const linha = achada ? achada.split('\t')[1] : null;
        if (linha) {
          const posicoes = linha.split(',').map((t) => indice.rodadas[parseInt(t, 10)]).filter(Boolean);
          // rodadas de meses seguidos sao uma passagem so: o nome travou
          const episodios = [];
          for (const iso of posicoes) {
            const [a, m] = iso.split('-').map(Number);
            const ultimo = episodios[episodios.length - 1];
            if (ultimo && ultimo.ano * 12 + ultimo.mes + 1 === a * 12 + m) {
              Object.assign(ultimo, { ano: a, mes: m, n: ultimo.n + 1 });
            } else {
              episodios.push({ iAno: a, iMes: m, ano: a, mes: m, n: 1 });
            }
          }
          const curto = (a, m) => `${MESES[m - 1].slice(0, 3)}/${a}`;
          const itens = episodios.map((e) => (e.n === 1 ? curto(e.ano, e.mes)
            : `${curto(e.iAno, e.iMes)} a ${curto(e.ano, e.mes)} (${e.n} rodadas seguidas: travou)`));
          const vezes = episodios.length;
          const elegivelEm = linha.split(',').filter((t) => t.endsWith('e'))
            .map((t) => indice.rodadas[parseInt(t, 10)]).filter(Boolean).map((d) => mesCurto(d.slice(0, 7)));
          // uma passagem so e, quase sempre, a rodada de agora travando: nao diz
          // nada sobre o dono. Duas ou mais dizem que ele ja deixou vencer.
          titulo = vezes > 1 ? 'Já voltou ao mercado antes' : 'Já passou pela lista';
          partes.push(`<p>Esteve na lista de liberação ${vezes === 1 ? 'uma vez' : `${vezes} vezes`}`
            + ` nas ${indice.rodadas.length} listas guardadas desde ${esc(indice.rodadas[0].slice(0, 4))}: `
            + `${esc(itens.join('; '))}.${vezes > 1 ? ' Quem teve esse nome já o deixou vencer mais de uma vez.' : ''}`
            + (elegivelEm.length ? ` Foi elegível ao leilão em ${esc(elegivelEm.join(', '))}.` : '') + '</p>');
        }
        const elegivelAgora = Boolean(linha) && linha.split(',').some((t) => t.endsWith('e')
          && (indice.rodadas[parseInt(t, 10)] || '').slice(0, 7) === ctx.mes);
        if (ctx.aoVivo && ctx.travou && elegivelAgora) {
          // Elegivel nesta rodada com dois candidatos: vai a leilao agora, nao
          // volta. Se o RDAP ainda nao virou para "competitive", o cartao
          // mandaria nao se candidatar justo no nome que so aceita lance de
          // quem tem candidatura.
          const trava = alvo.querySelector('.ficha-trava');
          if (alvo.dataset.nome === nome && trava) {
            trava.innerHTML = 'Este nome é <strong>elegível ao leilão nesta rodada</strong>: com dois candidatos '
              + 'abre o processo competitivo, e só dá lance quem se candidatou. Para disputar, candidate-se '
              + 'antes de o prazo de novos pedidos fechar.';
            const volta = alvo.querySelector('.ficha-volta');
            if (volta) volta.remove();
            const acoes = alvo.querySelector('.ficha-acoes');
            if (acoes) {
              acoes.innerHTML = link(BUSCA + encodeURIComponent(nome), 'Candidatar-se no Registro.br', true)
                + `<button type="button" data-disputa="${esc(nome)}">Ver quem disputa</button>`;
            }
          }
        } else if (ctx.travou && ctx.mes && (linha || r.ok)) {
          // fatia que nao baixou nao prova que o nome esta fora do indice
          partes.push(textoDaSequencia(sequencia(indice.rodadas, linha, ctx.mes, true), ctx.proxima));
        } else if (!linha && r.ok && !ctx.travou && !ctx.invalido) {
          // Fora do indice NAO e "nunca": o indice so guarda quem passou duas
          // vezes ou mais (garimpo/dominio/passagens.py). O que se sabe e que
          // ele passou no maximo uma vez; se a rodada de agora ja esta no
          // indice e o nome esta nela, esta e a primeira (19/09/2026, /seu-nome/).
          const copias = `entre as ${indice.rodadas.length} listas de que temos cópia, desde `
            + `${esc(indice.rodadas[0].slice(0, 4))}`;
          const agoraIndexada = ctx.mes && indice.rodadas.some((d) => d.slice(0, 7) === ctx.mes);
          if (agoraIndexada) {
            titulo = 'Primeira vez na lista';
            partes.push(`<p>É a primeira vez que ele aparece na lista de liberação, ${copias}.</p>`);
          } else {
            partes.push(`<p>${ctx.mes ? 'Antes desta rodada, passou' : 'Passou'} no máximo uma vez pela `
              + `lista de liberação, ${copias}.</p>`);
          }
        }
      }
    } catch (e) {
      // indice e complemento: sem ele a ficha continua certa
    }
    try {
      disputas = disputas || await json(DISPUTAS);
      const rodadas = Object.entries((disputas || {}).rodadas || {});
      const fases = (disputas || {}).fases || [];
      const vistas = rodadas
        // a rodada de agora ja aparece ao vivo no cartao, pelo RDAP
        .filter(([inicio, r]) => r.nomes[nome] && !(ctx.aoVivo && inicio.slice(0, 7) === ctx.mes))
        .map(([inicio, r]) => {
          const [n, fase] = r.nomes[nome];
          const onde = { rodada: 'rodada normal', elegivel: 'elegível ao leilão', leilao: 'leilão' }[fases[fase]] || '';
          return `${mesCurto(inicio.slice(0, 7))}: ${n} candidatos${onde ? ` (${onde})` : ''}`;
        });
      if (vistas.length) {
        const primeira = rodadas[0];
        titulo = titulo || 'Já foi disputado';
        partes.push(`<p>Candidatos visíveis que registramos: ${esc(vistas.join('; '))}.</p>`
          + '<p class="ficha-nota">Contagem do próprio Liberados desde '
          + `${esc(mesCurto(primeira[0].slice(0, 7)))}, só nos nomes que a varredura confere `
          + `(${esc(primeira[1].conferidos.toLocaleString('pt-BR'))} de `
          + `${esc(primeira[1].na_lista.toLocaleString('pt-BR'))} naquela rodada). É piso: candidato único não `
          + 'aparece, e quem se candidatou depois da última conferência também não.</p>');
      }
    } catch (e) {
      // idem: a base de disputas e complemento
    }
    const bloco = alvo.querySelector('.ficha-passagens');
    if (!bloco || alvo.dataset.nome !== nome || !partes.length) return;
    bloco.innerHTML = `<h3>${esc(titulo || 'Histórico nas rodadas')}</h3>${partes.join('')}`;
  }

  // ------------------------------------------------------------ arquivo

  /*
   * "Este dominio ja teve site?", lido no indice que arquivar_wayback.py
   * monta a partir do Internet Archive. O navegador nunca fala com o
   * Internet Archive (nao ha CORS, limitacao F8): le a resposta guardada.
   *
   * NOME FORA DO INDICE NAO E "NUNCA CAPTURADO". E so "ainda nao
   * consultamos". Por isso, sem linha para o nome, esta secao nao diz nada.
   * Confundir os dois foi o bug de 14/09/2026: o arquivo fora do ar saiu
   * publicado como "nunca capturado" para um nome com 100 capturas.
   */
  function mesAno(aaaamm) {
    return `${MESES[parseInt(aaaamm.slice(4, 6), 10) - 1].slice(0, 3)}/${aaaamm.slice(0, 4)}`;
  }

  function vezesDeMes(n) {
    return n === 1 ? 'um mês' : `${n} meses`;
  }

  async function arquivoDoNome(nome, alvo) {
    let campos = null;
    try {
      const fatia = (fnv1a32(nome) % 256).toString(16).padStart(2, '0');
      const r = await fetch(`${ARQUIVO}${fatia}.txt`);
      if (!r.ok) return;
      const achada = (await r.text()).split('\n').find((l) => l.startsWith(nome + '\t'));
      if (achada) campos = achada.split('\t');
    } catch (e) {
      return;                     // complemento: sem indice, a ficha segue sem
    }
    const bloco = alvo.querySelector('.ficha-arquivo');
    if (!bloco || alvo.dataset.nome !== nome || !campos || campos.length !== 7) return;
    const [, primeira, ultima, cap, serv, redir, quando] = campos;
    const capturas = parseInt(cap, 10);
    const servindo = parseInt(serv, 10);
    const redirecionando = parseInt(redir, 10);
    const lido = `${quando.slice(6, 8)}/${quando.slice(4, 6)}/${quando.slice(0, 4)}`;
    const ver = `<a href="https://web.archive.org/web/*/${encodeURIComponent(nome)}" `
      + 'rel="noopener" target="_blank">ver as capturas no Internet Archive</a>';
    let titulo;
    let texto;
    if (!capturas) {
      titulo = 'Sem captura no Internet Archive';
      texto = 'O Internet Archive não guardou nenhuma página deste endereço. Isso '
        + '<strong>não prova</strong> que ele nunca teve site: a cobertura dos '
        + 'domínios <code>.br</code> no arquivo é desigual.';
    } else if (servindo) {
      titulo = 'Já teve site';
      texto = `O Internet Archive guardou ${capturas.toLocaleString('pt-BR')} `
        + `captura${capturas === 1 ? '' : 's'}, de ${esc(mesAno(primeira))} a `
        + `${esc(mesAno(ultima))}. Em ${vezesDeMes(servindo)} o endereço serviu `
        + 'página própria'
        + (redirecionando ? `, e em ${vezesDeMes(redirecionando)} redirecionou para outro lugar` : '')
        + '. Um nome que já foi usado pode trazer tráfego e links antigos.';
    } else {
      titulo = 'Foi usado para redirecionar';
      texto = `O Internet Archive guardou ${capturas.toLocaleString('pt-BR')} `
        + `captura${capturas === 1 ? '' : 's'}, de ${esc(mesAno(primeira))} a `
        + `${esc(mesAno(ultima))}, mas em nenhuma o endereço serviu página própria`
        + (redirecionando ? `: em ${vezesDeMes(redirecionando)} apontou para outro endereço` : '')
        + '.';
    }
    bloco.innerHTML = `<h3>${esc(titulo)}</h3><p>${texto} `
      + `<span class="ficha-nota">Lido em ${esc(lido)}; ${ver}.</span></p>`;
  }

  // ------------------------------------------------------------ fluxo

  /**
   * Uma consulta ao RDAP e o cartao dela, desenhado em `alvo`. Espera a
   * PAUSA desde a consulta anterior (desta pagina) e deixa o erro subir para
   * quem chamou. E o que /seu-nome/ usa, um alvo por nome (seu-nome.js).
   */
  async function conferir(nome, exibe, alvo) {
    const espera = ultimaConsulta + PAUSA - Date.now();
    if (espera > 0) await new Promise((r) => setTimeout(r, espera));
    alvo.dataset.nome = '';
    alvo.innerHTML = `<p class="ficha-carregando">Consultando <code>${esc(nome)}</code> no Registro.br…</p>`;
    try {
      if (!window.Disputa || !window.Disputa.consultar) throw new Error('a página não carregou inteira; recarregue');
      const res = await window.Disputa.consultar('domain/' + encodeURIComponent(nome));
      ultimaConsulta = Date.now();
      historico(nome, desenhar(nome, classificar(res, exibe), exibe, alvo), alvo);
      arquivoDoNome(nome, alvo);
    } finally {
      ultimaConsulta = Date.now();
    }
  }

  async function consultar(bruto) {
    const saida = $('#ficha-resultado');
    const { nome, erro, exibe } = normalizar(bruto);
    if (!nome) {
      saida.innerHTML = erro ? `<p class="ficha-erro">${esc(erro)}</p>` : '';
      return;
    }
    if (ocupado) return;
    ocupado = true;
    const botao = $('#ficha-form button');
    if (botao) botao.disabled = true;
    $('#ficha-nome').value = exibe;
    history.replaceState(null, '', `?d=${encodeURIComponent(nome)}`);
    try {
      await conferir(nome, exibe, saida);
    } catch (e) {
      // depois de um 429, Disputa.consultar bloqueia por 5 min (cota
      // compartilhada com "quem disputa" e a conferencia ao vivo): a
      // mensagem ja diz quanto falta, sem o prefixo generico
      const bloqueada = window.Disputa && window.Disputa.bloqueado && window.Disputa.bloqueado();
      saida.innerHTML = bloqueada ? `<p class="ficha-erro">${esc(e.message)}</p>`
        : `<p class="ficha-erro">Não deu para consultar agora: ${esc(e.message)}.</p>`;
    } finally {
      ocupado = false;
      const bloqueada = Boolean(window.Disputa && window.Disputa.bloqueado && window.Disputa.bloqueado());
      if (botao) botao.disabled = bloqueada;
      // sem isto, o botao ficava desabilitado para sempre depois do
      // bloqueio: ninguem mais chama consultar() para destravar sozinho
      if (bloqueada && window.Disputa.restanteBloqueio) {
        setTimeout(() => { if (!ocupado && botao) botao.disabled = false; }, window.Disputa.restanteBloqueio() + 200);
      }
    }
  }

  // o botao de agenda de qualquer cartao, desta pagina ou de /seu-nome/
  document.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('[data-agenda]');
    if (b && window.Agenda && eventos.has(b.dataset.agenda)) window.Agenda.abrir(eventos.get(b.dataset.agenda));
  });

  window.Ficha = { normalizar, foraDaRegra, conferir, PAUSA };

  function iniciar() {
    const form = $('#ficha-form');
    if (!form) return;
    // form-action 'none' na CSP: o envio e sempre por aqui, nunca navegacao
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      consultar($('#ficha-nome').value);
    });
    // So ?d=; nunca o hash (#respostas, #travou...): a pagina tem h2 com id
    // para cada secao, e compartilhar.js poe neles um link "#id" para
    // copiar. Ler o hash aqui como nome de dominio consultava o RDAP de
    // "travou.com.br" toda vez que alguem abria /quando-volta/#travou
    // (18/09/2026, F-bug). Nenhum link do repositorio usa #nome: todos usam
    // ?d=, que continua funcionando.
    const pedido = new URLSearchParams(location.search).get('d');
    if (pedido) consultar(pedido);
  }

  iniciar();
})();
