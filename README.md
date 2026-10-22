# Ally Legal Flex

Ally Legal Flex is a Microsoft Word add-in for contract analysis and review, adapted from Microsoft Azure Samples' [Ally – AI Contract Assistant](https://github.com/Azure-Samples/ally-legal-assistant). This version is designed for individual use with a locally hosted backend. Users can configure chat and embedding models, maintain review policies locally, and select Policy Sets for each contract.

The current features call OpenAI-compatible model services configured through Config. Azure AI Search and Azure OpenAI deployments are not required. Text needed for contract analysis is still sent to the model services you configure; local configuration does not mean fully offline operation.

**Current version:** Ally Legal Flex 1.0.0 (Word add-in manifest version 1.0.0.0).

**Maintainer:** Silvia Shen.

**Documentation updated:** 2026-10-22.

## Main features

| Feature | Purpose |
| --- | --- |
| **Ask** | Ask questions about the current Word contract. Relevant passages are retrieved automatically to help explain its content. |
| **Summary** | Analyze the full contract, summarize important clauses and general risks, and check compliance with the selected Policy Sets. Important risks should also appear when no company policy applies. |
| **Review & Mark-up** | Select a Policy Set, then review text selected in Word. The analysis considers applicable policies and general contractual risks. When a change is needed, review the proposed wording and choose whether to apply it with Mark-up. |
| **Config** | Use Company Policies, Model Settings and Prompt Settings to manage local review rules, model connections and the core prompts for Ask, Summary and Review. |
| **General Settings** | Set the answer language, Review Perspective, and Policy Sets for the current review. |

Summary and Review display the **Policy Set name, Policy name, and Severity** for verified policy references. In the analysis text, the backend replaces references such as "company policy 2" with wording that omits the number when it corresponds to a verified policy ID. Formal citations retain the Policy Set and Policy name. Unselected Policy Sets are not used as the basis for the current policy review. Ask does not use these company policies.

The first Ask, Summary, or Review request automatically prepares a shared local contract index. The index is reused while the contract text and numbering remain unchanged, and updated on the next request after they change. No separate Index action is needed. Ask generates and caches contract embeddings as needed; Summary analyzes the full document; Review analyzes the selection and retrieves policies. See [automatic indexing and review features in the Chinese user guide](USER_GUIDE.zh-CN.md#review-features).

## Installation and getting started

In **Company Policies**, select a Policy Set to import policies from Excel, preview changes, and append confirmed new rules. Exact duplicates are skipped; same-name conflicts must be resolved before importing. **Download Excel** exports that set for migration, and a blank template includes instructions and examples. See [policy sharing and migration](USER_GUIDE.zh-CN.md#policy-sharing).

In **Prompt Settings**, switch between Ask, Summary and Review to edit their core instructions, check their length, save changes, or restore the built-in prompt. The add-in still adds contract context, applicable selected policies and required output and citation rules. Saved prompts apply to the next request without a service restart. See [prompt settings](USER_GUIDE.zh-CN.md#prompt-settings).

For first-time setup, extract the complete package into a permanent, writable folder and double-click **[Setup-Ally.cmd](Setup-Ally.cmd)** on Windows (Intel/AMD 64-bit) or **[Setup-Ally.command](Setup-Ally.command)** on Mac (Apple Silicon/Intel). The setup downloads verified uv and Node.js releases, prepares project-local Python and dependencies, initializes the local flow connection and creates a desktop launcher. **Internet access is required for installation.** Desktop Word is required separately. No system Python or Node.js installation is needed. See the [Chinese user guide](USER_GUIDE.zh-CN.md#setup) or [manual developer installation](docs/INSTALL_MANUALLY.zh-CN.md).

Setup can be rerun after a failure and preserves model credentials, policies and custom prompts. Runtime tools live in `.ally-tools/`, the Python environment in `.venv/`, and frontend dependencies in `node_modules/`; keep the project in place after installation. This is a source-based setup ZIP, not a signed `.exe`/`.dmg` installer or an offline distribution.

The source distribution includes the user guide, README, LICENSE, third-party notices, and two sample Policy Sets containing six policies: sales contract review with the company as seller, and purchase contract review with the company as buyer. Personal `model_config.json` and `prompt_settings.json` files are excluded from Git, and the Docker build context excludes these JSON settings. Do not include API keys, installed dependencies, runtime logs or contract caches in a source ZIP. Run Setup, then enter and save your own model configuration in **Config**.

After installation:

1. **Start:** On Windows, double-click [`Start-Ally.cmd`](Start-Ally.cmd). On Mac, double-click [`Start-Ally.command`](Start-Ally.command). The first run creates a desktop launcher and starts the local services and Word. Use the desktop launcher for subsequent sessions.
2. **Configure models and policies:** Open a contract in Word and use **Config** to configure the chat model, embedding model, and local Policy Sets. See [model configuration](USER_GUIDE.zh-CN.md#model-configuration).
3. **Set up the review:** In **General Settings**, select the answer language and enter the review perspective. Before using Summary or Review, select Policy Sets that contain policies. See [review settings](USER_GUIDE.zh-CN.md#review-settings).
4. **Use the features:** Ask questions with Ask, or run Summary for an overview. To review and revise a specific clause, select its text in Word and run Review.
5. **Stop:** Save the document and wait for analysis to finish. Return to the startup window and press **Enter** to stop the services. Keep that window open while using the add-in.

Check model-generated facts, clause references, and proposed revisions against the original contract. You decide whether to apply each change.

## Documentation

Windows users can open the [Chinese user guide](使用手册.docx), [project README](README.docx), [third-party notices](THIRD_PARTY_NOTICES.docx), and [LICENSE](LICENSE.docx) directly in Word from the project root. Markdown versions remain available for GitHub and future maintenance.

The Word files listed above are snapshots and may lag behind the Markdown versions. The Markdown files in this repository are authoritative; the Word copies are not regenerated on every documentation change.

## Security

- **Reporting a problem:** please report vulnerabilities privately as described in [SECURITY.md](SECURITY.md) rather than opening a public issue.
- **Data handling and known limitations:** the [security review](docs/security-audit.md) records how the local services are protected, what was fixed for this release, and what remains open.
- **Model API keys are stored in plain text** in the local `model_config.json`. That file is excluded from Git and from the release packages, but anyone who can read your project folder can read the keys. Do not commit, zip, sync, or share it, and prefer a dedicated key with a spending limit where your model provider supports one. Encrypted at-rest storage is planned for a later release.
- **Contract text leaves this computer** when you run Ask, Summary, or Review: it is sent to the model service you configure. Local configuration does not mean fully offline operation.

- [Chinese user guide](USER_GUIDE.zh-CN.md): installation, configuration, feature screenshots, Policy maintenance and sharing, model data handling, and prompt locations.
- [Fictional sample contract](docs/examples/Ally-Legal-Flex-demo.docx): for exploring the features and following the guide's screenshots.
- [First launch and desktop launcher](USER_GUIDE.zh-CN.md#one-click-start): Windows and Mac instructions.
- `tests/`: automated checks for development and maintenance. Ordinary users do not need to run them, and they are not executed when the add-in starts.
- [Help](https://localhost:3000/help.html): local help available while the add-in is running.

For optional backend container deployment, see the [Docker backend documentation](backend/Docker/legal-main-flow-container/README.md). The Word add-in frontend and local Config services run separately from that container. Model configuration files and API keys should remain on the user's computer and should not be committed to a public repository or copied into an image.

## Project origin and licensing

This project is adapted from [Azure-Samples/ally-legal-assistant](https://github.com/Azure-Samples/ally-legal-assistant). The upstream architecture, demonstrations, and deployment instructions are available in the [original repository](https://github.com/Azure-Samples/ally-legal-assistant). This README and the Chinese user guide describe the features and operation of this version.

The original [rights statement in the upstream README](https://github.com/Azure-Samples/ally-legal-assistant#intellectual-property-and-licensing) is retained below:

> This plugin is free to use and modify by anyone. The GitHub repository is also free to use and change.

**Upstream code and attribution:** This fork retains the MIT license declaration from the [upstream package.json](https://github.com/Azure-Samples/ally-legal-assistant/blob/main/package.json), the README rights statement above, the original team attribution below, and existing copyright and license notices in the source files, including Microsoft's notices. Attribution for new contributions does not replace upstream attribution. Upstream copyright years are not inferred or rewritten.

**Additions and modifications in this version:** Silvia Shen licenses additions and modifications under the [MIT License](LICENSE) to the extent she is entitled to do so, with the notice `Copyright (c) 2026 Silvia Shen`. This notice identifies the new contributions in this version and does not change ownership of upstream code or third-party components. See [project background in the user guide](USER_GUIDE.zh-CN.md#project-background) for the changes and their origins.

**Third-party components:** Existing and newly added third-party code, libraries, and resources remain subject to their own licenses. This project's MIT License does not replace those terms. See the [third-party notices](THIRD_PARTY_NOTICES.md) for component sources, licensing information, and applicable copyright notices, and the [license directory](docs/licenses/README.md) for license texts. The inventories describe the current scope of review. Distributions must retain the licenses and applicable NOTICE files required by the components and versions they contain.

Licensing information last updated: 2026-10-18.

<a id="team-behind-ally--ai-contract-assistant"></a>

### Original project team

The following attribution identifies the original project's contributors. It does not indicate that they maintain or support Ally Legal Flex.

- **Esther Dediashvili** – Senior Solution Specialist – AI Global Black Belt, EMEA
- **Lior Armiev** – Senior Technical Specialist – AI Global Black Belt, EMEA
- **Andrew Mackay** – AI Director – Global Black Belts, CEMA

Original upstream contact: [liorarmiev@microsoft.com](mailto:liorarmiev@microsoft.com). This address is retained for attribution. Please direct questions about this fork to its maintainer.

## Collaboration and feedback

The feature design, code changes, and user guide for this version were developed by the project maintainer in collaboration with ChatGPT. Final testing and the pre-release security review were carried out with assistance from DeepSeek.

Issues, suggestions, and pull requests are welcome in the repository that distributes this source package. Contributions are merged after review.
