# 德国税务固定菜单知识库｜可运行演示

[English](README_EN.md) | 中文

德国税法复杂，特殊场景常需咨询税务师；经手人离职后，同类问题可能再次耗费时间和咨询费用。本项目按场景保存既有结论和依据，供团队核对条件后复用，减少知识流失。

一个本地运行的固定菜单知识库演示：从菜单选择主题与场景，在 Chroma 中按来源文件、场景标题和税种标题精确读取已编写的答案。当前查询不接受自由提问，也不调用语言模型改写答案。

## 运行效果

下面是公开演示的一条实际菜单路径，内容已节选：

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

答案文字来自公开示例文档 [vat_invoice_demo_cn.md](docs/CN/vat_invoice_demo_cn.md)。若对应章节缺失或不唯一，程序会报错，不会改用相似内容补答。

## 程序如何工作

| 步骤 | 文件 | 作用 |
| --- | --- | --- |
| 建库 | `ingest.py`、`docs/CN/` | 按 Markdown 标题切分文档，保存正文和章节元数据到本地 Chroma；建库时使用 Ollama `nomic-embed-text` |
| 选择 | `config.json`、`ask.py` | 固定菜单限定主题、场景、税种；查询时按元数据精确定位答案，不运行向量相似度检索 |
| 输出 | `ask.py` | 直接展示文档答案，无语言模型改写 |
| 验证 | `batch_validate_tax_rag.py`、`demo_expected.json` | 逐条运行菜单路径，对照答案、来源、税种和必需条件 |

公开演示有 3 个主题、15 条路径：收到供应商发票后的增值税审核（7 条）；公司承担员工培训费用（VAT、CIT、Payroll 各 2 条）；向非员工赠送业务礼品的费用扣除（CIT，2 条）。礼品演示按同一受赠人一个经济年度内的累计成本是否超过 50 欧元区分，不覆盖 VAT 或受赠人的税务处理。这些简化示例为本仓库重新编写。官方资料见 [SOURCES.md](SOURCES.md)。

## 本地运行

需要 Python 3.11、可用的 Ollama 服务和 `nomic-embed-text` 模型。在仓库根目录运行：

```powershell
conda create -n tax-kb-demo python=3.11
conda activate tax-kb-demo
pip install -r requirements.txt
ollama pull nomic-embed-text
python ingest.py --docs docs --db db
python ask.py --config config.json --db db
```

输入 `exit`、`quit` 或 `q` 退出菜单。

## 验收范围

2026 年 10 月 15 日在本地对当前公开版完整运行了 15 条菜单路径：15/15 为 `passed`，其中 VAT 7 条、员工培训 6 条、礼品 2 条。输出方式均为 `Python` 文档直读，运行错误和错误日志均为 0；答案、来源、税种及必要条件与演示基线一致。此结果是程序验收，不代表独立税务审计。仓库目前没有 GitHub Actions CI 记录。

在本机复现：

```powershell
python batch_validate_tax_rag.py `
  --ask ask.py `
  --config config.json `
  --db db `
  --ingest ingest.py `
  --expected demo_expected.json `
  --out validation_demo
```

查看 `validation_demo/summary.json`。验证目录包含答案及选段日志，由 `.gitignore` 排除，不提交到仓库。

## 公开范围与项目文件

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

完整私有知识库文档、真实的 65 条路径标准答案、数据库和原始验收日志没有放入本仓库。仓库中的 `db/` 由本地建库生成并被忽略。

演示答案采用简化事实，仅用于展示程序行为。实际税务判断须核实适用期间、主体、交易事实及现行法规。
