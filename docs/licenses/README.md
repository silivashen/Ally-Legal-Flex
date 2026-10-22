# 许可正文与来源记录

整理日期：2026-10-18。项目级说明见[第三方版权与许可声明](../../THIRD_PARTY_NOTICES.md)，新增及修改部分的 MIT 正文见[根目录 LICENSE](../../LICENSE)。

本目录保存已经核对的第三方许可原文和版本来源；本项目自己的 MIT 不替代这些文件。多数文件逐字复制自当前安装包，少数从官方仓库取得，分别列明。上游通知中的版权人、年份和旧依赖说明均保持原样，不用本项目署名替换。

## 依赖包资料

- [一键安装工具](runtime-tools/README.md)：uv、Node.js 和 uv 管理的 Python 的来源及许可说明；Setup ZIP 首次联网下载这些工具，不内置其二进制文件。
- [前端清单](frontend/INVENTORY.md)：4 个运行依赖、23 个直接开发依赖及 2 个特殊间接开发依赖的许可文件；另有待核实项。
- [Python 清单](python/INVENTORY.md)：PromptFlow、OpenAI SDK、certifi 的实际版本、许可文件及适用的 NOTICE。

这些是整理时的有限版本快照。更新依赖或生成分发物后，应按实际包含的版本及文件更新清单，不能把本目录当成任意后续产物的完整许可清单。

## 上游模板及外部资源

| 收录文件 | 原始来源（固定提交） | 说明 |
| --- | --- | --- |
| [office-addin-template-LICENSE.txt](upstream/office-addin-template-LICENSE.txt) | [OfficeDev/Office-Addin-TaskPane-JS](https://github.com/OfficeDev/Office-Addin-TaskPane-JS/blob/1f773e8814105f85547799dc8bd6107080cdc556/LICENSE) | 保留微软插件模板的版权和 MIT 正文。不是上游 Ally 仓库原本存在独立 LICENSE 文件的证明，也不推定整个 Ally 仓库的单一版权所有人。 |
| [fabric-core-LICENSE.txt](external/fabric-core-LICENSE.txt) | [OfficeDev/office-ui-fabric-core](https://github.com/OfficeDev/office-ui-fabric-core/blob/d2df16513baae2b1daa6d560f9c5822b1756d936/LICENSE) | 官方仓库许可快照，原文包含字体及图标资产许可入口；项目引用的 CSS 为 CDN 11.0.0，未将该 CDN 版本与此提交等同。 |
| [office-js-LICENSE.md](external/office-js-LICENSE.md) | [OfficeDev/office-js](https://github.com/OfficeDev/office-js/blob/498e88261bc578243d40dd79083953d86f84e7f6/LICENSE.md) | 官方 release 分支许可快照；Office.js 本体适用专门的软件条款，不是 MIT。 |

上述 3 份原文通过 GitHub 官方仓库内容接口取得，未改写版权、条件或免责声明。只收录许可资料，不在此目录复制 Office.js、字体、图标或模型权重。
