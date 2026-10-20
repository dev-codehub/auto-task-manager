# Testar o plugin auto-task-manager (instalação manual, via zip)

Este guia é para quem recebeu o `.zip` diretamente, sem passar pelo
`/plugin marketplace add`.

## Antes de começar (comum às duas ferramentas)

- Extrai o zip para uma pasta, por exemplo `~/auto-task-manager`:
  ```bash
  unzip auto-task-manager-codex-support.zip -d ~/
  ```
- Credenciais Redmine (uma vez, nunca partilhes esta chave):
  ```bash
  mkdir -p ~/.config/redmine-sync
  printf '%s\n' 'A-TUA-CHAVE-API' > ~/.config/redmine-sync/credentials
  chmod 600 ~/.config/redmine-sync/credentials
  ```
  (chave em *My account → API access key* no teu Redmine)
- Copia o template incluído no zip e preenche os campos marcados
  `PREENCHE:` (deixa `issue_key` como está):
  ```bash
  cd ~/auto-task-manager
  cp redmine.example.json .redmine.json
  ```
  Depois abre `.redmine.json` num editor de texto e substitui cada
  `PREENCHE: ...` pelo valor real - `url` é o endereço do teu Redmine,
  `project` é o identificador do projeto (não o nome; está no URL
  `.../projects/<identificador>/...`), `text_format` é `markdown` ou
  `textile` conforme o teu Redmine (pergunta a quem administra a
  instância se não souberes).
  - O bloco `required_fields_on_close` no fim do template é só um exemplo
    com um campo fictício (`reviewed`). **Se o teu Redmine não obriga a
    preencher nenhum campo personalizado ao fechar uma issue, apaga esse
    bloco** (e a vírgula no fim da linha `issue_key` mesmo acima, senão o
    JSON fica inválido) - com ele lá, o CLI passa a exigir um campo que o
    teu Redmine não tem. Se o teu Redmine obriga, substitui-o pelo campo
    real (`id`, `key`, `name` e `values` - ver o README).
  - Trabalha sempre **a partir de dentro desta pasta** (`cd
    ~/auto-task-manager` antes de abrires o Claude Code ou o Codex) — é
    isso que lhes diz a que Redmine e a que projeto se referem os
    pedidos, e é também aqui que o Codex vai encontrar `.agents/skills/`.
- **Começa sempre pelos comandos só-de-leitura** (`status`, `plan`) antes de
  aprovares qualquer escrita — nenhuma das skills escreve sem pedir
  confirmação explícita primeiro.

## Via Claude Code

- A partir de dentro de `~/auto-task-manager` (onde criaste o
  `.redmine.json`), abre uma sessão apontando o plugin para essa mesma
  pasta:
  ```bash
  cd ~/auto-task-manager
  claude --plugin-dir ~/auto-task-manager
  ```
- Confirma que carregou: pede *"verifica se o comando redmine-sync está
  disponível"*.
- Testa: *"mostra o estado do issue X"* (read-only), depois *"fecha esta
  sessão de trabalho..."* ou *"cria uma feature no Redmine chamada..."*.

## Via Codex

- Põe o `bin/` no PATH (o Codex não faz isto automaticamente, ao
  contrário do Claude Code):
  ```bash
  export PATH="$PATH:$HOME/auto-task-manager/bin"
  redmine-sync --version   # confirma que encontra o comando
  ```
- O Codex descobre as skills em `.agents/skills/` a partir da pasta
  atual, da pasta acima, ou da raiz do repositório onde estiveres a
  trabalhar. Como já puseste o `.redmine.json` dentro de
  `~/auto-task-manager`, basta correres o Codex a partir de lá:
  ```bash
  cd ~/auto-task-manager
  codex
  ```
  Se preferires testar a partir de outro repositório, copia ou symlinka
  a pasta `.agents/skills/` desse zip para dentro do teu próprio
  repositório, e move o `.redmine.json` para lá também.
- Lê `AGENTS.md` (na raiz do zip) para mais detalhes.
- Testa da mesma forma: pede primeiro algo read-only, depois experimenta
  pedir para fechar uma sessão ou criar um issue.

## Testar as skills do Jira (jira-session-close e jira-backlog)

O suporte a Jira foi testado contra uma simulação em memória da API, não
contra um Jira real. A primeira utilização num Jira Cloud verdadeiro deve por
isso ser **acompanhada**, passo a passo, com confirmação na interface do Jira.

- Cria um token em https://id.atlassian.com/manage-profile/security/api-tokens
  e guarda-o (uma vez, nunca o partilhes):
  ```bash
  mkdir -p ~/.config/jira-sync
  printf '%s\n' 'JIRA_EMAIL=O-TEU-EMAIL' 'JIRA_API_TOKEN=O-TEU-TOKEN' > ~/.config/jira-sync/credentials
  chmod 600 ~/.config/jira-sync/credentials
  ```
  (em alternativa, exporta `JIRA_EMAIL` e `JIRA_API_TOKEN`). Um valor que
  ainda comece por `PREENCHE:` é o template por preencher e o CLI recusa-o.
- Copia o template e preenche os campos marcados `PREENCHE:`:
  ```bash
  cd ~/auto-task-manager
  cp jira.example.json .jira.json
  ```
  `url` é o endereço do teu Jira Cloud (sem barra final), `project` é a
  chave do projeto (o prefixo das issues, `PROJ` em `PROJ-123`).
  `story_points_field` é opcional: se souberes o id do campo (por exemplo
  `customfield_10016`) põe-no; senão **apaga essa linha** (e a vírgula no
  fim da linha anterior) e o CLI procura o campo pelo nome. Deixar o
  `PREENCHE:` lá dá erro "not filled in".
- Confirma que o comando existe: `jira-sync --version` e
  `jira-backlog --version` (com o `bin/` no PATH, como acima).
- Se a pasta tiver `.redmine.json` e `.jira.json` ao mesmo tempo, as skills
  param e perguntam qual dos dois queres usar. Para testar o Jira, usa uma
  pasta só com o `.jira.json`.

Checklist da primeira utilização (pára e reporta se algo não bater certo):

1. **Só leitura:** `jira-sync status PROJ-1` (uma issue que exista). Deve
   mostrar estado, story points e as transições disponíveis.
2. **Plano de teste com 3 nós** (um Epic, uma Story debaixo dele, uma
   Sub-task debaixo da story, mais uma relação `blocks` entre dois deles,
   ou entre um deles e uma issue existente `#PROJ-1`). Pede à skill
   `jira-backlog` para o validar (`jira-backlog plan <ficheiro>`) e depois
   para o simular (`jira-backlog apply <ficheiro>`, sem `--write`). Nada
   deve ser criado nesta fase.
3. Só depois de leres a simulação, aprova a escrita
   (`jira-backlog apply <ficheiro> --write`) e **confirma na interface do
   Jira**: os tipos de issue, os pais (Epic > Story > Sub-task), os story
   points e o **sentido** do link `blocks` (quem bloqueia quem; deve ser
   "A bloqueia B" para `from` A, `to` B).
4. **Fecho de sessão:** com a skill `jira-session-close`, faz uma única linha
   que passe uma story para `Done` com `story_points`, simula, aprova e
   escreve. Confirma no Jira o comentário (termina em
   `_jira-sync: <sessão>_`), o estado e os story points.
5. **Repetir** o mesmo `jira-sync apply <ficheiro> --write`: a issue deve ser
   dada como já feita e ignorada, sem segundo comentário.

## O que reportar

- Se o comando/skill foi encontrado ou não (e onde tiveste de o pôr).
- O texto exato de qualquer erro.
- Se o dry-run apareceu sempre antes de qualquer escrita.
- No Jira: o que a checklist acima mostrou na interface (tipos, pais, story
  points, sentido do `blocks`) e o texto exato de qualquer erro do CLI.
- Qualquer coisa que pareça específica do Claude Code e não faça sentido
  no Codex (ou vice-versa) — é exatamente o tipo de detalhe que este
  teste quer apanhar.
