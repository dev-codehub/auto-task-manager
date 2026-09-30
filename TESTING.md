# Testar o plugin auto-task-manager (instalação manual, via zip)

Este guia é para quem recebeu o `.zip` diretamente, sem passar pelo
`/plugin marketplace add`.

## Antes de começar (comum às duas ferramentas)

- Extrai o zip para uma pasta, por exemplo `~/auto-task-manager`.
- Credenciais Redmine (uma vez, nunca partilhes esta chave):
  ```bash
  mkdir -p ~/.config/redmine-sync
  printf '%s\n' 'A-TUA-CHAVE-API' > ~/.config/redmine-sync/credentials
  chmod 600 ~/.config/redmine-sync/credentials
  ```
  (chave em *My account → API access key* no teu Redmine)
- Num repositório de teste (pode ser uma pasta vazia só para isto), cria
  `.redmine.json` na raiz:
  ```json
  {
    "url": "https://o-teu-redmine",
    "project": "identificador-do-projeto",
    "text_format": "markdown",
    "issue_key": "subject_prefix"
  }
  ```
- **Começa sempre pelos comandos só-de-leitura** (`status`, `plan`) antes de
  aprovares qualquer escrita — nenhuma das skills escreve sem pedir
  confirmação explícita primeiro.

## Via Claude Code

- Abre uma sessão a apontar para a pasta extraída:
  ```bash
  cd /caminho/para/o/repo-de-teste
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
  trabalhar. A forma mais simples de testar: corre o Codex a partir de
  dentro da própria pasta `auto-task-manager` extraída (que já tem
  `.agents/skills/`), com `.redmine.json` também aí. Se preferires testar
  a partir de outro repositório, copia ou symlinka a pasta
  `.agents/skills/` desse zip para dentro do teu próprio repositório.
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
