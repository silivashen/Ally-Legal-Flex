import math
from typing import Optional

from promptflow.core import tool
from promptflow.connections import CustomConnection
from openai import OpenAI
from embedding_config_loader import get_embedding_config


def validate_vector(value, dimensions=None):
    if not isinstance(value, list) or not value:
        raise ValueError("Embedding 模型返回了空向量或无效向量。")
    if dimensions is not None and len(value) != dimensions:
        raise ValueError("Embedding 模型返回的向量维度不一致，请检查模型配置。")
    if any(isinstance(item, bool) or not isinstance(item, (int, float))
           or not math.isfinite(item) for item in value):
        raise ValueError("Embedding 模型返回了非有限数值。")
    vector = [float(item) for item in value]
    magnitude = math.hypot(*vector)
    if not math.isfinite(magnitude) or magnitude == 0:
        raise ValueError("Embedding 模型返回了无效的零向量或过大数值。")
    return vector


def create_embeddings(client, model, texts, dimensions=None):
    """Validate every batch before vectors are cached or compared."""
    try:
        response = client.embeddings.create(model=model, input=texts)
    except Exception:
        # Provider errors may contain request text or credentials.
        raise RuntimeError(
            "Embedding 请求失败，请检查前端配置的 API 地址、模型、密钥及网络。"
        ) from None
    data = getattr(response, "data", None)
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("Embedding 模型返回的向量数量与输入数量不一致。")
    indexes = [getattr(item, "index", None) for item in data]
    if (any(isinstance(index, bool) or not isinstance(index, int) for index in indexes)
            or sorted(indexes) != list(range(len(texts)))):
        raise ValueError("Embedding 模型返回了重复或无效的向量序号。")
    vectors = []
    for item in sorted(data, key=lambda item: item.index):
        vector = validate_vector(getattr(item, "embedding", None), dimensions)
        if dimensions is None:
            dimensions = len(vector)
        vectors.append(vector)
    return vectors


@tool
def my_python_tool(input: str, ally: CustomConnection, policySets: Optional[list] = None) -> list:
    if not isinstance(input, str) or not input.strip():
        raise ValueError("请提供需要生成向量的文本。")
    if policySets == []:
        return []
    config = get_embedding_config(ally)
    client = OpenAI(base_url=config["base_url"], api_key=config["api_key"])
    return create_embeddings(client, config["model"], [input])[0]
