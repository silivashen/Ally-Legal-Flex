import json
from pathlib import Path
from openai import OpenAI


def get_local_config_dir():
    """Use the frontend's project directory, or the standalone flow directory."""
    flow_dir = Path(__file__).resolve().parent
    config_dir = flow_dir
    for parent in flow_dir.parents:
        if (parent / "package.json").is_file() and (parent / "src").is_dir():
            config_dir = parent
            break
    return config_dir


def find_local_config(filename):
    """Read only the authoritative frontend config, never an old copied file."""
    config_path = get_local_config_dir() / filename
    if not config_path.is_file():
        # A missing project config must not fall back to an old copied policy.
        raise FileNotFoundError(f"Local configuration not found: {config_path}")
    return config_path


def get_chat_client_and_model(ally):
    try:
        config_path = find_local_config("model_config.json")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "未找到本机模型配置文件，请先在前端模型设置中点击 Apply Model。"
        ) from exc
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法读取本机模型配置文件。") from exc
    if not isinstance(cfg, dict):
        raise RuntimeError("本机模型配置格式无效。")

    base_url = str(cfg.get("base_url") or "").strip()
    model = str(cfg.get("model") or "").strip()
    api_key = str(cfg.get("api_key") or "").strip()
    if not base_url or not model or not api_key:
        raise RuntimeError(
            "本机模型配置不完整。请在模型设置中填写 API Base URL、"
            "Model 和 API Key，然后点击 Apply Model。"
        )
    # An existing frontend configuration is authoritative; never use Azure fallback.
    return OpenAI(base_url=base_url, api_key=api_key), model
