# 一键安装工具来源

本次源码包和 Setup ZIP 不内置运行工具二进制文件；首次安装时从下列来源下载。下载到用户电脑的组件仍适用自身许可，安装程序保留 Node.js 解压目录中的 LICENSE 及 Python 安装中的许可文件。

| 组件 | 安装版本与来源 | 许可资料 |
| --- | --- | --- |
| uv | [Astral 官方 0.13.4 发布](https://github.com/astral-sh/uv/releases/tag/0.13.4) | MIT OR Apache-2.0；从对应 tag 取得的 [MIT](uv-0.13.4-LICENSE-MIT.txt) 与 [Apache-2.0](uv-0.13.4-LICENSE-APACHE.txt) 原文均保留。 |
| Node.js | [官方 v22.23.4 下载](https://nodejs.org/dist/v22.23.4/) | 原包中的 LICENSE 含 Node.js 及其附带组件的声明；参见[该版本官方 LICENSE](https://github.com/nodejs/node/blob/v22.23.4/LICENSE)。 |
| CPython | uv 管理的 Python 3.11，具体补丁版本由首次安装时可用版本决定 | 来自 Astral 的 [python-build-standalone](https://github.com/astral-sh/python-build-standalone)，参见[分发许可说明](https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html#licensing)。不是本项目自行编译或自行授权的 Python 发行版。 |

uv 和 Node.js 的下载地址及 SHA256 固定在 [runtime-downloads.json](../../../scripts/runtime-downloads.json)。Python 和项目 Python 依赖未锁定到补丁版本，原有依赖范围保持不变；安装后应以实际组件携带的许可为准。如将来改为预装离线包，需要按实际捆绑内容重新整理许可清单。

整理日期：2026-10-21。
