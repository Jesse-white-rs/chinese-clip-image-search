import io
import os
import threading
import torch
from PIL import Image
import cn_clip.clip as clip
from cn_clip.clip import load_from_name
from config import MODEL_NAME, MODEL_DIR, DEVICE, ENCODE_BATCH_SIZE, INFER_CONCURRENCY
from logs import LOGGER

# 各模型对应的离线权重文件名，用于判断是否存在本地权重
_WEIGHTS = {
    "RN50": "chinese_clip_rn50.pt",
    "ViT-B-16": "chinese_clip_vit_b16.pt",
    "ViT-L-14": "chinese_clip_vit_l14.pt",
    "ViT-L-14-336": "chinese_clip_vit_l14_336px.pt",
    "ViT-H-14": "chinese_clip_vit_h14.pt",
}


class ChineseClipModel:
    """chinese-clip 模型单例：图像与文本统一输出 1024 维 L2 归一化特征。

    采用双重检查锁保证多线程（gunicorn 多 worker / FastAPI 线程池）下只加载一次。
    离线优先：若 MODEL_DIR 中已有权重文件则直接读取，否则自动联网下载到该目录。
    """

    _instance = None
    _lock = threading.Lock()
    # 并发推理信号量：允许 N 个推理同时进行以吃满多核，
    # 配合 OMP_NUM_THREADS=1 避免 PyTorch 内部线程互相争抢导致长尾。
    _infer_sem = threading.Semaphore(max(1, INFER_CONCURRENCY))

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._load()
                    cls._instance = obj
        return cls._instance

    def _load(self):
        """加载模型权重并切换到推理模式。"""
        os.makedirs(MODEL_DIR, exist_ok=True)
        weight_file = _WEIGHTS.get(MODEL_NAME, f"{MODEL_NAME}.pt")
        weight_path = os.path.join(MODEL_DIR, weight_file)
        if os.path.exists(weight_path):
            LOGGER.info(f"使用离线模型权重: {weight_path}")
        else:
            LOGGER.info(f"未找到离线权重，将自动下载到: {MODEL_DIR}")

        # 显式指定设备时优先用指定值，否则自动选择 GPU
        self.device = DEVICE or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model, self.preprocess = load_from_name(
            MODEL_NAME, device=self.device, download_root=MODEL_DIR
        )
        self.model.eval()          # 关闭 dropout / BN 更新
        self.name = MODEL_NAME
        self.ready = True
        LOGGER.info(f"Chinese-CLIP 加载完成: {MODEL_NAME}, 设备: {self.device}")

    def health(self):
        """返回健康状态信息，供 /health 接口使用。"""
        return {"model": self.name, "device": self.device, "dim": 1024, "ready": self.ready}

    @staticmethod
    def _open_image(source):
        """把文件路径 / 字节 / PIL 对象统一转换为 RGB 图像。"""
        if isinstance(source, str):
            return Image.open(source).convert("RGB")
        if isinstance(source, (bytes, bytearray)):
            return Image.open(io.BytesIO(source)).convert("RGB")
        if isinstance(source, Image.Image):
            return source.convert("RGB")
        raise TypeError(f"不支持的图片输入类型: {type(source)}")

    def _features_to_list(self, feats):
        """特征矩阵做 L2 归一化后转成 Python 列表。"""
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.float().cpu().numpy().tolist()

    @torch.inference_mode()
    def encode_image(self, source):
        """编码单张图片，返回 1024 维归一化向量。"""
        tensor = self.preprocess(self._open_image(source)).unsqueeze(0).to(self.device)
        with self._infer_sem:
            return self._features_to_list(self.model.encode_image(tensor))[0]

    @torch.inference_mode()
    def encode_images(self, sources, batch_size=None):
        """批量编码图片：分块送入模型，减少 GPU/CPU 上下文切换。"""
        batch_size = batch_size or ENCODE_BATCH_SIZE
        results = []
        for start in range(0, len(sources), batch_size):
            batch = sources[start:start + batch_size]
            tensors = torch.stack(
                [self.preprocess(self._open_image(src)) for src in batch]
            ).to(self.device)
            with self._infer_sem:
                results.extend(self._features_to_list(self.model.encode_image(tensors)))
            del tensors  # 及时释放显存/内存
        return results

    @torch.inference_mode()
    def encode_text(self, text):
        """编码中文文本，直接 tokenize，无需外部翻译。"""
        tokens = clip.tokenize(text).to(self.device)
        with self._infer_sem:
            return self._features_to_list(self.model.encode_text(tokens))[0]
