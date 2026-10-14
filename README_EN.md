# German Tax Fixed-Menu Knowledge Base | Runnable Demo

English | [中文](README.md)

German tax rules are complex, and special cases often require a tax adviser; when an employee leaves, the same issue may incur time and advisory costs again. This project records prior conclusions and sources by scenario so teams can check the conditions, reuse existing guidance, and retain knowledge.

A local, fixed-menu knowledge-base demo. Choose a topic and scenario; the application selects an authored answer from Chroma by source file, scenario heading, and tax heading. The current query path accepts no free-text questions and does not use a language model to rewrite the answer.

## What the program shows

Excerpt from a real run of one public demo path (menu prompts are in Chinese):

```text
请选择查询主题：
1. VAT 发票形式审查
2. 公司承担员工培训费用
Selection: 1

请选择发票情况：
1. 公司收到包含法定必要信息的业务发票；
2. 发票缺少法定必要信息。
3. 回到上一级菜单
Selection: 1

Selected 1 chunk(s) for answer construction:
  Source: vat_invoice_demo_cn.md | Tax type: VAT

Answer:
若德国公司是服务接受方，购入项目用于具有进项税抵扣权的经营活动，并持有符合发票要求的凭证，相关进项税原则上可以抵扣。仍需另行检查是否存在免税业务或其他抵扣排除情形。
法律依据：§ 15 Abs. 1 Satz 1 Nr. 1、Abs. 2 UStG；§§ 14、14a UStG。
```

The answer text comes from the public sample document [vat_invoice_demo_cn.md](docs/CN/vat_invoice_demo_cn.md). If the matching section is missing or duplicated, the application raises an error instead of substituting a similar section.

## How it works

| Stage | Files | Behavior |
| --- | --- | --- |
| Ingest | `ingest.py`, `docs/CN/` | Split Markdown by headings; store text and section metadata in local Chroma. Ingestion uses Ollama `nomic-embed-text`. |
| Select | `config.json`, `ask.py` | The fixed menu limits topic, scenario, and tax type. The query selects exact metadata matches; it does not run vector-similarity retrieval. |
| Display | `ask.py` | Show the authored document answer without language-model rewriting. |
| Validate | `batch_validate_tax_rag.py`, `demo_expected.json` | Run each menu path and compare answer, source, tax type, and required conditions. |

The public demo has 3 topics and 10 paths: VAT invoice review (2 paths), employer-paid training (2 scenarios × VAT, CIT, Payroll), and deduction of business gifts to nonemployees (2 CIT paths). The gift example compares the total cost for one recipient in one fiscal year with the EUR 50 limit; it does not cover VAT or the recipient's tax treatment. The simplified samples were written for this repository. Official references are listed in [SOURCES.md](SOURCES.md).

## Run locally

Requires Python 3.11, a running Ollama service, and the `nomic-embed-text` model. From the repository root:

```powershell
conda create -n tax-kb-demo python=3.11
conda activate tax-kb-demo
pip install -r requirements.txt
ollama pull nomic-embed-text
python ingest.py --docs docs --db db
python ask.py --config config.json --db db
```

Enter `exit`, `quit`, or `q` to leave the menu.

## Validation scope

The previous 8-path public version was run locally: 8/8 `passed`, each using `Python` document-direct output, with 0 runtime errors. The 2 newly added gift paths have not yet completed an end-to-end run with Ollama/Chroma, so this version does not claim 10/10 passed. Validation establishes agreement with the separate demo baseline; it is not an independent tax audit. The repository does not currently have a GitHub Actions CI record.

To reproduce locally:

```powershell
python batch_validate_tax_rag.py `
  --ask ask.py `
  --config config.json `
  --db db `
  --ingest ingest.py `
  --expected demo_expected.json `
  --out validation_demo
```

Inspect `validation_demo/summary.json`. Validation logs contain answers and selected context; `.gitignore` excludes them from the repository.

## Public files and data boundary

```text
tax-knowledge-rag/
├── README.md
├── README_EN.md
├── SOURCES.md
├── ask.py
├── ingest.py
├── batch_validate_tax_rag.py
├── config.json
├── demo_expected.json
├── requirements.txt
├── .gitignore
└── docs/CN/
    ├── business_gifts_demo_cn.md
    ├── employee_training_demo_cn.md
    └── vat_invoice_demo_cn.md
```

The full private knowledge corpus, 65-path production baseline, database, and raw validation logs are not included. The local `db/` directory is generated during ingestion and ignored by Git.

The sample answers use simplified facts to demonstrate software behavior. Practical tax treatment requires checking the applicable period, entity, transaction facts, and current law.
