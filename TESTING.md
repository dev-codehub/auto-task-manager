# Testar o plugin auto-task-manager (instalação manual, via zip)

Este guia é para quem recebeu o `.zip` (`auto-task-manager-0.4.0.zip`)
diretamente, sem passar pelo `/plugin marketplace add`. O plugin tem skills
para **Redmine** e para **Jira Cloud**: testa a que usas. As secções
"Configurar o Redmine" e "Configurar o Jira" são independentes.

## Antes de começar (comum)

- Precisas de Python 3.9 ou superior (`python3 --version`); não há nada para
  instalar.
- Extrai o zip para uma pasta, por exemplo `~/auto-task-manager`:
  ```bash
  unzip auto-task-manager-0.4.0.zip -d ~/
  ```
- Trabalha sempre **a partir de dentro desta pasta** (`cd
  ~/auto-task-manager` antes de abrires o Claude Code ou o Codex) — é isso
  que lhes diz a que Redmine/Jira e a que projeto se referem os pedidos, e é
  também aqui que o Codex vai encontrar `.agents/skills/`.
- Não ponhas `.redmine.json` e `.jira.json` na mesma pasta: com os dois, as
  skills param e perguntam qual dos trackers queres usar.
- **Começa sempre pelos comandos só-de-leitura** (`status`, `plan`) antes de
  aprovares qualquer escrita — nenhuma das skills escreve sem pedir
  confirmação explícita primeiro.
- Nunca coles chaves ou tokens numa conversa: as skills não os lêem nem os
  pedem.

## Configurar o Redmine

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

## Configurar o Jira

São dois ficheiros: as **credenciais** (fora do repositório, só tuas) e o
**`.jira.json`** (na pasta de trabalho). A referência completa de cada chave
está no [README](README.md#jira).

- Cria um token em https://id.atlassian.com/manage-profile/security/api-tokens
  e guarda-o (uma vez, nunca o partilhes):
  ```bash
  mkdir -p ~/.config/jira-sync
  printf '%s\n' 'JIRA_EMAIL=O-TEU-EMAIL' 'JIRA_API_TOKEN=O-TEU-TOKEN' > ~/.config/jira-sync/credentials
  chmod 600 ~/.config/jira-sync/credentials
  ```
  (em alternativa, exporta `JIRA_EMAIL` e `JIRA_API_TOKEN`). O email é o da
  tua conta Atlassian. Um valor que ainda comece por `PREENCHE:` é o template
  por preencher e o CLI recusa-o.
- Copia o template e preenche os campos marcados `PREENCHE:`:
  ```bash
  cd ~/auto-task-manager
  cp jira.example.json .jira.json
  ```
  - `url`: o endereço do teu Jira Cloud, `https://<site>.atlassian.net`
    (sem barra final).
  - `project`: a chave do projeto, o prefixo das issues (`PROJ` em
    `PROJ-123`).
  - `updates_dir`: já vem preenchido; normalmente não mudas.
  - `story_points_field`: opcional. Se souberes o id do campo dos story
    points (por exemplo `customfield_10016`) põe-no; senão **apaga essa
    linha** (e a vírgula no fim da linha anterior) e o CLI procura o campo
    pelo nome. Deixar o `PREENCHE:` lá dá erro "not filled in".
- Este plugin só suporta **Jira Cloud** (`*.atlassian.net`), não Data Center
  nem Server.

## Via Claude Code

- A partir de dentro de `~/auto-task-manager` (onde puseste o `.redmine.json`
  ou o `.jira.json`), abre uma sessão apontando o plugin para essa mesma
  pasta:
  ```bash
  cd ~/auto-task-manager
  claude --plugin-dir ~/auto-task-manager
  ```
- Confirma que carregou: pede *"verifica se o comando redmine-sync (ou
  jira-sync) está disponível"*.
- Testa: *"mostra o estado do issue X"* (read-only), depois *"fecha esta
  sessão de trabalho..."* ou *"cria uma feature no Redmine/Jira chamada..."*.

## Via Codex

- Põe o `bin/` no PATH (o Codex não faz isto automaticamente, ao
  contrário do Claude Code):
  ```bash
  export PATH="$PATH:$HOME/auto-task-manager/bin"
  redmine-sync --version   # confirma que encontra o comando
  jira-sync --version      # idem, para o Jira (deve dizer 0.4.0)
  ```
- O Codex descobre as skills em `.agents/skills/` a partir da pasta
  atual, da pasta acima, ou da raiz do repositório onde estiveres a
  trabalhar. Como já puseste o `.redmine.json`/`.jira.json` dentro de
  `~/auto-task-manager`, basta correres o Codex a partir de lá:
  ```bash
  cd ~/auto-task-manager
  codex
  ```
  Se preferires testar a partir de outro repositório, copia ou symlinka
  a pasta `.agents/skills/` desse zip para dentro do teu próprio
  repositório, e move o `.redmine.json`/`.jira.json` para lá também.
- Lê `AGENTS.md` (na raiz do zip) para mais detalhes.
- Testa da mesma forma: pede primeiro algo read-only, depois experimenta
  pedir para fechar uma sessão ou criar um issue.

## Checklist do Jira (jira-session-close e jira-backlog)

O suporte a Jira foi testado contra uma simulação da API e contra **um** Jira
Cloud de teste (criar Epic, Task e Subtask com pais, incluindo um pai já
existente referido como `#KEY`; prioridade; story points; os três tipos de
link; descrições em ADF; `update-descriptions`; `fix-parents`; fecho de sessão
com transições para a frente e para trás; repetições imediatas; e a validação
em dry-run). Ainda não foi visto num site real: transições com campos
obrigatórios (por exemplo `Resolution`), limpar um campo com `null`,
diferenças entre projetos team-managed e company-managed, workflows com campos
obrigatórios, e os corpos de erro do Jira para além dos casos já vistos. A
primeira utilização no teu Jira deve por isso ser **acompanhada**, passo a
passo, com confirmação na interface do Jira. Pára e reporta se algo não bater certo.

0. **Antes de tudo**, com o `bin/` no PATH (como acima): `jira-sync
   --version` e `jira-backlog --version` devem dizer `0.4.0`.
1. **Só leitura:** `jira-sync status PROJ-1` (uma issue que exista no teu
   projeto). Deve mostrar estado, story points e as transições disponíveis.
2. **Plano de teste com 3 nós** (um Epic, uma tarefa debaixo dele, uma
   subtarefa debaixo da tarefa, e uma relação `blocks`). Parte do modelo
   incluído:
   ```bash
   mkdir -p jira
   cp jira.plan.example.json jira/plano-teste.json
   ```
   Abre `jira/plano-teste.json` e muda `project` para a tua chave. **Os nomes
   dos tipos de issue variam de projeto para projeto** (o modelo usa `Epic`,
   `Task` e `Subtask`; o teu pode ter `Story`, `Sub-task`, ou nomes na tua
   língua). Não precisas de os adivinhar: corre `jira-backlog plan
   jira/plano-teste.json` e, se um nome não existir, o erro lista os tipos
   do projeto. Um filho tem de estar exatamente um nível abaixo do pai (Epic
   > Task/Story > Subtask) e uma subtarefa precisa de pai.
3. Pede à skill `jira-backlog` para validar (`jira-backlog plan <ficheiro>`) e
   para simular (`jira-backlog apply <ficheiro>`, sem `--write`). Nada deve
   ser criado nesta fase.
4. Só depois de leres a simulação, aprova a escrita (`jira-backlog apply
   <ficheiro> --write`) e **confirma na interface do Jira**: os tipos de
   issue, os pais, os story points e o **sentido** do link `blocks` (deve
   ser "A bloqueia B" para `from` A, `to` B). Corre de novo **logo a seguir**
   o mesmo `jira-backlog apply <ficheiro> --write`: não deve criar nada.
5. **Fecho de sessão:** parte do modelo `jira.update.example.json`:
   ```bash
   mkdir -p jira/session-updates
   cp jira.update.example.json jira/session-updates/2026-01-15-teste-jira.json
   ```
   Muda `issue` para uma issue de teste tua e `status` para o **nome do
   estado de destino como aparece no teu workflow** (pode estar na tua língua,
   por exemplo `Concluído`). Pede à skill `jira-session-close` para simular,
   aprova e escreve. Confirma no Jira o comentário (termina em
   `_jira-sync: <sessão>_`), o estado e os story points. Se a transição
   exigir campos (por exemplo `Resolution`), a simulação diz quais faltam e
   que valores aceita: preenche-os em `transition_fields` (só texto, número e
   opção única são suportados; outros tipos têm de ser preenchidos no Jira).
6. **Repetir** o mesmo `jira-sync apply <ficheiro> --write`: a issue deve ser
   dada como já feita e ignorada, sem segundo comentário.
7. As issues de teste ficam no Jira: apaga-as no fim.

## O que reportar

- A versão (`jira-sync --version`) e se o comando/skill foi encontrado ou
  não (e onde tiveste de o pôr).
- O texto exato de qualquer erro.
- Se o dry-run apareceu sempre antes de qualquer escrita.
- No Jira: o que a checklist acima mostrou na interface (tipos, pais, story
  points, sentido do `blocks`), os nomes dos tipos de issue e dos estados do
  teu projeto, se o projeto é gerido pela empresa ou pela equipa
  (*company-managed* / *team-managed*), e se alguma transição exigiu campos.
- Qualquer coisa que pareça específica do Claude Code e não faça sentido
  no Codex (ou vice-versa) — é exatamente o tipo de detalhe que este
  teste quer apanhar.
