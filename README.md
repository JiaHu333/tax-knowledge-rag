# 德国税务固定菜单知识库｜公开演示

[English](README_EN.md) | 中文

这是一个可在本地运行的微型演示，用于展示如何把需要明确条件的德国税务问题拆成固定菜单，并从结构化文档中精确读取已编写的答案。

公开仓库只包含 2 个示例主题和 8 条演示路径。完整私有知识库、真实标准答案、Chroma 数据库以及原始验证日志均不在仓库中。

## 公开演示范围

| 主题 | 场景 | 税种 |
| --- | --- | --- |
| VAT 发票形式审查 | 信息完整；缺少必要信息 | VAT |
| 公司承担员工培训费用 | 明确业务关联；主要私人兴趣 | VAT、CIT、Payroll |

演示数据为本仓库重新编写，没有从私有知识库复制正文。内容采用简化事实，仅用于展示软件行为；官方资料链接见 [SOURCES.md](SOURCES.md)。

## 工作方式

1. `ingest.py` 读取 `docs/CN`，按 Markdown 标题切分，并将文本和元数据写入本地 Chroma。
2. `ask.py` 从 `config.json` 读取菜单结构。
3. 用户依次选择主题、场景和税种。
4. 程序按来源文件、场景标题和税种标题精确选择答案。
5. 答案直接来自文档，不经过语言模型改写。

Ollama 的 `nomic-embed-text` 用于建库。当前固定菜单查询使用 Chroma 保存的文本和元数据，不执行向量相似度检索。

## 项目结构

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
└── docs/
    └── CN/
        ├── employee_training_demo_cn.md
        └── vat_invoice_demo_cn.md
```

`db/` 由本机运行 `ingest.py` 后生成，并由 `.gitignore` 排除。

## 安装

```powershell
conda create -n tax-kb-demo python=3.11
conda activate tax-kb-demo
pip install -r requirements.txt
ollama pull nomic-embed-text
```

## 建库并运行

在仓库根目录执行：

```powershell
python ingest.py --docs docs --db db
python ask.py --config config.json --db db
```

输入 `exit`、`quit` 或 `q` 可退出。

## 批量验证

```powershell
python batch_validate_tax_rag.py `
  --ask ask.py `
  --config config.json `
  --db db `
  --ingest ingest.py `
  --expected demo_expected.json `
  --out validation_demo
```

预期结果：8 条路径全部为 `passed`，输出方式均为 `Python`。验证结果目录包含答案和选段内容，因此默认不提交到 GitHub。

## 数据边界

- 公开：通用程序、演示配置、2 份演示文档、8 条演示基线。
- 私有：完整知识库文档、65 条真实验收基线、本地数据库及详细验证日志。
- `passed` 只表示程序输出与演示基线一致，不代表独立税务审计。

## 税务说明

本项目用于展示知识管理、检索流程和软件实现。演示答案不能替代针对具体事实进行的专业税务咨询或法律意见。实际应用前应核实适用期间、主体、交易事实及最新法规。
