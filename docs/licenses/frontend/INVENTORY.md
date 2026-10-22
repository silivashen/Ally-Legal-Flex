# 前端第三方许可快照

核查日期：2026-10-18。

本目录保存当前本地安装包随附的许可文本，按原始字节复制，保留原文件名、版权文字及换行。实际版本已与根目录 `package-lock.json` 对照。上游仓库链接来自各包的 `package.json.repository`，用于识别来源；本次收录的具体许可文本以对应本地安装版本为来源，不以仓库当前分支替代旧版本授权。

## 范围

- 收录根目录 `package.json` 声明的 3 个直接运行依赖及其递归 `dependencies`，共 4 个已安装包。
- 收录根目录声明的 23 个直接开发依赖自身许可；没有穷尽其全部间接依赖。
- 另收录本次关注的 `caniuse-lite`、`node-forge` 两个间接开发依赖的随包许可全文，并记录 `tree-dump` 的待核实项。
- 这是有限依赖快照，不是最终浏览器 bundle、安装包或 Docker 镜像的完整分发审计。是否进入分发物，应在实际发布构建后另行核对；本次没有打包。
- 此处的 MIT 声明仅对应表中第三方包，不能替代上游 Ally 项目的许可说明，也不覆盖 Office.js CDN 库或 Fabric 的字体、图标资产。

## 运行依赖

`core-js`、`regenerator-runtime` 是 `webpack.config.js` 的 polyfill 入口；`@azure/msal-browser` 仍被 `src/taskpane/taskpane.js` 导入。`@azure/msal-common` 为 MSAL Browser 的间接运行依赖。前三者来自 `node_modules/<包名>`；本快照的 MSAL Common 来自 `node_modules/@azure/msal-browser/node_modules/@azure/msal-common`。

| 包 | 实际版本 | 许可 | 上游仓库（包内声明） | 收录全文 |
| --- | --- | --- | --- | --- |
| `core-js` | 3.37.1 | MIT | [仓库](https://github.com/zloirock/core-js) | [LICENSE](runtime/core-js-3.37.1/LICENSE) |
| `regenerator-runtime` | 0.14.1 | MIT | [仓库](https://github.com/facebook/regenerator/tree/main/packages/runtime) | [LICENSE](runtime/regenerator-runtime-0.14.1/LICENSE) |
| `@azure/msal-browser` | 3.28.0 | MIT | [仓库](https://github.com/AzureAD/microsoft-authentication-library-for-js) | [LICENSE](runtime/azure-msal-browser-3.28.0/LICENSE) |
| `@azure/msal-common` | 14.16.0 | MIT | [仓库](https://github.com/AzureAD/microsoft-authentication-library-for-js) | [LICENSE](runtime/azure-msal-common-14.16.0/LICENSE) |

## 直接开发依赖

下列包来自 `node_modules/<包名>`，在根目录 `package.json.devDependencies` 声明，服务于构建、调试、类型检查、开发服务器及相关工具。`devDependencies` 分类本身不证明某个包绝不会被再分发；若未来发布开发工具环境，仍需核对其中实际包含的第三方文件。

| 包 | 实际版本 | 许可 | 上游仓库（包内声明） | 收录全文 |
| --- | --- | --- | --- | --- |
| `@babel/core` | 7.24.7 | MIT | [仓库](https://github.com/babel/babel) | [LICENSE](development/babel-core-7.24.7/LICENSE) |
| `@babel/preset-env` | 7.24.7 | MIT | [仓库](https://github.com/babel/babel) | [LICENSE](development/babel-preset-env-7.24.7/LICENSE) |
| `@types/office-js` | 1.0.396 | MIT | [仓库](https://github.com/DefinitelyTyped/DefinitelyTyped) | [LICENSE](development/types-office-js-1.0.396/LICENSE) |
| `@types/office-runtime` | 1.0.35 | MIT | [仓库](https://github.com/DefinitelyTyped/DefinitelyTyped) | [LICENSE](development/types-office-runtime-1.0.35/LICENSE) |
| `acorn` | 8.12.0 | MIT | [仓库](https://github.com/acornjs/acorn) | [LICENSE](development/acorn-8.12.0/LICENSE) |
| `babel-loader` | 9.1.3 | MIT | [仓库](https://github.com/babel/babel-loader) | [LICENSE](development/babel-loader-9.1.3/LICENSE) |
| `copy-webpack-plugin` | 12.0.2 | MIT | [仓库](https://github.com/webpack-contrib/copy-webpack-plugin) | [LICENSE](development/copy-webpack-plugin-12.0.2/LICENSE) |
| `eslint-plugin-office-addins` | 2.1.8 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [LICENSE](development/eslint-plugin-office-addins-2.1.8/LICENSE) |
| `file-loader` | 6.2.0 | MIT | [仓库](https://github.com/webpack-contrib/file-loader) | [LICENSE](development/file-loader-6.2.0/LICENSE) |
| `html-loader` | 5.0.0 | MIT | [仓库](https://github.com/webpack-contrib/html-loader) | [LICENSE](development/html-loader-5.0.0/LICENSE) |
| `html-webpack-plugin` | 5.6.0 | MIT | [仓库](https://github.com/jantimon/html-webpack-plugin) | [LICENSE](development/html-webpack-plugin-5.6.0/LICENSE) |
| `office-addin-cli` | 1.6.3 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [License](development/office-addin-cli-1.6.3/License) |
| `office-addin-debugging` | 5.1.3 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [License](development/office-addin-debugging-5.1.3/License) |
| `office-addin-dev-certs` | 1.13.3 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [License](development/office-addin-dev-certs-1.13.3/License) |
| `office-addin-lint` | 2.3.3 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [LICENSE](development/office-addin-lint-2.3.3/LICENSE) |
| `office-addin-manifest` | 1.13.3 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [LICENSE](development/office-addin-manifest-1.13.3/LICENSE) |
| `office-addin-prettier-config` | 1.2.1 | MIT | [仓库](https://github.com/OfficeDev/Office-Addin-Scripts) | [LICENSE](development/office-addin-prettier-config-1.2.1/LICENSE) |
| `os-browserify` | 0.3.0 | MIT | [仓库](https://github.com/CoderPuppy/os-browserify) | [LICENSE](development/os-browserify-0.3.0/LICENSE) |
| `process` | 0.11.10 | MIT | [仓库](https://github.com/shtylman/node-process) | [LICENSE](development/process-0.11.10/LICENSE) |
| `source-map-loader` | 5.0.0 | MIT | [仓库](https://github.com/webpack-contrib/source-map-loader) | [LICENSE](development/source-map-loader-5.0.0/LICENSE) |
| `webpack` | 5.92.1 | MIT | [仓库](https://github.com/webpack/webpack) | [LICENSE](development/webpack-5.92.1/LICENSE) |
| `webpack-cli` | 5.1.4 | MIT | [仓库](https://github.com/webpack/webpack-cli) | [LICENSE](development/webpack-cli-5.1.4/LICENSE) |
| `webpack-dev-server` | 5.0.3 | MIT | [仓库](https://github.com/webpack/webpack-dev-server) | [LICENSE](development/webpack-dev-server-5.0.3/LICENSE) |

## 间接开发依赖中的特殊项

| 包 | 实际版本 | 许可 | 上游仓库（包内声明） | 收录全文 |
| --- | --- | --- | --- | --- |
| `caniuse-lite` | 1.0.30001636 | CC-BY-4.0 | [仓库](https://github.com/browserslist/caniuse-lite) | [LICENSE](special-development/caniuse-lite-1.0.30001636/LICENSE) |
| `node-forge` | 1.3.1 | (BSD-3-Clause OR GPL-2.0) | [仓库](https://github.com/digitalbazaar/forge) | [LICENSE](special-development/node-forge-1.3.1/LICENSE) |

- `caniuse-lite 1.0.30001636`：锁文件标注 `dev: true`，属于浏览器兼容性数据；其 CC-BY-4.0 许可不能按 MIT 代替。
- `node-forge 1.3.1`：锁文件标注 `dev: true`，由开发证书相关工具使用。随包 LICENSE 明确可选择 BSD-3-Clause 或 GPL-2.0；本项目拟按 BSD-3-Clause 路径使用并保留所需声明。为完整保留来源，此处逐字收录原包包含双重许可的整份文件；这不表示本项目改用 GPL。
- `tree-dump 1.0.1`：锁文件标注 `dev: true`，由 `memfs 4.9.3` 引入，是开发工具的间接依赖。本地 `node_modules/tree-dump/package.json` 没有 `license` 字段，且未随包找到 LICENSE 文件。进一步核对[官方 npm 1.0.1 元数据](https://registry.npmjs.org/tree-dump/1.0.1)：也没有 `license` / `licenses`，`gitHead` 为 `58984f5c70ef04bf11849b6c717cc00d92fd41ef`；GitHub 的 `v1.0.1` 标签对应同一提交，且[该提交根目录](https://github.com/streamich/tree-dump/tree/58984f5c70ef04bf11849b6c717cc00d92fd41ef)没有 LICENSE 文件。虽然[官方仓库当前分支](https://github.com/streamich/tree-dump)展示 Apache-2.0，仍未取得能覆盖 1.0.1 发布版本的明确许可文本，故旧版本许可保持**待核实**。没有将当前分支的许可直接追溯套用到此版本，也未安装、升级或替换该包。
- 锁文件中的旧版 `regjsparser/node_modules/jsesc 0.5.0` 未写入 `license` 字段，但本地包的 `package.json.licenses` 和 `LICENSE-MIT.txt` 可核实为 MIT；属于本次未全面收录的间接开发依赖。

## CDN 资源边界

- `src/taskpane/taskpane.html`、`src/configpane/configpane.html` 和 `src/commands/commands.html` 从微软 CDN 引用 Office.js。运行库适用[微软 Office.js 专用许可](https://github.com/OfficeDev/office-js/blob/release/LICENSE.md)；`@types/office-js` 的 MIT 许可仅覆盖该类型包。
- Taskpane 和 Config 页面引用 Fabric Core 11.0.0 CSS。其[官方说明](https://github.com/OfficeDev/office-ui-fabric-core#licenses)将仓库代码的 MIT 许可与 CDN 字体、图标的独立资产许可区分。它们不在上述 npm 许可快照覆盖范围内。

更新依赖、替换 CDN 或制作分发包时，应更新本快照及根目录第三方声明，并按实际分发内容补齐间接依赖和资源的许可资料。
