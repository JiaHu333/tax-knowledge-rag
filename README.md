# 德国税务固定菜单知识库｜可运行演示

[English](README_EN.md) | 中文

德国税法复杂，特殊场景常需咨询税务师；经手人离职后，同类问题可能再次耗费时间和咨询费用。本项目按场景保存既有结论和依据，供团队核对条件后复用，减少知识流失。

一个本地运行的固定菜单知识库演示：从菜单选择主题与场景，在 Chroma 中按来源文件、场景标题和税种标题精确读取已编写的答案。当前查询不接受自由提问，也不调用语言模型改写答案。

## 运行效果

下面是公开演示的一条实际菜单路径，内容已节选：

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

答案文字来自公开示例文档 [vat_invoice_demo_cn.md](docs/CN/vat_invoice_demo_cn.md)。若对应章节缺失或不唯一，程序会报错，不会改用相似内容补答。

## 程序如何工作

| 步骤 | 文件 | 作用 |
| --- | --- | --- |
| 建库 | `ingest.py`、`docs/CN/` | 按 Markdown 标题切分文档，保存正文和章节元数据到本地 Chroma；建库时使用 Ollama `nomic-embed-text` |
| 选择 | `config.json`、`ask.py` | 固定菜单限定主题、场景、税种；查询时按元数据精确定位答案，不运行向量相似度检索 |
| 输出 | `ask.py` | 直接展示文档答案，无语言模型改写 |
| 验证 | `batch_validate_tax_rag.py`、`demo_expected.json` | 逐条运行菜单路径，对照答案、来源、税种和必需条件 |

公开演示有 3 个主题、10 条路径：VAT 发票形式审查（2 条）；公司承担员工培训费用（VAT、CIT、Payroll 各 2 条）；向非员工赠送业务礼品的费用扣除（CIT，2 条）。礼品演示按同一受赠人一个经济年度内的累计成本是否超过 50 欧元区分，不覆盖 VAT 或受赠人的税务处理。这些简化示例为本仓库重新编写。官方资料见 [SOURCES.md](SOURCES.md)。

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

此前公开版的 8 条菜单路径曾在本地运行，8/8 为 `passed`，输出方式均为 `Python` 文档直读，运行错误为 0。本次新增的 2 条礼品路径尚未在 Ollama/Chroma 环境中完成端到端验收，当前版本不声称 10/10 通过。验收结果只表示程序输出与独立演示基线一致，不代表独立税务审计。目前仓库没有 GitHub Actions CI 记录。

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
