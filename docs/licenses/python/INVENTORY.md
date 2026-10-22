# Python 依赖许可资料

核查日期：2026-10-18。版本来源：本机 `.venv-mac/lib/python3.12/site-packages/` 的已安装包元数据。

本目录收录当前活跃后端的直接第三方依赖、相关 PromptFlow 组件，以及已识别的间接依赖 certifi 的许可资料。它是本机环境的有限快照，不是完整的依赖清单，也不代表未来安装或 Docker 镜像最终包含的全部软件。

## 已收录组件

| 组件 | 本机版本 | 元数据中的许可 | 项目引用位置或依赖关系 | 来源仓库 | 本地许可资料 |
| --- | --- | --- | --- | --- | --- |
| promptflow | 1.18.5 | MIT | [requirements.txt](../../../backend/PromptFlow/legal-main-flow/requirements.txt) 的直接依赖；主流程使用 `promptflow` 命名空间 | [microsoft/promptflow](https://github.com/microsoft/promptflow) | [LICENSE](promptflow-1.18.5/LICENSE)、[NOTICE.txt](promptflow-1.18.5/NOTICE.txt) |
| promptflow-core | 1.18.5 | MIT | `promptflow` 的依赖；[documen_summary.py](../../../backend/PromptFlow/legal-main-flow/documen_summary.py) 等使用 `promptflow.core.tool`、`promptflow.connections.CustomConnection` | [microsoft/promptflow](https://github.com/microsoft/promptflow) | [LICENSE](promptflow-core-1.18.5/LICENSE) |
| promptflow-devkit | 1.18.5 | MIT | `promptflow` 的依赖；[启动器](../../../scripts/start_ally.py) 使用 PromptFlow 命令行服务 | [microsoft/promptflow](https://github.com/microsoft/promptflow) | [LICENSE](promptflow-devkit-1.18.5/LICENSE) |
| promptflow-tools | 1.6.1 | MIT | 本机 PromptFlow 环境中的工具组件；当前活跃项目源码未直接导入该包 | [microsoft/promptflow](https://github.com/microsoft/promptflow) | [LICENSE](promptflow-tools-1.6.1/LICENSE)、[NOTICE.txt](promptflow-tools-1.6.1/NOTICE.txt) |
| openai | 3.33.0 | Apache-2.0 | [requirements.txt](../../../backend/PromptFlow/legal-main-flow/requirements.txt) 的直接依赖；[model_config_loader.py](../../../backend/PromptFlow/legal-main-flow/model_config_loader.py)、[search_doc.py](../../../backend/PromptFlow/legal-main-flow/search_doc.py) 等导入 `OpenAI` 客户端 | [openai/openai-python](https://github.com/openai/openai-python) | [LICENSE](openai-3.33.0/LICENSE) |
| certifi | 2026.7.22 | MPL-2.0 | 间接依赖；本机元数据可追溯到 `promptflow-devkit → httpx → certifi`，项目源码未直接导入 | [certifi/python-certifi](https://github.com/certifi/python-certifi) | [LICENSE](certifi-2026.7.22/LICENSE) |

## 原文来源与保留方式

所有收录的许可文件和 NOTICE 均保留来源原文，没有翻译、删改或用本项目的 MIT 声明替换。

- `promptflow-1.18.5/NOTICE.txt` 逐字复制自已安装包的 `promptflow-1.18.5.dist-info/NOTICE.txt`。
- `promptflow-tools-1.6.1/NOTICE.txt` 逐字复制自已安装包的 `promptflow_tools-1.6.1.dist-info/licenses/NOTICE.txt`。
- `openai-3.33.0/LICENSE` 逐字复制自已安装包的 `openai-3.33.0.dist-info/licenses/LICENSE`。
- `certifi-2026.7.22/LICENSE` 逐字复制自已安装包的 `certifi-2026.7.22.dist-info/licenses/LICENSE`。该文件保留了 Mozilla 证书包的声明及 MPL 2.0 正文链接；[Mozilla 官方 MPL 2.0 正文](https://www.mozilla.org/en-US/MPL/2.0/) 可供查阅。
- 本机上述 PromptFlow 包没有单独附带 `LICENSE` 文件，core/devkit 也没有单独的 `NOTICE` 文件。本目录的四份 PromptFlow `LICENSE` 均逐字取自 [Microsoft 官方仓库的 LICENSE](https://github.com/microsoft/promptflow/blob/3928a727b406e66d64ff42621534bb58e0ca18ce/LICENSE)，固定提交为 `3928a727b406e66d64ff42621534bb58e0ca18ce`，文件 Git blob 为 `9e841e7a26e4eb057b24511e7b92d42b257a80e5`。这是核查日期取得的官方许可正文，与本机包元数据的 MIT 标识一致；没有将该提交冒称为上述包版本的发布标签，也没有将补充文件称为 wheel 自带文件。

PromptFlow 原始 NOTICE 可能列出旧版本依赖或通用说明，已原样保留。它不构成本项目当前依赖版本的锁定清单，不能用其中的旧版本许可替代实际安装版本的许可；例如本机 OpenAI Python 客户端采用上表列明的 Apache-2.0。

## 核查边界

已静态核查 `backend/PromptFlow/legal-main-flow/` 的 Python 源码，以及 `model_config_server.py`、`index_server.py`、`local_api_security.py`、`scripts/start_ally.py`。这些活跃项目代码直接导入的第三方 Python 命名空间为 `promptflow` 和 `openai`。没有发现它们直接导入 Flask、requests 或 NumPy，因此本次没有把这些仅存在于本机依赖环境中的包扩展为逐项收录对象。

仓库内保留的其他历史流程，以及全部间接依赖、测试工具和开发工具，不在本次逐项收录范围内；后续若将其作为运行功能或发布内容，应补充核查。Python 标准库也不在此表逐项列出。

[主流程 requirements.txt](../../../backend/PromptFlow/legal-main-flow/requirements.txt) 和 [Docker requirements.txt](../../../backend/Docker/legal-main-flow-container/flow/requirements.txt) 目前只列出 `promptflow`、`openai`，没有锁定版本。因此重新安装后的版本和许可资料需要重新确认，本目录不能替代锁定依赖或针对实际发布物的核查。

## Docker 发布前另行核查

当前 [Dockerfile](../../../backend/Docker/legal-main-flow-container/Dockerfile) 还使用 `continuumio/miniconda3:latest` 基础镜像，并安装 `keyrings.alt`、`gunicorn`、`uvicorn` 和系统软件。基础镜像、Conda 渠道、系统软件以及最终解析出的 Python 依赖均需要在实际构建和分发镜像时按确定版本核查。本次没有构建镜像，也没有生成镜像依赖或许可全清单。

本地虚拟环境已由 [.gitignore](../../../.gitignore) 排除，Docker 构建上下文由 [.dockerignore](../../../backend/Docker/legal-main-flow-container/.dockerignore) 的白名单限制。手工压缩整个项目目录不会自动遵守这些规则；本目录收录许可资料不意味着可以把本机依赖环境一并无条件分发。
