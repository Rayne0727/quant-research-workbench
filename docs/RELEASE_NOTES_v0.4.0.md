# Quant Research Workbench v0.4.0

v0.4.0 为 Direct Standard Return、Direct NAV、Generic Return 和 Generic NAV 四条单实验路径增加 Research Bundle ZIP。分析成功后，用户可以保留原有三个独立下载，也可以下载一份固定结构的研究包进行归档、复现辅助和完整性核验。

## 研究包内容

研究包文件名为 `qrw_bundle_<run_id 前 16 位>.zip`，成员及顺序固定为：

1. `analysis_report.md`
2. `standardized_data.csv`
3. `run_manifest.json`
4. `bundle_index.json`

前三个成员直接复用同一次页面渲染中的 standalone exact bytes。`bundle_index.json` 使用 `qrw-research-bundle-index-v1`，记录前三个成员的媒体类型、实际字节长度和 SHA-256；它不记录自身、不创建 `bundle_id`，也不改变 `analysis_id` 或 `run_id`。

## 确定性与隐私边界

ZIP 固定成员顺序、时间戳、普通文件权限 metadata、空 comment，并使用 `ZIP_STORED`。相同 builder、相同 ordered member bytes 和相同 metadata 会生成相同 ZIP bytes；相同 IDs 在不同环境下不保证具有相同 ZIP SHA。

研究包默认不包含原始上传文件、原始来源字节、绝对路径、session、browser 或 widget metadata。报告可能包含用户填写的策略名称和研究备注，标准化 CSV 也可能包含敏感研究数据，分享前应自行核对内容和授权范围。

## 工程质量

新增 `src/research_bundle.py` 纯内存 typed packaging boundary，并从首日进入 `mypy --strict`。正式 typed boundary 从 15 个模块扩展到 16 个模块；自动化测试覆盖固定 ZIP 结构、exact-byte equality、index SHA、四条 Manifest 路径、metadata、安全路径、隐私边界和 Streamlit 成功/阻断状态。

## 范围边界

v0.4.0 不修改绩效、NAV、benchmark、mapping、standardization、comparison、报告、标准化 CSV 或 Run Manifest identity 合同；不包含原始来源研究包、comparison bundle、B.3 或新的安全阶段。Tag 和 GitHub Release 只能在合并后的正式线上验收通过后创建。
