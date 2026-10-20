# Testar o auto-task-manager (versão alpha)

Obrigado por testares! Este plugin liga o Claude Code (ou o Codex) ao Jira:
no fim de uma sessão de trabalho atualiza as issues, e cria épicos, tarefas e
subtarefas a partir de um plano.

**Nunca escreve no Jira sem te mostrar primeiro o que vai fazer e sem tu
dizeres que sim.** Mesmo assim, usa um **projeto Jira de teste**. Demora cerca
de 30 minutos.

## O que precisas

- Uma conta **Jira Cloud** (o endereço acaba em `.atlassian.net`) e um projeto
  de teste.
- O **Claude Code** (ou o Codex).
- **Python 3.9 ou superior.** Os comandos do plugin são programas em Python.
  Corre `python3 --version` no terminal: tem de aparecer 3.9 ou mais. Se não
  existir ou for mais antigo, instala o Python
  (https://www.python.org/downloads/). Não é preciso instalar mais nada.

## 1. Preparar (5 minutos)

**a) Extrair o zip** na tua pasta pessoal:

```bash
unzip auto-task-manager-*.zip -d ~/
```

**b) Criar um token do Jira** em
https://id.atlassian.com/manage-profile/security/api-tokens e guardá-lo (só
tu o deves ver; **nunca o coles numa conversa**):

```bash
mkdir -p ~/.config/jira-sync
printf '%s\n' 'JIRA_EMAIL=O-TEU-EMAIL' 'JIRA_API_TOKEN=O-TEU-TOKEN' > ~/.config/jira-sync/credentials
chmod 600 ~/.config/jira-sync/credentials
```

O email é o da tua conta Atlassian.

**c) Criar a pasta do teste e o ficheiro `.jira.json`:**

```bash
mkdir ~/teste-jira && cd ~/teste-jira
cp ~/auto-task-manager/jira.example.json .jira.json
```

Abre o `.jira.json` num editor de texto e preenche só duas coisas, apagando o
texto `PREENCHE: ...`:

- `url`: o endereço do teu Jira, por exemplo `https://empresa.atlassian.net`
  (sem `/` no fim);
- `project`: a chave do projeto, o prefixo das issues (`PROJ` em `PROJ-123`).

Na linha `story_points_field`: apaga-a (e a vírgula no fim da linha de cima),
a não ser que saibas o número do campo dos story points.

> **Onde fica o `.jira.json`?** Na **pasta raiz do projeto** em que vais
> trabalhar, a pasta onde abres o Claude Code. Cada projeto tem o seu.
> Não o ponhas numa pasta "de cima" (como a tua pasta pessoal): aplicava-se a
> todos os projetos que estão por baixo. E não ponhas `.jira.json` e
> `.redmine.json` na mesma pasta: as skills param e perguntam qual usar.
> Aqui, `~/teste-jira` faz de projeto de teste.

## 2. Experimentar

Abre o Claude Code **dentro da pasta do teste**, a apontar para o plugin:

```bash
cd ~/teste-jira
claude --plugin-dir ~/auto-task-manager
```

Escreve ao Claude, **por esta ordem**, e confere cada resultado no Jira:

1. *"Mostra o estado da issue PROJ-1"* (uma issue que exista). Deve dizer o
   estado, os story points e para que estados pode passar.
2. *"Quero criar no Jira um épico, uma tarefa dentro dele e uma subtarefa,
   com a tarefa a bloquear a subtarefa. Mostra-me só a simulação."* Deve listar
   o que **seria** criado e não criar nada. Se os tipos de issue do teu projeto
   tiverem outros nomes (por exemplo "História"), o Claude diz-te quais
   existem: usa esses.
3. *"Cria-os."* Depois de leres a simulação. Confere no Jira os tipos, quem é
   filho de quem e que **a tarefa bloqueia a subtarefa** (e não o contrário).
   Pede a seguir *"cria-os outra vez"*: não deve criar nada de novo.
4. *"Fecha esta sessão: passa a tarefa para o estado final e põe 3 story
   points."* Lê a simulação e aprova. Confere no Jira o estado, os story
   points e o comentário (acaba em `_jira-sync: ..._`). Se o Jira exigir um
   campo para fechar (por exemplo `Resolution`), o Claude pergunta-te o valor.
5. Repete o pedido do passo 4: deve dizer que **já está feito**, sem segundo
   comentário.
6. **Apaga as issues de teste** no Jira.

## Se algo correr mal

| Mensagem | O que fazer |
|---|---|
| `... is not filled in` | Ainda ficou um `PREENCHE: ...` no `.jira.json` ou nas credenciais. |
| `the API token was rejected` | Email ou token errados: confirma o email da tua conta Atlassian ou cria outro token. |
| `project ... does not exist or is not visible to you` | A chave do projeto está errada, ou a tua conta não tem acesso a ele. Confirma a chave no endereço de uma issue (`PROJ` em `PROJ-123`). |
| `no .jira.json found` | Não estás na pasta do projeto: faz `cd ~/teste-jira` antes de abrir o Claude Code. |
| `type '...' does not exist ...; available: ...` | O projeto chama outra coisa a esse tipo de issue: usa um dos nomes listados. |

Pára e reporta se algo não bater certo.

## O que me enviar

- O texto **exato** de qualquer erro.
- Se a simulação apareceu sempre antes de qualquer escrita.
- No Jira: o que viste (tipos, quem é filho de quem, story points, o sentido do
  "bloqueia"), os nomes dos tipos de issue e dos estados do teu projeto, e, se
  souberes, se o projeto é *company-managed* ou *team-managed*.
- Se algum estado exigiu campos para fechar.
- Qualquer coisa que tenha sido confusa.

---

## Mais detalhes (opcional)

**Codex em vez do Claude Code.** O Codex não põe os comandos no PATH sozinho:

```bash
export PATH="$PATH:$HOME/auto-task-manager/bin"
jira-sync --version      # deve dizer 0.4.0
```

E precisa das skills na pasta do projeto: copia ou faz um link de
`~/auto-task-manager/.agents/skills` para `~/teste-jira/.agents/skills`, e corre
`codex` a partir de `~/teste-jira`. Mais detalhes em `AGENTS.md`.

**Usar os comandos à mão** (em vez de pedir ao Claude), depois do `export`
acima e dentro de `~/teste-jira`:

```bash
jira-sync status PROJ-1                              # só leitura
cp ~/auto-task-manager/jira.plan.example.json plano.json   # editar project e tipos
jira-backlog plan plano.json                         # valida
jira-backlog apply plano.json                        # simulação
jira-backlog apply plano.json --write                # cria
```

O modelo de fecho de sessão é `jira.update.example.json`
(`jira-sync apply ficheiro.json` simula; `--write` escreve).

**Redmine em vez de Jira.** O mesmo, com `redmine.example.json` copiado para
`.redmine.json` na raiz do projeto, e a chave API (*My account → API access
key*) em `~/.config/redmine-sync/credentials` (modo 600, só a chave numa
linha). Preenche `url`, `project` e `text_format`, e **apaga o bloco
`required_fields_on_close`** (e a vírgula na linha de cima) se o teu Redmine não
exige campos ao fechar uma issue.

**Documentação completa:** `README.md` (cada opção do `.jira.json`, formatos
dos ficheiros, limitações).
