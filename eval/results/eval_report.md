# ResearchOS 评估报告

生成时间：2026-10-22T00:49:01.048711+00:00  
配置：embedding=`hash`，min_term_coverage=0.5，min_vector_sim=0.55，chunk=700/120

## 指标汇总

| 指标 | 结果 |
|---|---|
| 检索召回率 recall@5 | 100.0% |
| MRR@10 | 1.000 |
| Top-1 来源准确率 | 100.0% |
| 关键事实出现在所选证据中 | 100.0% |
| 引用完整性（引用→真实文档/页码/原文） | 100.0%（检查 22 条） |
| 无答案问题的拒答率 | 100.0% |
| 可回答问题被误拒率 | 0.0% |
| 比较功能文档覆盖率 | 100.0% |

## 文档处理

| 文件 | 状态 | 页数 | 分块 | 说明 |
|---|---|---|---|---|
| kx200_field_notes_en.md | ready | 1 | 2 |  |
| kx200_incident_report_2023.pdf | ready | 4 | 4 |  |
| kx200_revised_report_2024.pdf | ready | 4 | 4 |  |
| kx200_vendor_bulletin.docx | ready | 2 | 2 |  |
| maintenance_team_memo.md | ready | 1 | 1 |  |
| operation_log_summary.txt | ready | 2 | 2 |  |
| scanned_inspection_sheet.pdf | needs_ocr | - | 0 | PDF 共 1 页，均为图像且没有可提取的文本层（可能是扫描件），需要先进行 OCR 处理 |

## 可回答问题

| ID | 问题 | 首个正确来源排名 | Top-1 | 关键事实命中 | 状态 |
|---|---|---|---|---|---|
| A1 | KX-200 轴承过热的根本原因是什么？ | 1 | kx200_revised_report_2024.pdf p.2 | ✅ | llm_unavailable |
| A2 | 修订报告建议的补脂周期是多少运行小时？ | 1 | kx200_revised_report_2024.pdf p.4 | ✅ | llm_unavailable |
| A3 | 初步调查报告建议的补脂周期是多少？ | 1 | kx200_incident_report_2023.pdf p.3 | ✅ | llm_unavailable |
| A4 | 故障发生前驱动端轴承振动速度上升到多少？ | 1 | operation_log_summary.txt p.1 | ✅ | llm_unavailable |
| A5 | 高温工况下应该使用什么润滑脂？ | 1 | kx200_vendor_bulletin.docx p.2 | ✅ | llm_unavailable |
| A6 | 故障轴承的金相与硬度检验结果如何？ | 1 | kx200_revised_report_2024.pdf p.3 | ✅ | llm_unavailable |
| A7 | 维护班组认为轴承过热的真正原因是什么？ | 1 | maintenance_team_memo.md p.1 | ✅ | llm_unavailable |
| A8 | 激光对中校正后轴承温度稳定在多少？ | 1 | operation_log_summary.txt p.2 | ✅ | llm_unavailable |
| A9 | What was the bearing overheating at Site 7 linked to? | 1 | kx200_field_notes_en.md p.1 | ✅ | llm_unavailable |
| A10 | 故障时轴承温度达到了多少度？ | 1 | kx200_incident_report_2023.pdf p.1 | ✅ | llm_unavailable |
| A11 | 激光对中检测显示的角向不对中是多少？ | 1 | kx200_revised_report_2024.pdf p.2 | ✅ | llm_unavailable |
| A12 | 技术公告 TB-2024-07 的适用范围是什么？ | 1 | kx200_vendor_bulletin.docx p.1 | ✅ | llm_unavailable |

## 无法回答的问题

| ID | 问题 | 状态 | 是否拒答 | 最佳候选覆盖率 |
|---|---|---|---|---|
| U1 | KX-200 泵的采购价格是多少？ | insufficient_evidence | ✅ | 0.0061 |
| U2 | 该泵站的员工人数是多少？ | insufficient_evidence | ✅ | 0.1564 |
| U3 | KX-200 在海上平台的设计使用寿命是多少年？ | insufficient_evidence | ✅ | 0.123 |
| U4 | What is the warranty period of the KX-200? | insufficient_evidence | ✅ | 0.0091 |
| U5 | 供应商 B 的公司注册地址在哪里？ | insufficient_evidence | ✅ | 0.2146 |
| U6 | 事故造成的直接经济损失是多少万元？ | insufficient_evidence | ✅ | 0.0311 |

## 跨文档比较

状态：`llm_unavailable`

- kx200_incident_report_2023.pdf：有相关证据
- kx200_vendor_bulletin.docx：有相关证据
- operation_log_summary.txt：无相关证据
- kx200_revised_report_2024.pdf：有相关证据
- maintenance_team_memo.md：有相关证据
- kx200_field_notes_en.md：无相关证据

## 大模型回答评估

未运行：未配置大模型（LLM_PROVIDER=none）。以上指标均不依赖模型；配置 LLM_PROVIDER 与 LLM_API_KEY 后重新运行可评估生成回答。

> 注：
> - 默认 embedding 为离线哈希词法向量（非神经语义模型），语义/跨语言召回能力有限（例如英文现场笔记无法被中文比较问题召回）。
> - 语料与问题均由开发者编写，规模很小；检索规则（IDF 加权覆盖率、跨词二元组过滤、上下文块头）曾针对本评估暴露的失败做过修正，因此指标存在乐观偏差，不代表在真实资料上的表现。
