# PDF Anonymizer

Substitui identificadores sensíveis em PDFs HISCON e pareceres técnicos por valores falsos, preservando layout, fontes e coerência entre documentos.

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recomendado) ou `python3-venv` + `pip`

## Instalação

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd pdf-anonymizer
uv sync
```

## Uso

Coloque os PDFs originais em `docs/` e execute:

```bash
# Descobrir entidades sensíveis (gera entities.yaml)
uv run pdf-anonymizer discover

# Aplicar anonimização (gera output/*.pdf e output/mapping.json)
uv run pdf-anonymizer run

# Validar PDFs gerados
uv run pdf-anonymizer validate
```

### Um PDF por vez (casos em `cases/`)

```bash
uv run pdf-anonymizer discover /caminho/para/parecer.pdf \
  --name "IRENE STOLF" --fake-name "MARIA SOUZA"

uv run pdf-anonymizer run /caminho/para/parecer.pdf \
  --name "IRENE STOLF" --fake-name "MARIA SOUZA"

uv run pdf-anonymizer validate /caminho/para/parecer.pdf \
  --name "IRENE STOLF" --fake-name "MARIA SOUZA"
```

Opcional: `--account` e `--agency` quando o HISCON trouxer conta/agência.

## Campos anonimizados

- Nome do titular
- Número do benefício (NB)
- Conta corrente e agência
- Números de contrato (empréstimos e cartão)
- Código de autenticidade do INSS
- Metadados do PDF (Creator, Producer, datas)

**Não são anonimizados:** nomes de bancos, valores em reais, datas operacionais, espécie do benefício.

## Arquivos sensíveis

- `docs/` — PDFs originais (não versionar)
- `cases/` — PDFs, `entities.yaml` e `mapping.json` por caso (não versionar)
- `output/mapping.json` — chave de reidentificação (não versionar)
