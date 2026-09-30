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
- Cria um ficheiro `.redmine.json` **dentro dessa mesma pasta extraída**
  (`~/auto-task-manager/.redmine.json`) — não precisa de ser um
  repositório git nem uma pasta separada, o CLI só procura este ficheiro:
  ```bash
  cd ~/auto-task-manager
  cat > .redmine.json <<'EOF'
  {
    "url": "https://o-teu-redmine",
    "project": "identificador-do-projeto",
    "text_format": "markdown",
    "issue_key": "subject_prefix"
  }
  EOF
  ```
  - `url` — o endereço do teu Redmine (ex: `https://redmine.aempresa.pt`),
    sem barra final.
  - `project` — o identificador do projeto, não o nome. Está no URL do
    projeto no Redmine: `.../projects/<identificador>/...`.
  - `text_format` — `"markdown"` ou `"textile"`, conforme o que o teu
    Redmine usa (pergunta a quem administra a instância se não souberes).
  - `issue_key` — deixa `"subject_prefix"` (é o que as duas skills
    esperam); só usa `"id_only"` se souberes que é esse o caso do teu
    projeto.
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

## O que reportar

- Se o comando/skill foi encontrado ou não (e onde tiveste de o pôr).
- O texto exato de qualquer erro.
- Se o dry-run apareceu sempre antes de qualquer escrita.
- Qualquer coisa que pareça específica do Claude Code e não faça sentido
  no Codex (ou vice-versa) — é exatamente o tipo de detalhe que este
  teste quer apanhar.
