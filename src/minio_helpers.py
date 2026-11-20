import io
import uuid
from datetime import timedelta
from minio import Minio
from minio.error import S3Error
from config import (
    MINIO_HOST, MINIO_PORT, MINIO_ROOT_USER,
    MINIO_ROOT_PASSWORD, MINIO_BUCKET_NAME, MINIO_SECURE,
    MINIO_PRESIGNED_ON_UPLOAD
)
from logs import LOGGER
from typing import Optional, Tuple


class MinioHelper:
    """MinIO 对象存储辅助类"""
    
    def __init__(self):
        """初始化 MinIO 客户端"""
        try:
            self.client = Minio(
                f"{MINIO_HOST}:{MINIO_PORT}",
                access_key=MINIO_ROOT_USER,
                secret_key=MINIO_ROOT_PASSWORD,
                secure=MINIO_SECURE
            )
            self.bucket_name = MINIO_BUCKET_NAME
            self._ensure_bucket_exists()
            LOGGER.info(f"MinIO 客户端初始化成功，连接到: {MINIO_HOST}:{MINIO_PORT}")
        except Exception as e:
            LOGGER.error(f"MinIO 客户端初始化失败: {e}")
            raise e
    
    def _ensure_bucket_exists(self):
        """确保存储桶存在，如果不存在则创建"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                LOGGER.info(f"创建新的存储桶: {self.bucket_name}")
            else:
                LOGGER.info(f"存储桶已存在: {self.bucket_name}")
        except S3Error as e:
            LOGGER.error(f"检查或创建存储桶失败: {e}")
            raise e

    def health(self):
        try:
            return self.client.bucket_exists(self.bucket_name)
        except Exception:
            return False

    def upload_image(self, image_content: bytes, table_name: str, file_extension: str = ".jpg") -> Tuple[str, str]:
        """上传图片并返回 (对象名, 预签名URL)。

        性能：预签名 URL 默认不生成（业务未使用），需要时把 MINIO_PRESIGNED_ON_UPLOAD 设为 true。
        """
        try:
            # 用图库名做前缀 + UUID，保证对象名全局唯一
            unique_id = uuid.uuid4().hex
            object_name = f"{table_name}/{unique_id}{file_extension}"

            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=io.BytesIO(image_content),
                length=len(image_content),
                content_type=f"image/{file_extension.lstrip('.')}"
            )

            # 仅在显式开启时生成预签名 URL，避免每次上传多一次签名计算
            presigned_url = ""
            if MINIO_PRESIGNED_ON_UPLOAD:
                presigned_url = self.client.presigned_get_object(
                    bucket_name=self.bucket_name,
                    object_name=object_name,
                    expires=timedelta(days=7)
                )
            return object_name, presigned_url

        except S3Error as e:
            LOGGER.error(f"上传图片到 MinIO 失败: {e}")
            raise e
    
    def download_image(self, object_name: str) -> bytes:

        try:
            response = self.client.get_object(self.bucket_name, object_name)
            image_content = response.read()
            response.close()
            response.release_conn()
            
            LOGGER.info(f"成功从 MinIO 下载图片: {object_name}")
            return image_content
            
        except S3Error as e:
            LOGGER.error(f"从 MinIO 下载图片失败: {e}")
            raise e
    
    def delete_image(self, object_name: str) -> bool:
        """
        从 MinIO 删除图片
        
        Args:
            object_name: 对象名称
            
        Returns:
            bool: 删除是否成功
        """
        try:
            self.client.remove_object(self.bucket_name, object_name)
            return True
            
        except S3Error as e:
            LOGGER.error(f"从 MinIO 删除图片失败: {e}")
            return False
    
    def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        """
        获取对象的预签名访问URL
        
        Args:
            object_name: 对象名称
            expires: URL过期时间（秒）
            
        Returns:
            str: 预签名URL
        """
        try:
            url = self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=timedelta(seconds=expires)
            )
            return url
            
        except S3Error as e:
            LOGGER.error(f"获取预签名URL失败: {e}")
            raise e
    
    def list_images(self, table_name: str, limit: Optional[int] = None) -> list:
        """
        列出指定表名下的所有图片
        
        Args:
            table_name: 表名
            limit: 限制返回数量
            
        Returns:
            list: 对象列表
        """
        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name,
                prefix=f"{table_name}/",
                recursive=True
            )
            
            result = []
            count = 0
            for obj in objects:
                if limit and count >= limit:
                    break
                result.append({
                    'object_name': obj.object_name,
                    'size': obj.size,
                    'last_modified': obj.last_modified
                })
                count += 1
            
            return result
            
        except S3Error as e:
            LOGGER.error(f"列出图片失败: {e}")
            raise e

    def delete_by_prefix(self, table_name: str) -> bool:
        """删除某图库前缀下的全部对象（用于级联删除图库）。"""
        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name, prefix=f"{table_name}/", recursive=True
            )
            for obj in objects:
                self.client.remove_object(self.bucket_name, obj.object_name)
            return True
        except S3Error as e:
            LOGGER.error(f"批量删除对象失败: {e}")
            return False