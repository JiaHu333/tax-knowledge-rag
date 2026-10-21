# Rule-Based Tax Knowledge Base Q&A System

German tax knowledge base | Runnable public demo

English | [中文](README.md)

German tax rules are complex, and special cases often require a tax adviser; when an employee leaves, the same issue may incur time and advisory costs again. This project records prior conclusions and sources by scenario so teams can check the conditions, reuse existing guidance, and retain knowledge.

The system organizes tax questions into a fixed menu of topics, scenarios, and tax types. Standard answers and legal references are maintained in Markdown documents. Once a user selects a question, the application reads the corresponding answer from local Chroma using exact source-file, scenario-heading, and tax-heading matches.

The goal is to return the maintained standard answer for each supported question and retain a traceable source. Menu branches and section-matching rules determine which answer to read; document authors maintain the answer text, and the program displays it directly. The current interface and knowledge documents are in Chinese.

## What the program shows

Excerpt from a real run of one public demo path. The Chinese text below is the actual interface; the table that follows explains the same choices in English.

```text
请选择查询主题：
1. 收到供应商发票后的增值税审核
2. 公司承担员工培训费用
3. 公司赠送非员工礼品
Selection: 1

请选择供应商所在地：
1. 供应商在德国；
2. 供应商在国外（服务发票）。
Selection: 1

请选择发票类别：
1. 一般发票；
2. 业务招待餐饮发票；
3. 特殊情况：可能适用 § 13b UStG。
Selection: 1

请选择发票含税总额：
1. 不超过 250 EUR；
2. 超过 250 EUR。
Selection: 1

Answer:
核对供应商完整名称和地址、开票日期、货物或服务的数量及种类、含税总额和适用税率。符合其他进项税抵扣条件时，再判断德国增值税能否抵扣。
法律依据：§ 33 UStDV；§ 15 Abs. 1 Satz 1 Nr. 1、Abs. 2 UStG。
```

### English guide to the example

The example follows menu path `1 → 1 → 1 → 1`:

| Step | Chinese prompt or choice | English meaning | Selected value |
| --- | --- | --- | --- |
| Topic | 收到供应商发票后的增值税审核 | VAT review of an incoming supplier invoice | `1` |
| Supplier location | 供应商在德国 | Supplier located in Germany | `1` |
| Invoice category | 一般发票 | General invoice | `1` |
| Gross invoice total | 不超过 250 EUR | EUR 250 or less, including VAT | `1` |

The top-level topics are:

| Menu choice | Chinese label | English meaning |
| --- | --- | --- |
| `1` | 收到供应商发票后的增值税审核 | VAT review of an incoming supplier invoice |
| `2` | 公司承担员工培训费用 | Employer-paid employee training |
| `3` | 公司赠送非员工礼品 | Business gifts to nonemployees |

English explanation of the sample answer: check the supplier's full name and address, invoice date, quantity and description of goods or services, gross amount, and applicable VAT rate. Then assess input VAT deductibility subject to the other input VAT requirements. Legal references: § 33 UStDV and § 15 Abs. 1 Satz 1 Nr. 1, Abs. 2 UStG.

These tables and the answer explanation are documentation translations. The application continues to show Chinese prompts and authored Chinese answers; an English runtime interface is not included.

The answer text comes from the public sample document [vat_invoice_demo_cn.md](docs/CN/vat_invoice_demo_cn.md). If the matching section is missing or duplicated, the application raises an error instead of substituting a similar section.

## How it works

| Stage | Files | Behavior |
| --- | --- | --- |
| Ingest | `ingest.py`, `docs/CN/` | Split Markdown by headings; store text and section metadata in local Chroma. Ingestion uses Ollama `nomic-embed-text`. |
| Select | `config.json`, `ask.py` | The fixed menu limits topic, scenario, and tax type. The query selects exact metadata matches; it does not run vector-similarity retrieval. |
| Display | `ask.py` | Show the authored document answer without language-model rewriting. |
| Validate | `batch_validate_tax_rag.py`, `demo_expected.json` | Run each menu path and compare answer, source, tax type, and required conditions. |

### What Ollama and the vectors do

The current implementation retains the Chroma and embedding components introduced earlier in the project:

- `ingest.py` uses Ollama's `nomic-embed-text` to generate vectors for document chunks and stores the text and section metadata in Chroma.
- `ask.py` reads text by exact source, scenario, and tax-type matches. It does not perform vector-similarity retrieval during menu queries.
- Fixed-menu answers do not call a generative model such as phi3. There is no model-generated fallback; a failed match produces an error or a not-covered message.

The current Q&A behavior is therefore rule-based. Ollama remains a dependency of the existing ingestion process, but it does not select or compose menu answers. The project title describes this behavior; the repository retains its historical name, `tax-knowledge-rag`.

The public demo has 3 topics and 15 paths: supplier-invoice VAT review (7 paths), employer-paid training (2 scenarios × VAT, CIT, Payroll), and deduction of business gifts to nonemployees (2 CIT paths). The gift example compares the total cost for one recipient in one fiscal year with the EUR 50 limit; it does not cover VAT or the recipient's tax treatment. The simplified samples were written for this repository. Official references are listed in [SOURCES.md](SOURCES.md).

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

On 15 October 2026, all 15 paths in the current public demo were run locally: 15/15 `passed` (7 VAT, 6 training, and 2 gift paths). Every answer used `Python` document-direct output; return codes and stderr were clear, and answers, sources, tax types, and required conditions matched the demo baseline. This is a software acceptance check, not an independent tax audit. The repository does not currently have a GitHub Actions CI record.

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

| File or directory | Purpose |
| --- | --- |
| `README.md`, `README_EN.md` | Chinese and English documentation |
| `SOURCES.md` | Official reference links |
| `ask.py`, `config.json` | Menu, matching rules, and answer display |
| `ingest.py` | Document splitting and incremental ingestion |
| `batch_validate_tax_rag.py`, `demo_expected.json` | Runtime validation and expected answers |
| `requirements.txt`, `.gitignore` | Dependencies and ignore rules |
| `docs/CN/vat_invoice_demo_cn.md` | Supplier-invoice VAT sample |
| `docs/CN/employee_training_demo_cn.md` | Employee-training sample |
| `docs/CN/business_gifts_demo_cn.md` | Nonemployee-gift sample |

The full private knowledge corpus, private standard-answer baseline, database, and raw validation logs are not included. The local `db/` directory is generated during ingestion and ignored by Git.

The sample answers use simplified facts to demonstrate software behavior. Practical tax treatment requires checking the applicable period, entity, transaction facts, and current law.

