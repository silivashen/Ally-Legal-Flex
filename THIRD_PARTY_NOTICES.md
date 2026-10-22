# Third Party Copyright and License Notices

Project: Ally Legal Flex 1.0.0. Updated on: 2026-10-21.

This project modifies the upstream Ally project and uses third-party software and resources. The root [LICENSE](LICENSE) applies the MIT License to additions and modifications that Silvia Shen is entitled to license. It does not replace copyright notices, licenses, or other applicable terms for upstream code or third-party components.

This file and [docs/licenses](docs/licenses/README.md) document sources and provide the license texts collected during the review. Package versions are based on the lockfile and local installation examined at that time. They do not establish the versions or licensing of future installations or release artifacts that have not yet been produced. Incomplete findings are marked for verification; no third-party permissions are invented.

## 1. Upstream Ally and Microsoft template code

Source: [Azure-Samples/ally-legal-assistant](https://github.com/Azure-Samples/ally-legal-assistant). The upstream commit examined was [166c4a4b881be49bc9f8b3a92bbb3689a1ace9a7](https://github.com/Azure-Samples/ally-legal-assistant/tree/166c4a4b881be49bc9f8b3a92bbb3689a1ace9a7). This identifies the version used to check licensing materials; it does not mean that this local fork has been compared with that commit file by file.

The upstream [package.json](https://github.com/Azure-Samples/ally-legal-assistant/blob/166c4a4b881be49bc9f8b3a92bbb3689a1ace9a7/package.json) declares `"license": "MIT"`. The original rights statement from the upstream README is retained below:

> This plugin is free to use and modify by anyone. The GitHub repository is also free to use and change.

Original project team:

- Esther Dediashvili — Senior Solution Specialist – AI Global Black Belt, EMEA
- Lior Armiev — Senior Technical Specialist – AI Global Black Belt, EMEA
- Andrew Mackay — AI Director – Global Black Belts, CEMA

Existing Microsoft copyright and license headers remain unchanged in the local source, including [commands.js](src/commands/commands.js), [commands.html](src/commands/commands.html), [configpane.html](src/configpane/configpane.html), [configpane.css](src/configpane/configpane.css), and [taskpane.css](src/taskpane/taskpane.css). The copyright notice reads:

> Copyright (c) Microsoft Corporation. All rights reserved. Licensed under the MIT license.

HTML files retain their original capitalization of `MIT License`. These notices have not been replaced with this fork's attribution. The Microsoft add-in template's [MIT license text and copyright notice](docs/licenses/upstream/office-addin-template-LICENSE.txt) are retained separately; see the [license directory](docs/licenses/README.md) for their source. That template file is not used to infer the copyright owner or year of every upstream file.

Ally Legal Flex is independently maintained by this fork's maintainer. Microsoft and the original project team are not responsible for maintaining, updating, or supporting this fork. Its functional changes are described in the [Chinese user guide](USER_GUIDE.zh-CN.md#project-background).

## 2. Runtime software dependencies

The following entries describe the installed versions examined. Copyright holders, license texts, and applicable NOTICE provisions are given in the original files linked below.

| Component | Version examined | License | Collected materials |
| --- | --- | --- | --- |
| core-js | 3.37.1 | MIT | [Full license](docs/licenses/frontend/runtime/core-js-3.37.1/LICENSE) |
| regenerator-runtime | 0.14.1 | MIT | [Full license](docs/licenses/frontend/runtime/regenerator-runtime-0.14.1/LICENSE) |
| @azure/msal-browser | 3.28.0 | MIT | [Full license](docs/licenses/frontend/runtime/azure-msal-browser-3.28.0/LICENSE) |
| @azure/msal-common (transitive dependency) | 14.12.0 | MIT | [Full license](docs/licenses/frontend/runtime/azure-msal-common-14.16.0/LICENSE) (collected from 14.16.0; same MIT text) |
| PromptFlow and its core, devkit, and tools packages | 1.18.5; `promptflow-tools` is not installed in this environment | MIT | [Version, license, and NOTICE inventory](docs/licenses/python/INVENTORY.md) |
| OpenAI Python SDK | 3.36.0 | Apache-2.0 | [Full license](docs/licenses/python/openai-3.33.0/LICENSE) (collected from 3.33.0; same Apache-2.0 text) |
| certifi (transitive dependency) | 2026.10.19 | MPL-2.0; see the original file for component details | [Original license file](docs/licenses/python/certifi-2026.7.22/LICENSE) (collected from 2026.7.22; same MPL-2.0 text) |

The [frontend inventory](docs/licenses/frontend/INVENTORY.md) records source repositories, actual installation locations, and licenses for frontend packages. The [Python inventory](docs/licenses/python/INVENTORY.md) records backend references, license sources, and version ranges. Direct Python requirements are pinned in `requirements.txt`; transitive versions are still resolved at install time, so verify the actual versions and update these materials after reinstalling. Where a retained license file was collected from an earlier patch release of the same component, the table states both versions: the license text is unchanged, but the version examined and the retained snapshot do not match exactly. The certifi entry records a specific transitive licensing case found during the review. It does not mean that all Python transitive dependencies have been collected.

## 3. Externally loaded Office.js and interface resources

| Resource | Current use | Licensing information |
| --- | --- | --- |
| Office.js | Loaded from Microsoft's `appsforoffice.microsoft.com/lib/1.1/hosted/office.js`; this URL does not identify a fixed patch version | Subject to the [Microsoft Office.js software license terms](docs/licenses/external/office-js-LICENSE.md), rather than this project's MIT License. The MIT license for `@types/office-js` covers only the type definitions package. |
| Office UI Fabric Core 11.0.0 | CSS loaded from Microsoft's CDN by Taskpane and Config | Repository code is MIT-licensed; the [official license text](docs/licenses/external/fabric-core-LICENSE.txt) is retained. Referenced fonts and icons are subject to separate asset terms. |

The [official Fabric licensing information](https://github.com/OfficeDev/office-ui-fabric-core#licenses) distinguishes code from font and icon assets. Asset terms are available through the [Fabric assets license](https://aka.ms/fabric-assets-license). The retained Office.js and Fabric license files are snapshots from the official repositories at the time of review; the commits are recorded in the [source records](docs/licenses/README.md). These snapshots do not pin the CDN content to those commits or grant redistribution rights beyond the original terms.

Icons in `assets/` and architecture diagrams and demonstration images in `files/` retain their upstream provenance. They are not claimed as original work by Silvia Shen, and no trademark permission has been added for any marks they may contain. Model service APIs and user-selected models are separately subject to their service terms. This project's MIT License does not grant rights to use model weights or services.

## 4. Development tools and specific transitive dependencies

The [frontend inventory](docs/licenses/frontend/INVENTORY.md) also lists 23 direct development dependencies and retains the MIT texts supplied with their installed versions. `devDependencies` is a usage classification; it does not establish that a component cannot enter a distributed artifact.

- `caniuse-lite 1.0.30001636`: CC-BY-4.0. The [original license](docs/licenses/frontend/special-development/caniuse-lite-1.0.30001636/LICENSE) is retained.
- `node-forge 1.3.1`: The original package offers a choice of BSD-3-Clause or GPL-2.0. This project uses the BSD-3-Clause option and retains the [complete original license](docs/licenses/frontend/special-development/node-forge-1.3.1/LICENSE). This does not change this project's license to GPL.
- `tree-dump 1.0.1`: Introduced through the development dependency `memfs`. Neither the local package nor the official npm metadata for that version provides a license field, and the root of the commit referenced by its matching Git tag has no LICENSE file. Its licensing is therefore **pending verification**. The current upstream branch's Apache-2.0 declaration has not been applied retroactively to that older version, and the package has not been labeled MIT. Version and source evidence is recorded in the frontend inventory.

## 5. Retention and scope of review

When distributing this project's source, retain this file, the applicable [LICENSE](LICENSE), the materials under [docs/licenses](docs/licenses/README.md), and the existing copyright headers in source files. Preserve the meaning of third-party LICENSE, NOTICE, and other licensing texts. This file does not add to or reduce those terms.

This review covers upstream notices, direct frontend runtime dependencies and their recursive dependencies, direct development dependencies, and selected Python and other transitive dependencies. The original licensing review did not produce a preinstalled runtime bundle or Docker image, and does not claim that every transitive dependency has been reviewed. The network-assisted Setup ZIPs described below download dependencies during installation rather than bundling those binaries.

For future frontend artifacts or images, complete the licensing materials for the software actually included and distribute those materials with the artifact. Build files were not changed as part of this documentation review; do not assume that newly added license files in the source directory are automatically copied into build artifacts. Additional components installed by Docker and the Miniconda base image must be checked against the final versions used. Compressing an entire project directory does not automatically respect `.gitignore`; local dependency environments, contracts, and model configurations should not be included in a distribution.

## 6. Setup runtime tools

The source and network-assisted setup ZIPs include bootstrap scripts, not preinstalled runtime binaries. Setup downloads uv 0.13.4 and Node.js v22.23.4 from their official releases with pinned SHA256 checksums, and obtains managed Python 3.11 through uv. uv is MIT OR Apache-2.0; its original license texts and the Node.js / Python distribution sources are recorded in the [runtime tool notices](docs/licenses/runtime-tools/README.md). Installed distributions retain their own license files. This project’s MIT License does not replace those terms.
